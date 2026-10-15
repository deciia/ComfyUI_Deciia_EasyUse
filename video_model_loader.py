# -*- coding: utf-8 -*-
"""Deiia 视频模型加载器 · 四合一预设（视频生成专用，MiniMax-H3 优先）。

固定四项加载：UNet / CLIP / 视频 VAE / 音频 VAE；固定四个输出槽。
预设（多套文件组合）由前端管理：preset_name 下拉切换，⚙ 菜单做增删改。
CLIP 加载类型默认 minimax（H3 文本编码器）。
"""

import json

import comfy.sd
import comfy.utils
import folder_paths
from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def _opts(folder):
    try:
        return folder_paths.get_filename_list(folder)
    except Exception:
        return []


_CLIP_TYPES = ["minimax", "stable_diffusion"]
try:
    from comfy.sd import CLIPType as _CLIPType
    _CLIP_TYPES = [(m.value if isinstance(m.value, str) else m.name).lower() for m in _CLIPType]
except Exception:
    pass

_DEFAULT_PRESETS = {
    "current": "H3 主力",
    "presets": [{
        "name": "H3 主力",
        "unet_name": "DasiwaMinimaxH3_dasiwaHybridV3_int8_r.safetensors",
        "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "audio_vae_name": "minimax_h3_audio_vae_fp32.safetensors",
    }],
}


class DeciiaVideoModelLoader(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaVideoModelLoader",
            display_name="Deiia 视频模型加载器 · 四合一预设",
            category="Deciia/local",
            description=(
                "视频生成模型四合一加载器：UNet / CLIP / 视频 VAE / 音频 VAE 一次加载，"
                "支持多预设切换（preset_name 下拉切换；⚙ 菜单管理预设）。"
                "四个输出可直接对接 easy modelLoaderPack 或各自的采样输入。"
            ),
            inputs=[
                io.Combo.Input("unet_name", options=_opts("diffusion_models"),
                               tooltip="UNet / 扩散模型权重（diffusion_models 目录）。"),
                io.Combo.Input("clip_name", options=_opts("text_encoders"),
                               tooltip="文本编码器权重（text_encoders 目录）。"),
                io.Combo.Input("video_vae_name", options=_opts("vae"),
                               default="minimax_h3_video_vae_fp16.safetensors",
                               tooltip="视频 VAE 权重（vae 目录）。"),
                io.Combo.Input("audio_vae_name", options=_opts("vae"),
                               default="minimax_h3_audio_vae_fp32.safetensors",
                               tooltip="音频 VAE 权重（vae 目录）。"),
                io.String.Input("presets_json", default=json.dumps(_DEFAULT_PRESETS, ensure_ascii=False),
                                multiline=True, advanced=True,
                                tooltip="预设数据（前端面板自动维护，一般不用手改）。"),
                io.Combo.Input("clip_type", options=_CLIP_TYPES, default="minimax", advanced=True,
                               tooltip="CLIP 加载类型。MiniMax-H3 用 minimax。"),
            ],
            outputs=[
                io.Model.Output(display_name="模型"),
                io.Clip.Output(display_name="CLIP"),
                io.Vae.Output(display_name="视频VAE"),
                io.Vae.Output(display_name="音频VAE"),
            ],
        )

    @classmethod
    def execute(cls, unet_name, clip_name, video_vae_name, audio_vae_name,
                clip_type="minimax", presets_json="") -> io.NodeOutput:
        model = comfy.sd.load_diffusion_model(folder_paths.get_full_path_or_raise("diffusion_models", unet_name))
        if model is None:
            raise RuntimeError(f"UNet 加载失败: {unet_name}")

        clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
        clip_type_enum = clip_type
        try:
            clip_type_enum = comfy.sd.CLIPType(clip_type)
        except Exception:
            try:
                clip_type_enum = comfy.sd.CLIPType[clip_type.upper()]
            except Exception:
                clip_type_enum = clip_type  # 交给下游按原样处理
        clip = comfy.sd.load_clip(
            ckpt_paths=[clip_path],
            embedding_directory=folder_paths.get_full_path("embeddings", None),
            type=clip_type_enum,
        )
        if clip is None:
            raise RuntimeError(f"CLIP 加载失败: {clip_name}")

        video_vae = comfy.sd.VAE(sd=comfy.utils.load_torch_file(
            folder_paths.get_full_path_or_raise("vae", video_vae_name)))
        audio_vae = comfy.sd.VAE(sd=comfy.utils.load_torch_file(
            folder_paths.get_full_path_or_raise("vae", audio_vae_name)))

        return io.NodeOutput(model, clip, video_vae, audio_vae)


NODE_CLASS_MAPPINGS["DeciiaVideoModelLoader"] = DeciiaVideoModelLoader
NODE_DISPLAY_NAME_MAPPINGS["DeciiaVideoModelLoader"] = "Deiia 视频模型加载器 · 四合一预设"
