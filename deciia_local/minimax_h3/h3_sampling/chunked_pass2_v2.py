# -*- coding: utf-8 -*-
"""Deciia 分块 PASS 2 V2（双开关：时间分块 / 空间分块）— 自有代码，居 ComfyUI_Deciia_Local（本地专用不发布，含 T8 GPL 衍生骨架）

与 T8 的关系：运行时互操作（与 chunked_pass2.py 同策略，见 docs/upstream-dependencies.md）。
- T8 只提供稳定原语（sample_piece / rebind_dual_clock_sampler / 时间分段 / 条件重锚 /
  plan 构建），全部动态 import，T8 可独立更新。
- 本文件拥有全部自有逻辑：step_sync 零加噪执行器、空间 tile 循环（核心区独占+高斯羽化
  融合、audio 均值、keyframe 尺寸检查、auto-axis 切长边、可选班长 RoPE 全局坐标注入）、
  refined_exp 音频截获拼接、双开关路由四格矩阵。

历史：step_sync/空间tile初版曾直接写在 T8 源文件内（2026-09-29），同日迁出，
T8 恢复上游纯净。备份: D:/workspace/_node_backups/t8_chunked_final_20260929_2138.py
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import logging
import math
import os
import sys
import time
import types as _types

import torch

from comfy_api.latest import io

log = logging.getLogger(__name__)

_T8_DIRNAME = "comfyui-minimax-h3-audio-T8"
_PKG_NAME = "_deciia_t8_pkg_v2"
_CHUNKED_MOD = "chunked_two_pass_upscale_advanced"
_LOAD_ERROR: str | None = None


def _load_t8_chunked():
    """优先复用已加载的 T8 chunked 模块；否则按合成包名加载（目录含连字符）。"""
    global _LOAD_ERROR
    if _LOAD_ERROR:
        raise ImportError(_LOAD_ERROR)
    real = sys.modules.get(f"h3_t8.{_CHUNKED_MOD}")
    if real is not None:
        return real
    for mod in list(sys.modules.values()):
        fn = getattr(mod, "__file__", None)
        if fn and os.path.basename(str(fn)) == _CHUNKED_MOD + ".py" and _T8_DIRNAME in str(fn):
            return mod
    # 本文件在 <custom_nodes>/ComfyUI_Deciia_All/minimax_h3/h3_sampling/ 下,
    # T8 与本包同级: <custom_nodes>/comfyui-minimax-h3-audio-T8/h3_t8/…
    plugins_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    cand = os.path.join(plugins_root, _T8_DIRNAME, "h3_t8", _CHUNKED_MOD + ".py")
    if not os.path.exists(cand):
        _LOAD_ERROR = f"T8 plugin not found at {cand}"
        raise ImportError(_LOAD_ERROR)
    # 注册合成父包(供 T8 模块内相对 import 解析), 与旧版 chunked_pass2.py 同策略
    parent = sys.modules.get(_PKG_NAME)
    if parent is None:
        parent = _types.ModuleType(_PKG_NAME)
        parent.__path__ = [os.path.dirname(cand)]
        sys.modules[_PKG_NAME] = parent
    spec = _ilu.spec_from_file_location(f"{_PKG_NAME}.{_CHUNKED_MOD}", cand,
                                        submodule_search_locations=[os.path.dirname(cand)])
    module = _ilu.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_T8 = _load_t8_chunked()

# ── T8 稳定原语(运行时取) ──
sample_piece = _T8.sample_piece
rebind_dual_clock_sampler = _T8.rebind_dual_clock_sampler
compute_temporal_segments = _T8.compute_temporal_segments
frames_for_tokens = _T8.frames_for_tokens
reanchor_conditioning = _T8.reanchor_conditioning
_append_video = _T8._append_video
# _append_audio_lena 为自有实现(见下), 不取自 T8
_temporal_overlap_mask = _T8._temporal_overlap_mask
_nested_parts = _T8._nested_parts
_build_global_target_av_noise = _T8._build_global_target_av_noise
build_chunked_two_pass_masked_low_sigma_plan = _T8.build_chunked_two_pass_masked_low_sigma_plan
PLAN_SCHEMA_GLOBAL_NOISE_V2 = _T8.PLAN_SCHEMA_GLOBAL_NOISE_V2
PLAN_SCHEMA_LOW_SIGMA_V3 = _T8.PLAN_SCHEMA_LOW_SIGMA_V3
PLAN_SCHEMA_MASKED_LOW_SIGMA_V4 = _T8.PLAN_SCHEMA_MASKED_LOW_SIGMA_V4
learned_upscale_h3_av_latent = _T8.learned_upscale_h3_av_latent
FRAME_RESCALE = _T8.FRAME_RESCALE
comfy = _T8.comfy

# 班长 RoPE 全局坐标注入(可选依赖,缺则禁用) — 与 T8 内实现同源同语义
_TILE_POS_AVAILABLE = False
try:
    import importlib as _il
    _tile_pos_mod = _il.import_module(
        "custom_nodes.ComfyUI-Banzhang-All.banzhang_h3_tile_pos"
    )
    _install_tile_pos = _tile_pos_mod.install
    _set_tile_offset = _tile_pos_mod.set_tile_offset
    _clear_tile_offset = _tile_pos_mod.clear_tile_offset
    _TILE_POS_AVAILABLE = True
except Exception:  # pragma: no cover - banzhang pack missing
    _tile_pos_mod = None



def _append_audio_lena(accumulated, chunk, start: int, end: int):
    """Concatenate refined audio chunks along the absolute audio timeline."""
    total = max(int(accumulated.shape[-1]), end)
    out = torch.zeros(
        (*accumulated.shape[:-1], total),
        device=accumulated.device,
        dtype=accumulated.dtype,
    )
    out[..., : accumulated.shape[-1]] = accumulated
    seg = chunk[..., : end - start]
    out[..., start:end] = seg
    return out

# ── 节点层常量 ──
_VAE_DOWNSAMPLE = 16
_AUDIO_OUTPUTS = ("refined_exp", "preserve_first_pass")
_DEFAULT_UPSCALER = "minimax_h3_latent_upscaler_3d_fp16.safetensors"
_CTRL_TEMPORAL = {"ctrl": {"source": "temporal_chunking", "value": [True]}}
_CTRL_SPATIAL = {"ctrl": {"source": "spatial_chunking", "value": [True]}}

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def _spatial_tile_windows(dim_len: int, n_tiles: int, overlap: int):
    """Single-axis stripe tiling (GH/Banzhang semantics).

    stride = dim_len // n_tiles, tile = stride + 2*overlap (each tile pokes
    `overlap` cells into BOTH neighbours), starts = i*stride - overlap.
    All boundaries even so the DiT 2x2 patch never straddles a tile edge.
    Returns list of (start, end). Caller computes core windows separately.
    """
    dim_len = int(dim_len)
    n_tiles = max(1, int(n_tiles))
    overlap = max(0, int(overlap) // 2 * 2)
    if n_tiles <= 1 or dim_len <= 8:
        return [(0, dim_len)]
    stride = int(round(dim_len / n_tiles))
    stride -= stride % 2
    stride = max(2, stride)
    tile_size = stride + 2 * overlap
    if tile_size >= dim_len * 0.9:
        return [(0, dim_len)]
    starts = []
    for i in range(n_tiles):
        st = max(0, i * stride - overlap)
        st -= st % 2
        starts.append(st)
    last = max(0, (dim_len - tile_size) & ~1)
    if last > starts[-1]:
        starts.append(last)
    dedup = []
    for st in starts:
        if not dedup or st > dedup[-1]:
            dedup.append(st)
    return [(st, min(dim_len, st + tile_size)) for st in dedup]


def _core_window_1d(tile_len: int, c_lo: int, c_hi: int, feather: int, dtype, device):
    """Banzhang-style ownership window: 1.0 across the core, gaussian-decayed
    shoulders of width `feather` outside the core. Neighbouring cores tile
    the axis exactly, so summed weights stay ~=1 everywhere."""
    import numpy as np
    xs = np.arange(tile_len, dtype=np.float32)
    w = np.ones(tile_len, dtype=np.float32)
    feather = max(1, int(feather))
    if c_lo > 0 and feather > 0:
        g = np.exp(-0.5 * ((xs[:c_lo] - c_lo) / (feather / 2.0)) ** 2)
        w[:c_lo] = np.minimum(w[:c_lo], g + 1e-6)
    if c_hi < tile_len and feather > 0:
        g = np.exp(-0.5 * ((xs[c_hi:] - c_hi) / (feather / 2.0)) ** 2)
        w[c_hi:] = np.minimum(w[c_hi:], g + 1e-6)
    return torch.from_numpy(w).to(dtype=dtype, device=device)


def _gaussian_feather_1d(dim_len: int, start: int, end: int, sigma_scale: float = 0.42):
    """1-D gaussian weight ramp for one tile on [start, end).

    Peaks at 1.0 across the core, gaussian-decays across the feathered
    overlap toward each neighbouring tile. Combined with the division by
    the summed weight map this keeps total weight ~1 everywhere.
    """
    import numpy as np
    n = end - start
    xs = np.arange(n, dtype=np.float32)
    w = np.ones(n, dtype=np.float32)
    # left ramp: distance from tile start to previous tile's reach
    ramp = max(1, int(round(sigma_scale * n)))
    ramp = min(ramp, n // 2)
    if start > 0 and ramp > 1:
        g = np.exp(-0.5 * ((xs[:ramp] - 0) / (ramp / 2.5)) ** 2)
        w[:ramp] = np.minimum(w[:ramp], g + 1e-6)
    if end < dim_len and ramp > 1:
        g = np.exp(-0.5 * ((xs[n - ramp :] - (n - 1)) / (ramp / 2.5)) ** 2)
        w[n - ramp :] = np.minimum(w[n - ramp :], g + 1e-6)
    return w


def _crop_conditioning_spatial(conditioning, axis: int, start: int, end: int):
    """Crop keyframe latents inside conditioning to one spatial tile.

    Crops (never resizes) minimax_keyframe latents along H (axis=-2) or
    W (axis=-1) so reference imagery stays pixel-aligned with the tile.
    """
    output = []
    for tensor, metadata in conditioning:
        updated = dict(metadata)
        keyframes = updated.get("minimax_keyframes")
        if keyframes:
            cropped = []
            for kf in keyframes:
                kf = dict(kf)
                latent = kf.get("latent")
                if latent is not None:
                    if axis == 3:
                        kf["latent"] = latent[..., start:end, :].contiguous()
                    else:
                        kf["latent"] = latent[..., :, start:end].contiguous()
                cropped.append(kf)
            updated["minimax_keyframes"] = cropped
        output.append([tensor, updated])
    return output


def _adapt_and_crop_conditioning_spatial(conditioning, axis, start, end, H_full, W_full):
    """Banzhang rule: keyframe latents matching the canvas size are kept and
    cropped to the tile; mismatched (low-res anchor) keyframes are dropped to
    avoid ghosting/blur from a misaligned hard anchor."""
    kept = []
    for tensor, metadata in conditioning:
        updated = dict(metadata)
        keyframes = updated.get("minimax_keyframes")
        if keyframes:
            ok = True
            for kf in keyframes:
                latent = kf.get("latent")
                if latent is not None and (
                    int(latent.shape[-2]) != int(H_full) or int(latent.shape[-1]) != int(W_full)
                ):
                    ok = False
                    break
            if ok:
                updated = dict(_crop_conditioning_spatial([[tensor, updated]], axis, start, end)[0][1])
            else:
                updated.pop("minimax_keyframes", None)
        kept.append([tensor, updated])
    return kept


def _blend_spatial_tiles(tiles, axis, dim_len, windows, feather, dtype, device, cores):
    """Core-ownership fusion: each tile contributes 1.0 on its core, gaussian
    shoulders blend across the overlap context zones. Returns full-axis tensor."""
    shape = list(tiles[0].shape)
    shape[axis] = dim_len
    blended = torch.zeros(shape, dtype=dtype, device=device)
    weight = torch.zeros(shape, dtype=dtype, device=device)
    for t, (st, en), (c_lo, c_hi) in zip(tiles, windows, cores):
        w1d = _core_window_1d(en - st, c_lo, c_hi, feather, dtype, device)
        view_local = [1] * len(shape)
        view_local[axis] = en - st
        wt_local = w1d.view(view_local)
        if axis == 3:
            blended[..., st:en, :] += t * wt_local
            weight[..., st:en, :] += wt_local
        else:
            blended[..., :, st:en] += t * wt_local
            weight[..., :, st:en] += wt_local
    return blended / weight.clamp(min=1e-6)


def execute_step_sync_two_pass_upscale(
    model,
    conditioning,
    latent,
    noise,
    sampler,
    sigmas,
    plan,
    *,
    negative=None,
    cfg=1.0,
    spatial_tile_axis=0,
    spatial_n_tiles=2,
    spatial_overlap_px=128,
    spatial_feather=8,
    spatial_global_pos=False,
):
    """Step-synchronous temporal chunked PASS 2.

    Outer loop walks the refine sigma schedule one Euler step at a time; the
    inner loop advances every temporal chunk through that single step, then the
    per-step results are merged back into one global video latent (owned
    overlap: locked guard + smoothstep transition) before the next step runs.
    Chunk trajectories are re-aligned at every step, so per-chunk lens drift
    that the chunk-outer loop allows is structurally impossible here.

    Audio stays joint-sampled per chunk through the same steps; the final-step
    audio of each chunk is captured by the sample_piece wrapper installed by
    the caller (same mechanism as the guarded path), so refined-audio merging
    is unchanged.
    """
    if plan.get("schema") not in {
        PLAN_SCHEMA_GLOBAL_NOISE_V2,
        PLAN_SCHEMA_LOW_SIGMA_V3,
        PLAN_SCHEMA_MASKED_LOW_SIGMA_V4,
    }:
        raise ValueError(
            "step_sync requires a plan from the T8 Chunked Two-Pass Plan nodes"
        )
    video, audio = _nested_parts(latent["samples"], name="latent samples")
    video = video.to(comfy.model_management.intermediate_device())
    audio = audio.to(comfy.model_management.intermediate_device())
    target_width = int(plan["target_width"])
    target_height = int(plan["target_height"])

    sig = torch.as_tensor(sigmas, dtype=torch.float32).flatten()
    if sig.numel() < 2 or float(sig[-1]) != 0.0:
        raise ValueError(
            "step_sync expects a refine sigma schedule ending in 0.0"
        )
    steps = sig.numel() - 1

    (
        global_video_noise,
        global_audio_noise,
        _noise_policy,
    ) = _build_global_target_av_noise(noise, latent, video, audio, plan)

    frame_count = frames_for_tokens(int(video.shape[2]))
    if plan.get("temporal_strategy", "full_clip_safe") == "full_clip_safe":
        segments = [(0, 0, int(video.shape[2]), frame_count)]
    else:
        segments, frame_count = compute_temporal_segments(
            int(video.shape[2]),
            int(plan["temporal_chunk_frames"]),
            int(plan["temporal_overlap_frames"]),
        )

    if plan.get("spatial_strategy", "independent_tiles_exp") != "full_frame_safe":
        raise ValueError(
            "step_sync supports full_frame_safe spatial strategy only "
            "(this workflow never enables spatial tiling)"
        )
    _pass2_t0 = time.time()

    # 1) Upscale every chunk once (learned upscaler, unchanged), keep per-chunk state.
    chunk_states = []
    for index, (start_token, start_frame, end_token, end_frame) in enumerate(segments):
        chunk_video = video[:, :, start_token:end_token].contiguous()
        audio_start = round(start_frame * FRAME_RESCALE)
        audio_end = min(audio.shape[-1], round(end_frame * FRAME_RESCALE))
        chunk_audio = audio[..., audio_start:audio_end].contiguous()
        chunk_latent = {
            "samples": comfy.nested_tensor.NestedTensor((chunk_video, chunk_audio))
        }
        upscaled, _, _, _upscale_report = learned_upscale_h3_av_latent(
            chunk_latent,
            plan["model_name"],
            "target_dimensions",
            2.0,
            1.0,
            target_width,
            target_height,
            "honor_dimensions_exp",
            2.0,
            plan["precision"],
            plan["release_policy"],
        )
        chunk_states.append(
            {
                "index": index,
                "start_token": start_token,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "audio_start": audio_start,
                "audio_end": audio_end,
                "video": upscaled["samples"].tensors[0].contiguous(),
                "audio": upscaled["samples"].tensors[1].contiguous(),
                "conditioning": reanchor_conditioning(
                    conditioning,
                    start_frame,
                    end_frame,
                    tuple(upscaled["samples"].tensors[0].shape[-2:]),
                ),
            }
        )

    spatial_tile_axis = int(spatial_tile_axis)
    spatial_n_tiles = int(spatial_n_tiles)
    spatial_overlap_px = int(spatial_overlap_px)
    spatial_feather = int(spatial_feather)
    spatial_global_pos = bool(spatial_global_pos) and _TILE_POS_AVAILABLE
    if spatial_global_pos:
        try:
            _install_tile_pos(model)
        except Exception as error:  # pragma: no cover
            print(
                "[DeciiaChunkedPass2][step_sync] ⚠ 班长全局坐标 wrapper 安装失败, "
                f"退回无注入模式: {error}",
                flush=True,
            )
            spatial_global_pos = False
    _ov_latent = max(0, int(round(spatial_overlap_px / 16.0)))
    if spatial_overlap_px > 0 and _ov_latent == 0:
        _ov_latent = 1

    def spatial_overlap_latent():
        return _ov_latent
    # 2) Step-synchronous loop: outer = sigma step, inner = chunks.
    locked_profile = None
    _total_units = steps * len(chunk_states)
    _step_progress = comfy.utils.ProgressBar(_total_units)
    for step_index in range(steps):
        print(
            "[DeciiaChunkedPass2][step_sync] 步 {}/{} (σ={:.4f}), 累计 {:.0f}s".format(
                step_index + 1,
                steps,
                float(sig[step_index]),
                time.time() - _pass2_t0,
            ),
            flush=True,
        )
        step_sigmas = sig[step_index : step_index + 2].clone().to(
            device=video.device if video.is_cuda else torch.device("cpu"),
            dtype=global_video_noise.dtype if global_video_noise is not None else torch.float32,
        )
        for state in chunk_states:
            chunk_video = state["video"]
            chunk_audio = state["audio"]
            joint_audio = True
            audio_mask = torch.ones_like(chunk_audio) if joint_audio else torch.zeros_like(chunk_audio)
            video_mask = torch.ones(
                (1, 1, int(chunk_video.shape[2]), 1, 1),
                dtype=chunk_video.dtype,
                device=chunk_video.device,
            )
            if state["index"] and locked_profile is not None:
                # Keep the guard region frozen to the merged global latent.
                locked_tokens, transition_tokens = locked_profile
                if locked_tokens:
                    chunk_video = chunk_video.clone()
                    chunk_video[:, :, :locked_tokens] = state["merged_head"]
                    mask, _l, _t = _temporal_overlap_mask(
                        int(chunk_video.shape[2]),
                        locked_tokens,
                        dtype=chunk_video.dtype,
                        device=chunk_video.device,
                    )
                    video_mask = mask
            # --- spatial tiling (Plan A): cut this chunk along ONE spatial axis ---
            # axis semantics: 0 = auto (cut the LONGER edge), 3 = H, 4 = W
            sp_axis = int(spatial_tile_axis) if spatial_tile_axis else 0
            H_len = int(chunk_video.shape[3])
            W_len = int(chunk_video.shape[4])
            if sp_axis == 3:
                axis_len = H_len
            elif sp_axis == 4:
                axis_len = W_len
            elif int(spatial_n_tiles) > 1:
                # auto: choose the longer spatial edge so tiles stay close to
                # square (model-friendly aspect), cutting VRAM identically
                sp_axis = 3 if H_len >= W_len else 4
                axis_len = H_len if sp_axis == 3 else W_len
            else:
                axis_len = 0
            windows = None
            cores = None
            if sp_axis and int(spatial_n_tiles) > 1:
                wins = _spatial_tile_windows(axis_len, spatial_n_tiles, spatial_overlap_latent())
                if len(wins) > 1:
                    windows = wins
                    # core ownership: neighbour boundary = next start + overlap (Banzhang rule)
                    ov = max(0, int(spatial_overlap_latent()) // 2 * 2)
                    cores = []
                    for idx, (st, en) in enumerate(windows):
                        c_lo = 0 if idx == 0 else min(axis_len, st + ov) - st
                        c_hi = (axis_len - st if idx == len(windows) - 1
                                else min(axis_len, windows[idx + 1][0] + ov) - st)
                        cores.append((max(0, c_lo), max(c_lo + 2, c_hi)))
            if windows is None:
                piece = {
                    "samples": comfy.nested_tensor.NestedTensor((chunk_video, chunk_audio)),
                    "noise_mask": comfy.nested_tensor.NestedTensor((video_mask, audio_mask)),
                }
                piece_sampler = rebind_dual_clock_sampler(model, piece, sampler)
                prepared_noise = None
                if global_video_noise is not None:
                    tile_noise = global_video_noise[
                        :, :, state["start_token"] : state["start_token"] + chunk_video.shape[2]
                    ].to(chunk_video.dtype)
                    audio_noise = (
                        global_audio_noise[..., state["audio_start"] : state["audio_end"]]
                        .to(chunk_audio.dtype)
                        .contiguous()
                        if global_audio_noise is not None
                        else torch.zeros_like(chunk_audio)
                    )
                    prepared_noise = comfy.nested_tensor.NestedTensor((tile_noise, audio_noise))
                if step_index > 0:
                    # After step 0 the chunk latent already carries sigma_i noise
                    # (KSAMPLER re-noises latent_image by sigmas[0]); injecting the
                    # global noise again would double-noise and destroy the
                    # trajectory. Pass exact zeros so noise_scaling becomes a no-op
                    # and Euler advances x_i from sigma_i to sigma_{i+1} untouched.
                    prepared_noise = comfy.nested_tensor.NestedTensor(
                        (
                            torch.zeros_like(chunk_video),
                            torch.zeros_like(chunk_audio),
                        )
                    )
                sampled = sample_piece(
                    piece,
                    state["conditioning"],
                    model,
                    noise,
                    piece_sampler,
                    step_sigmas,
                    negative,
                    cfg,
                    prepared_noise=prepared_noise,
                )
                state["video"] = sampled.tensors[0].to(comfy.model_management.intermediate_device())
                state["audio"] = sampled.tensors[1].to(comfy.model_management.intermediate_device())
            else:
                tile_videos = []
                tile_audios = []
                for (st, en) in windows:
                    if sp_axis == 3:
                        t_video = chunk_video[..., st:en, :].contiguous()
                    else:
                        t_video = chunk_video[..., :, st:en].contiguous()
                    t_mask = video_mask
                    piece = {
                        "samples": comfy.nested_tensor.NestedTensor((t_video, chunk_audio)),
                        "noise_mask": comfy.nested_tensor.NestedTensor((t_mask, audio_mask)),
                    }
                    piece_sampler = rebind_dual_clock_sampler(model, piece, sampler)
                    t_cond = _adapt_and_crop_conditioning_spatial(
                        state["conditioning"], sp_axis, st, en, H_len, W_len
                    )
                    _tile_pos_to = None
                    if spatial_global_pos:
                        _tile_pos_to = (
                            model.model_options.setdefault("transformer_options", {})
                            if hasattr(model, "model_options")
                            else None
                        )
                        if _tile_pos_to is not None:
                            if sp_axis == 3:
                                _set_tile_offset(
                                    _tile_pos_to, H_len, W_len, en - st, W_len, st // 2, 0
                                )
                            else:
                                _set_tile_offset(
                                    _tile_pos_to, H_len, W_len, H_len, en - st, 0, st // 2
                                )
                    prepared_noise = None
                    if global_video_noise is not None:
                        if sp_axis == 3:
                            t_noise = global_video_noise[
                                :, :, state["start_token"] : state["start_token"] + t_video.shape[2], st:en, :
                            ].to(t_video.dtype)
                        else:
                            t_noise = global_video_noise[
                                :, :, state["start_token"] : state["start_token"] + t_video.shape[2], :, st:en
                            ].to(t_video.dtype)
                        a_noise = (
                            global_audio_noise[..., state["audio_start"] : state["audio_end"]]
                            .to(chunk_audio.dtype)
                            .contiguous()
                            if global_audio_noise is not None
                            else torch.zeros_like(chunk_audio)
                        )
                        prepared_noise = comfy.nested_tensor.NestedTensor((t_noise, a_noise))
                    if step_index > 0:
                        prepared_noise = comfy.nested_tensor.NestedTensor(
                            (
                                torch.zeros_like(t_video),
                                torch.zeros_like(chunk_audio),
                            )
                        )
                    try:
                        sampled = sample_piece(
                            piece,
                            t_cond,
                            model,
                            noise,
                            piece_sampler,
                            step_sigmas,
                            negative,
                            cfg,
                            prepared_noise=prepared_noise,
                        )
                    finally:
                        if _tile_pos_to is not None:
                            _clear_tile_offset(_tile_pos_to)
                    tile_videos.append(sampled.tensors[0].to(comfy.model_management.intermediate_device()))
                    # audio: every tile carries the full timeline (joint AV); average
                    # across tiles (Banzhang rule) to halve variance
                    tile_audios.append(sampled.tensors[1].to(comfy.model_management.intermediate_device()))
                blended = _blend_spatial_tiles(
                    tile_videos,
                    sp_axis,
                    axis_len,
                    windows,
                    spatial_feather,
                    tile_videos[0].dtype,
                    tile_videos[0].device,
                    cores,
                )
                state["video"] = blended
                # 音频不做 tile 均值: 各 tile 音频相位无关, 均值=波形抵消=全程杂音
                # (视频 blend 无此问题)。取首 tile 的一份完整去噪音频即可。
                state["audio"] = tile_audios[0]
            _step_progress.update(1)
            print(
                "[DeciiaChunkedPass2][step_sync] 块 {}/{} @ 步 {}/{} 完成, 总进度 {}/{} ({:.0f}%)".format(
                    state["index"] + 1,
                    len(chunk_states),
                    step_index + 1,
                    steps,
                    step_index * len(chunk_states) + state["index"] + 1,
                    _total_units,
                    100.0 * (step_index * len(chunk_states) + state["index"] + 1) / _total_units,
                ),
                flush=True,
            )

        # 3) Merge this step's chunk videos into one global latent (owned overlap).
        merged = None
        for state in chunk_states:
            if merged is None:
                merged = state["video"].clone()
                locked_profile = _temporal_overlap_mask(
                    int(state["video"].shape[2]),
                    0,
                    dtype=state["video"].dtype,
                    device=state["video"].device,
                )[1:]
                continue
            overlap = max(
                0, int(merged.shape[2]) - int(state["start_token"])
            )
            overlap = min(overlap, int(state["video"].shape[2]))
            chunk_out = state["video"]
            guard = max(1, overlap // 2)
            state["merged_head"] = merged[
                :, :, state["start_token"] : state["start_token"] + guard
            ].clone()
            merged = _append_video(merged, chunk_out, int(state["start_token"]))
            locked_profile = (guard, overlap - guard)
        if merged is None:
            raise RuntimeError("step_sync produced no merged video")

        # 4) Re-seed every chunk head from the merged latent so the next step
        #    starts from one shared trajectory.
        for state in chunk_states:
            if state["index"] == 0:
                state["video"] = merged[:, :, : state["video"].shape[2]].clone()
            else:
                head = merged[
                    :, :, state["start_token"] : state["start_token"] + state["video"].shape[2]
                ]
                if tuple(head.shape) == tuple(state["video"].shape):
                    state["video"] = head.clone()

    final_audio = chunk_states[0]["audio"]
    for state in chunk_states[1:]:
        final_audio = _append_audio_lena(
            final_audio, state["audio"], state["audio_start"], state["audio_end"]
        )
    output = {
        "samples": comfy.nested_tensor.NestedTensor((merged, final_audio))
    }
    report = {
        "schema": plan["schema"] + ".step_sync_exp",
        "temporal_strategy": "step_sync_exp",
        "segment_count": len(chunk_states),
        "steps": steps,
        "sigma_start": float(sig[0]),
        "sigma_end": float(sig[-1]),
        "chunk_tokens": [int(s["video"].shape[2]) for s in chunk_states],
    }
    return output, json.dumps(report, ensure_ascii=False, sort_keys=True)


def _nested_av_parts(latent):
    samples = latent.get("samples") if isinstance(latent, dict) else None
    if not getattr(samples, "is_nested", False):
        raise ValueError(
            "H16-3 PASS2 expects a native MiniMax H3 nested video/audio LATENT"
        )
    parts = getattr(samples, "tensors", None)
    if parts is None:
        parts = samples.unbind()
    parts = tuple(parts)
    if len(parts) != 2:
        raise ValueError("H16-3 PASS2 expects exactly video and audio tensors")
    video, audio = parts
    if video.ndim != 5 or tuple(video.shape[:2]) != (1, 24):
        raise ValueError(f"unexpected H3 video latent shape: {tuple(video.shape)}")
    if audio.ndim != 4 or tuple(audio.shape[:3]) != (1, 32, 2):
        raise ValueError(f"unexpected H3 audio latent shape: {tuple(audio.shape)}")
    if not torch.isfinite(video).all() or not torch.isfinite(audio).all():
        raise ValueError("H16-3 PASS2 received NaN or Inf in the AV latent")
    return video, audio


def _converted_to_raw(converted):
    raw = []
    for item in converted:
        if isinstance(item, dict):
            metadata = dict(item)
            tensor = metadata.pop("cross_attn", None)
            raw.append([tensor, metadata])
        else:
            raw.append(list(item[:2]))
    return raw


def _raw_conditioning_from_guider(guider):
    conditions = (
        getattr(guider, "original_conds", None)
        or getattr(guider, "conds", None)
        or {}
    )
    positive = conditions.get("positive")
    if not positive:
        raise ValueError("guider does not contain positive conditioning")
    negative = conditions.get("negative")
    model = getattr(guider, "model_patcher", None)
    if model is None:
        raise ValueError("guider does not expose the required ModelPatcher")
    return (
        _converted_to_raw(positive),
        _converted_to_raw(negative) if negative else None,
        float(getattr(guider, "cfg", 1.0) or 1.0),
        model,
    )


def _executor_segments(video, plan):
    frame_count = frames_for_tokens(int(video.shape[2]))
    if plan.get("temporal_strategy", "full_clip_safe") == "full_clip_safe":
        return [(0, 0, int(video.shape[2]), frame_count)]
    segments, _ = compute_temporal_segments(
        int(video.shape[2]),
        int(plan["temporal_chunk_frames"]),
        int(plan["temporal_overlap_frames"]),
    )
    return segments


def _rescale_refine_sigmas(sigmas, factor: float):
    """Shrink a refine schedule's redraw budget; keep it strictly descending to 0.

    x_norm ** (1/factor) re-spaces the interior points, then the whole curve is
    scaled by factor so sigma_start drops proportionally (0.5 -> start at ~50%).
    """
    import torch as _torch

    sig = _torch.as_tensor(sigmas, dtype=_torch.float32).flatten().clone()
    if sig.numel() < 2 or float(sig[-1]) != 0.0:
        raise ValueError(
            "chunk_redraw expects a refine sigma schedule ending in 0.0 "
            "(connect DetailMixer refine_sigmas)."
        )
    start = float(sig[0])
    if start <= 0.0:
        raise ValueError("refine sigma schedule starts at 0.0; nothing to rescale")
    inner = sig[:-1] / start
    inner = inner ** (1.0 / factor)
    scaled = inner * (start * factor)
    out = _torch.cat([scaled, _torch.zeros_like(scaled[:1])])
    if not bool(_torch.all(out[:-1] > out[1:])):
        out = _torch.sort(out, descending=True).values
        out[-1] = 0.0
    return out.to(device=sig.device, dtype=sig.dtype)


def _energy_gate(audio: torch.Tensor, kernel: int = 64) -> torch.Tensor:
    """Return a smooth active-audio gate; quiet tails stay on first-pass audio."""
    mono = audio.abs().mean(dim=(0, 1))
    length = int(mono.shape[-1])
    size = max(1, min(int(kernel), length))
    padding = size // 2
    energy = torch.nn.functional.avg_pool1d(
        mono.view(1, 1, -1), size, stride=1, padding=padding
    ).view(-1)[..., :length]
    ordered, _ = torch.sort(energy)
    floor = float(ordered[int(0.2 * length)])
    peak = float(ordered[int(0.9 * length)])
    if peak <= floor * 1.5:
        return torch.ones_like(energy)
    gate = ((energy - floor * 2.0) / max(1e-6, peak - floor * 2.0)).clamp(0.0, 1.0)
    return torch.nn.functional.avg_pool1d(
        gate.view(1, 1, -1), size, stride=1, padding=padding
    ).view(-1)[..., :length]


def _merge_audio_segments(input_audio, segments, refined_chunks, frame_rescale):
    if len(segments) != len(refined_chunks):
        raise RuntimeError(
            f"captured refined audio chunks ({len(refined_chunks)}) do not match "
            f"temporal windows ({len(segments)})"
        )
    total = int(input_audio.shape[-1])
    placed = torch.zeros_like(input_audio)
    weight = torch.zeros((1, 1, 1, total), dtype=torch.float32, device=input_audio.device)
    previous_end = None
    placed_count = 0
    for segment, refined in zip(segments, refined_chunks, strict=True):
        _start_token, start_frame, _end_token, end_frame = segment
        start = int(round(start_frame * frame_rescale))
        end = min(total, int(round(end_frame * frame_rescale)))
        if end <= start:
            continue
        refined = refined.to(device=input_audio.device, dtype=input_audio.dtype)
        span = input_audio[..., start:end]
        if tuple(refined.shape) != tuple(span.shape):
            raise RuntimeError(
                f"refined audio shape {tuple(refined.shape)} != input span {tuple(span.shape)}"
            )
        if previous_end is None or start >= previous_end:
            placed[..., start:end] = refined
            weight[..., start:end] = 1.0
        else:
            overlap = min(previous_end - start, end - start)
            blend = torch.linspace(
                0.0, 1.0, overlap, device=input_audio.device, dtype=input_audio.dtype
            ).view(1, 1, 1, overlap)
            placed[..., start : start + overlap] = (
                placed[..., start : start + overlap] * (1.0 - blend)
                + refined[..., :overlap] * blend
            )
            weight[..., start : start + overlap] = torch.maximum(
                weight[..., start : start + overlap], blend
            )
            placed[..., start + overlap : end] = refined[..., overlap:]
            weight[..., start + overlap : end] = 1.0
        previous_end = end
        placed_count += 1
    if placed_count == 0:
        raise RuntimeError("no refined audio chunk was placed")
    gate = _energy_gate(input_audio).to(input_audio).view(1, 1, 1, -1)
    effective = gate * weight.to(gate)
    return input_audio * (1.0 - effective) + placed * effective, placed_count


def _run_refined_audio(model, positive, latent, noise, sampler, sigmas, plan, negative, cfg, step_sync=False, spatial_tile_axis=0, spatial_n_tiles=2, spatial_overlap_px=128, spatial_feather=8, spatial_global_pos=False):
    global sample_piece
    video, audio = _nested_av_parts(latent)
    original_sample_piece = sample_piece
    captured = []

    _diag_calls = [0]

    def capture(piece, *args, **kwargs):
        _diag_calls[0] += 1
        _nm = piece.get("noise_mask") if isinstance(piece, dict) else None
        if _nm is not None:
            import torch as _tt
            _ntv, _nta = None, None
            try:
                _ntv, _nta = _nm.tensors
                _nta_min = float(_nta.min()) if _nta.numel() else -1
                _nta_max = float(_nta.max()) if _nta.numel() else -1
            except Exception:
                _nta_min = _nta_max = -2
            with open(r"D:/workspace/_probe/refined_diag.log", "a", encoding="utf-8") as _f:
                _f.write(f"mask probe call#{_diag_calls[0]}: audio_mask min={_nta_min} max={_nta_max}\n")
        result = original_sample_piece(piece, *args, **kwargs)
        with open(r"D:/workspace/_probe/refined_diag.log", "a", encoding="utf-8") as _f:
            _nested = getattr(result, "is_nested", False)
            _nt = len(getattr(result, "tensors", ())) if _nested else -1
            _f.write(f"capture call#{_diag_calls[0]}: is_nested={_nested} tensors={_nt}\n")
        if getattr(result, "is_nested", False) and len(result.tensors) == 2:
            if step_sync:
                # step_sync calls sample_piece once per chunk per step; keep only
                # each chunk's LAST step (sigma -> 0) as its finished audio.
                sig = torch.as_tensor(kwargs.get("sigmas", args[6] if len(args) > 6 else None))
                if sig is not None and float(torch.as_tensor(sig).flatten()[-1]) == 0.0:
                    captured.append(result.tensors[1].detach().clone())
            else:
                captured.append(result.tensors[1].detach().clone())
        return result

    sample_piece = capture
    _T8.sample_piece = capture  # guarded 分支走 T8 执行器, 需同时截获 T8 模块属性
    try:
        if step_sync:
            output, report_json = execute_step_sync_two_pass_upscale(
                model, positive, latent, noise, sampler, sigmas, plan,
                negative=negative, cfg=cfg,
                spatial_tile_axis=spatial_tile_axis, spatial_n_tiles=spatial_n_tiles,
                spatial_overlap_px=spatial_overlap_px, spatial_feather=spatial_feather,
                spatial_global_pos=spatial_global_pos,
            )
        else:
            output, report_json = _T8.execute_chunked_two_pass_upscale(
                model, positive, latent, noise, sampler, sigmas, plan,
                negative=negative, cfg=cfg,
            )
    finally:
        sample_piece = original_sample_piece
        _T8.sample_piece = original_sample_piece

    try:
        segments = _executor_segments(video, plan)
        with open(r"D:/workspace/_probe/refined_diag.log", "a", encoding="utf-8") as _f:
            _f.write(f"segments={len(segments)} captured={len(captured)} calls={_diag_calls[0]} step_sync={step_sync} tiles={spatial_n_tiles}\n")
            for _i, _c in enumerate(captured):
                _f.write(f"  captured[{_i}] shape={tuple(_c.shape)}\n")
        # 空间tile: 每个时间块的音频以 n_tiles 份截获(sample_piece 层),
        # 执行器内部对 tile 音频取均值,这里折叠成每块1份与其对齐。
        tiles_per_chunk = max(1, int(spatial_n_tiles)) if step_sync and spatial_n_tiles and int(spatial_n_tiles) >= 2 else 1
        if tiles_per_chunk > 1 and len(captured) == len(segments) * tiles_per_chunk:
            # 与执行器一致: 每 chunk 的多 tile 音频取首 tile(相位无关,不均值)
            captured = [captured[i] for i in range(0, len(captured), tiles_per_chunk)]
        refined_audio, count = _merge_audio_segments(
            audio, segments, captured, FRAME_RESCALE
        )
        samples = output.get("samples")
        if not getattr(samples, "is_nested", False) or len(samples.tensors) != 2:
            raise RuntimeError("chunked executor did not return a nested AV latent")
        output = dict(output)
        output["samples"] = comfy.nested_tensor.NestedTensor(
            (samples.tensors[0], refined_audio)
        )
        report = json.loads(report_json)
        report.update({"audio_output": "refined_exp", "refined_audio_chunks": count,
                       "audio_merge": "absolute_frame_rescale_crossfade_energy_gate"})
        report_json = json.dumps(report, ensure_ascii=False, sort_keys=True)
        log.info(
            "H16-3 refined audio merge complete: chunks=%d, "
            "mode=absolute_frame_rescale_crossfade_energy_gate",
            count,
        )
        return output, report_json
    except Exception as error:  # pragma: no cover - exercised by GPU/worker faults
        log.warning("H16-3 refined audio merge failed; preserving first-pass audio: %s", error)
        return output, report_json


class DeciiaChunkedPass2V2(io.ComfyNode):
    """Drop-in H3 v4 PASS 2 sampler with opt-in refined audio delivery."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaChunkedPass2V2",
            display_name="Deciia 分块PASS2 V2 · 时间/空间双开关",
            category="Deciia/MiniMax H3",
            description=(
                "Official T8 v4 full-frame temporal PASS 2 wrapper. "
                "preserve_first_pass is the safe default; refined_exp explicitly "
                "publishes captured second-pass audio with absolute timeline mapping, "
                "overlap crossfade and quiet-tail protection. Any merge failure falls "
                "back to first-pass audio without dropping the video. Decode output, "
                "not denoised_output."
            ),
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.Boolean.Input("temporal_chunking", default=False,
                    tooltip="时间分块总开关。关=完整直出。开=guarded 时间分块(T8原生,带锚定重叠)。"),
                io.Boolean.Input("spatial_chunking", default=False,
                    tooltip="空间分块总开关。开=沿长边自动切条(自动选H/W)。可与时间分块独立组合。"),
                io.Int.Input("temporal_chunk_frames", default=34, min=17, max=3600, step=17,
                    extra_dict=_CTRL_TEMPORAL),
                io.Int.Input("temporal_overlap_frames", default=17, min=0, max=1700, step=17,
                    extra_dict=_CTRL_TEMPORAL),
                io.Float.Input("anchor_strength", default=0.999, min=0.0, max=1.0, step=0.001,
                    extra_dict=_CTRL_TEMPORAL),
                io.Int.Input("spatial_n_tiles", default=2, min=1, max=8,
                    tooltip="沿长边的条数(GH/班长语义)。1=关。",
                    extra_dict=_CTRL_SPATIAL),
                io.Int.Input("spatial_overlap_px", default=128, min=0, max=2048, step=64,
                    tooltip="条间重叠像素(内部÷16→latent格), 同GH tile_overlap。",
                    extra_dict=_CTRL_SPATIAL),
                io.Int.Input("spatial_feather", default=8, min=0, max=64, step=2,
                    tooltip="tile边界高斯羽化宽(latent格)。",
                    extra_dict=_CTRL_SPATIAL),
                io.Boolean.Input("spatial_global_pos", default=False,
                    tooltip="opt-in: 注入班长全局RoPE坐标(每条tile知道画布绝对位置,防分身/接缝)。关=GH兼容。",
                    extra_dict=_CTRL_SPATIAL),
                io.Combo.Input("audio_output", options=list(_AUDIO_OUTPUTS), default="preserve_first_pass"),
                io.Float.Input(
                    "chunk_redraw",
                    default=1.0,
                    min=0.05,
                    max=1.0,
                    step=0.05,
                    tooltip="Refine-sigma rescale. 1.0 = official upstream schedule. Lower values (0.4-0.6) keep more of PASS1 per chunk and reduce per-chunk drift on long chunked runs.",
                ),
            ],
            outputs=[
                io.Latent.Output("output"),
                io.Latent.Output("denoised_output", tooltip="Placeholder equal to output; decode output."),
            ],
        )

    @classmethod
    def execute(
        cls, noise, guider, sampler, sigmas, latent_image,
        temporal_chunking=False, spatial_chunking=False,
        temporal_chunk_frames=34,
        temporal_overlap_frames=17, anchor_strength=0.999,
        spatial_n_tiles=2, spatial_overlap_px=128, spatial_feather=8,
        spatial_global_pos=False,
        audio_output="preserve_first_pass", chunk_redraw=1.0,
    ):
        video, _audio = _nested_av_parts(latent_image)
        positive, negative, cfg, model = _raw_conditioning_from_guider(guider)
        target_width = int(video.shape[-1]) * _VAE_DOWNSAMPLE
        target_height = int(video.shape[-2]) * _VAE_DOWNSAMPLE

        # ── 简化路由(2026-09-30 减法重构) ──
        # step_sync_exp 多时间块路线已移除(实测不能防块间漂移且 bug 密集)。
        # 现存三模式:
        #   全关        → 直出 full_clip_safe(T8 原生)
        #   仅时间      → guarded_overlap_exp(T8 原生)
        #   空间开(优先)→ 自有 step_sync 执行器: 单时间块(整条时间轴)+空间tile
        temporal_on = bool(temporal_chunking)
        spatial_on = bool(spatial_chunking) and int(spatial_n_tiles) >= 2
        if spatial_on and temporal_on:
            log.info(
                "[DeciiaChunkedPass2V2] 时间+空间双开: 空间优先, 时间分块参数本次忽略"
                "(时间分块实测不防漂移; 空间单时间块保镜头连贯)"
            )

        effective_strategy = (
            "step_sync_exp" if spatial_on
            else ("guarded_overlap_exp" if temporal_on else "full_clip_safe")
        )

        # T8 原版 plan 构建器只认 full_clip_safe/guarded_overlap_exp; 空间模式的
        # step_sync_exp 是自有策略 — 以 full_clip_safe 合法构造, 再覆写
        # temporal_strategy 供自有执行器读取(不经过 T8 校验)。
        _plan_strategy = "full_clip_safe" if effective_strategy == "step_sync_exp" else effective_strategy
        plan, _ = build_chunked_two_pass_masked_low_sigma_plan(
            model_name=_DEFAULT_UPSCALER,
            target_width=target_width, target_height=target_height,
            temporal_chunk_frames=int(temporal_chunk_frames),
            temporal_overlap_frames=int(temporal_overlap_frames),
            anchor_strength=float(anchor_strength),
            tile_width=target_width, tile_height=target_height,
            spatial_overlap=0, spatial_fade=0, minimum_tile_size=256,
            overlap_blend="smoothstep", precision="fp16", release_policy="offload_after",
            spatial_strategy="full_frame_safe", temporal_strategy=_plan_strategy,
            second_pass_audio_policy="joint_av_preserve_input",
            video_mask_policy="inherit_if_present_else_generate_all",
        )
        # plan 键语义: 空间模式保持 full_clip_safe → 执行器单时间块(整条时间轴)+空间tile;
        # 仅时间模式直接用 guarded(T8 原生读)。
        plan["temporal_strategy"] = _plan_strategy
        chunk_redraw = float(chunk_redraw)
        if not 0.05 <= chunk_redraw <= 1.0:
            raise ValueError(
                f"chunk_redraw must be within [0.05, 1.0], got {chunk_redraw!r}"
            )
        if chunk_redraw != 1.0:
            sigmas = _rescale_refine_sigmas(sigmas, chunk_redraw)

        # 空间参数: 仅空间执行器消费; 直出/guarded 走 T8(空间由 plan 的 full_frame_safe 承担)
        _spatial_kwargs = dict(
            spatial_tile_axis=0,  # 0 = auto(切长边), 由 step_sync 执行器解析
            spatial_n_tiles=int(spatial_n_tiles),
            spatial_overlap_px=int(spatial_overlap_px),
            spatial_feather=int(spatial_feather),
            spatial_global_pos=bool(spatial_global_pos),
        )

        if effective_strategy == "step_sync_exp":
            if audio_output == "refined_exp":
                output, _report = _run_refined_audio(
                    model, positive, latent_image, noise, sampler, sigmas, plan,
                    negative, cfg, step_sync=True,
                    **_spatial_kwargs,
                )
            else:
                output, _report = execute_step_sync_two_pass_upscale(
                    model, positive, latent_image, noise, sampler, sigmas, plan,
                    negative=negative, cfg=cfg,
                    **_spatial_kwargs,
                )
        elif audio_output == "refined_exp":
            output, _report = _run_refined_audio(
                model, positive, latent_image, noise, sampler, sigmas, plan,
                negative, cfg,
            )
        elif audio_output == "preserve_first_pass":
            output, _report = _T8.execute_chunked_two_pass_upscale(
                model, positive, latent_image, noise, sampler, sigmas, plan,
                negative=negative, cfg=cfg,
            )
        else:
            raise ValueError(f"unknown audio_output: {audio_output!r}")
        return io.NodeOutput(output, output)

NODE_CLASS_MAPPINGS = {"DeciiaChunkedPass2V2": DeciiaChunkedPass2V2}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DeciiaChunkedPass2V2": "Deciia 分块PASS2 V2（T8 v4·时间/空间双开关）",
}
