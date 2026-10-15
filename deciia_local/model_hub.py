# -*- coding: utf-8 -*-
"""Deciia 模型加载枢纽 v2 · 固定出口 + 加载器注册表引擎（2026-10-03，P2a-beta2）。

设计（两层分离）：

一、槽位层（数据，固定 6 槽，出口不随组变）：
  出口0  当前组    STRING  （= 组名，喂门控/广播）
  出口1  UNet      MODEL   （diffusion_models，图像视频通用）
  出口2  文本编码  CLIP    （text_encoders；type=CLIPLoader 分类参数，不占出口）
  出口3  VAE·视频  VAE     （vae；图像模型填这里）
  出口4  VAE·音频  VAE     （vae；视频模型音频解码件；图像预设留空=输出None）
  出口5  模型补丁  ANY     （model_patches，ControlNet/Fun 补丁等）
  出口6  机动      ANY     （子类别可选：CLIPVision / 放大模型 / 不用）

二、引擎层（代码，全类别通用）：
  加载器注册表 LOADERS：槽位 → (候选类名列表, 方法名, 参数构造器)。
  统一从 nodes.NODE_CLASS_MAPPINGS 按类名解析 —— 与类所在模块解耦，
  loader 搬家（如 nodes.CLIP→nodes.CLIPLoader 的历史迁移）不影响本节点；
  类名找不到时按候选列表回退，全部失败报清晰错误。

预设结构 v2：{presets:[{name, files:{UNet:{file,device}, 文本编码:{file,type,device},
VAE·视频:{file}, VAE·音频:{file}, 模型补丁:{file}, 机动:{cat,file}}}], current}
旧 v1 结构（slots 列表）自动迁移：按类别对号入座，第2个VAE→VAE·音频。

固定出口的意义：连线一次接好永久有效，切模型组不动出口；
「模型选择」广播（AE）覆盖面板 current —— 运行时换组，画布不动。
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("DeciiaModelHub")

# ---------------- 槽位定义（数据） ----------------
SLOT_ORDER = ["UNet", "文本编码", "VAE·视频", "VAE·音频", "模型补丁", "机动"]

# 加载器注册表：key → {"classes": 按优先级候选类名, "method": 方法名,
#                      "args"/"kwargs": 参数构造器, "desc": 报错用}
# 全部经 NODE_CLASS_MAPPINGS 解析，不 import 具体模块。
LOADERS = {
    "UNet": {
        "classes": ["UNETLoader"],
        "method": "load_unet",
        "args": lambda ent: [ent["file"], ent.get("device") or "default"],
        "desc": "UNETLoader.load_unet(unet_name, weight_dtype)",
    },
    "文本编码": {
        "classes": ["CLIPLoader", "CLIP"],  # CLIP 为旧版回退
        "method": "load_clip",
        "kwargs": lambda ent: {
            "clip_name": ent["file"],
            "type": ent.get("type") or "chinese_clip",
            "device": ent.get("device") or "default",
        },
        "desc": "CLIPLoader.load_clip(clip_name, type, device)",
    },
    "VAE": {
        "classes": ["VAELoader"],
        "method": "load_vae",
        "args": lambda ent: [ent["file"]],
        "desc": "VAELoader.load_vae(vae_name)",
    },
    "模型补丁": {
        "classes": ["ModelPatchLoader"],
        "method": "load_model_patch",
        "args": lambda ent: [ent["file"]],
        "desc": "ModelPatchLoader.load_model_patch(name)",
    },
    "CLIPVision": {
        "classes": ["CLIPVisionLoader"],
        "method": "load_clip_vision",
        "args": lambda ent: [ent["file"]],
        "desc": "CLIPVisionLoader.load_clip_vision(clip_name)",
    },
    "放大模型": {
        "classes": ["UpscaleModelLoader"],
        "method": "load_model",
        "args": lambda ent: [ent["file"]],
        "desc": "UpscaleModelLoader.load_model(model_name)",
    },
}

# 槽位 → 加载器key（机动槽按 cat 二次映射）
SLOT_LOADER = {
    "UNet": "UNet",
    "文本编码": "文本编码",
    "VAE·视频": "VAE",
    "VAE·音频": "VAE",
    "模型补丁": "模型补丁",
}
FREE_CATS = ["不用", "CLIPVision", "放大模型"]

DEFAULT_PRESET_TABLE = {
    "presets": [
        {
            "name": "qwen2.1",
            "files": {
                "UNet": {"file": "qwen_image_2.1_int8_convrot.safetensors", "device": "default"},
                "文本编码": {"file": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"},
                "VAE·视频": {"file": "qwen_image_2.1_vae_bf16.safetensors"},
                "VAE·音频": {"file": ""},
                "模型补丁": {"file": ""},
                "机动": {"cat": "不用", "file": ""},
            },
        },
        {
            "name": "krea2",
            "files": {
                "UNet": {"file": "krea2\\pornmasterKrea2_v2TurboInt8.safetensors", "device": "default"},
                "文本编码": {"file": "qwen3vl_4b_bf16.safetensors", "type": "krea2", "device": "default"},
                "VAE·视频": {"file": "qwen_image_vae.safetensors"},
                "VAE·音频": {"file": ""},
                "模型补丁": {"file": ""},
                "机动": {"cat": "不用", "file": ""},
            },
        },
    ],
    "current": "qwen2.1",
}


class _Any(str):
    def __ne__(self, other): return False
    def __eq__(self, other): return True
    def __str__(self): return "*"


ANY = _Any("*")


def _parse_table(raw) -> dict:
    if isinstance(raw, dict):
        obj = raw
    else:
        try:
            obj = json.loads(raw) if raw else {}
        except Exception:
            return {}
        if not isinstance(obj, dict):
            return {}
    return _migrate(obj)


def _migrate(table: dict) -> dict:
    """v1（slots 列表）→ v2（files 固定槽）。就地改写并返回。"""
    presets = table.get("presets")
    if not isinstance(presets, list):
        return table
    changed = False
    for p in presets:
        if not isinstance(p, dict) or "files" in p or "slots" not in p:
            continue
        files: dict = {}
        vae_i = 0
        for s in p.get("slots") or []:
            if not isinstance(s, dict):
                continue
            cat = str(s.get("cat") or "")
            file = str(s.get("file") or "")
            if cat == "UNet":
                files["UNet"] = {"file": file, "device": str(s.get("device") or "default")}
            elif cat == "文本编码":
                files["文本编码"] = {"file": file, "type": str(s.get("type") or ""),
                                     "device": str(s.get("device") or "default")}
            elif cat == "VAE":
                key = "VAE·视频" if vae_i == 0 else "VAE·音频"
                vae_i += 1
                files[key] = {"file": file}
            elif cat == "模型补丁":
                files["模型补丁"] = {"file": file}
        for k in SLOT_ORDER:
            files.setdefault(k, {"file": ""})
        if not isinstance(files.get("机动"), dict) or "cat" not in files["机动"]:
            files["机动"] = {"cat": "不用", "file": ""}
        p["files"] = files
        del p["slots"]
        changed = True
    if changed:
        log.info("[模型枢纽] 旧预设结构已自动迁移为固定 6 槽格式")
    return table


def _resolve_loader(loader_key: str):
    """按注册表候选类名从 NODE_CLASS_MAPPINGS 解析 loader 类。"""
    import nodes as comfy_nodes
    spec = LOADERS[loader_key]
    for cls_name in spec["classes"]:
        cls = getattr(comfy_nodes, "NODE_CLASS_MAPPINGS", {}).get(cls_name)
        if cls is not None:
            return cls, spec
    raise ValueError(
        f"[模型枢纽] 找不到加载器类 {spec['classes']}（需要 {spec['desc']}）。"
        f"请确认对应节点包已安装且 ComfyUI 版本支持。")


def _load_slot(loader_key: str, ent: dict):
    """执行一个槽位的加载。返回 (值, 标签) 或 (None, None)。"""
    file = str((ent or {}).get("file") or "").strip()
    if not file or file in ("none", "None"):
        return None, None
    cls, spec = _resolve_loader(loader_key)
    inst = cls()
    method = getattr(inst, spec["method"])
    if "kwargs" in spec:
        result = method(**spec["kwargs"](ent))
    else:
        result = method(*spec["args"](ent))
    return result[0], f"{loader_key}:{file}"


class DeciiaModelHub:
    """模型加载枢纽 · 固定出口（图像/视频模型通用）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "预设表": ("STRING", {"default": json.dumps(DEFAULT_PRESET_TABLE, ensure_ascii=False),
                                       "multiline": True,
                                       "tooltip": "预设组表（JSON，前端面板维护，勿手改）。v2: presets:[{name, files:{槽:{file,type,device,cat}}}]"}),
            },
            "optional": {
                # forceInput：纯输入口（非 widget 化），Anything Everywhere 默认可投递
                "模型选择": ("STRING", {"forceInput": True, "tooltip": "接收 STRING 广播（如 820 模型选择器 qwen2.1/krea2）；有值时覆盖面板当前组。"}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("STRING", "MODEL", "CLIP", "VAE", "VAE", ANY, ANY)
    RETURN_NAMES = ("当前组", "UNet", "文本编码", "VAE·视频", "VAE·音频", "模型补丁", "机动")
    FUNCTION = "load_all"
    CATEGORY = "Deciia/模型"
    DESCRIPTION = "Deciia 模型加载枢纽 · 固定6出口（UNet/文本编码/VAE视频/VAE音频/补丁/机动），图像视频通用，切组不换口"

    OUTPUT_NODE = False

    @classmethod
    def IS_CHANGED(cls, 预设表, **kwargs):
        return ""  # 加载结果由 ComfyUI 原生权重缓存管理

    def load_all(self, 预设表, **kwargs):
        table = _parse_table(预设表)
        presets = table.get("presets") or []
        if not presets:
            raise ValueError("[模型枢纽] 预设表为空。")
        # 组名：广播口「模型选择」优先（AE 投递），再其次面板 current
        gname = str(kwargs.get("模型选择") or "").strip()
        if not gname:
            gname = str(table.get("current") or "").strip()
        if not gname:
            gname = str((presets[0] or {}).get("name") or "").strip()
        if not gname:
            raise ValueError("[模型枢纽] 当前组名为空。请在前端面板选一次组。")
        group = next((p for p in presets if str(p.get("name")) == gname), None)
        if group is None:
            raise ValueError(f"[模型枢纽] 预设表里没有组「{gname}」。")

        files = group.get("files") or {}
        outs = [gname]
        labels = []

        for slot in SLOT_ORDER:
            ent = files.get(slot) or {}
            if not isinstance(ent, dict):
                ent = {}
            if slot == "机动":
                cat = str(ent.get("cat") or "不用")
                if cat in ("不用", ""):
                    outs.append(None)
                    continue
                val, lab = _load_slot(cat, ent)
                outs.append(val)
                if lab:
                    labels.append(lab)
                continue
            val, lab = _load_slot(SLOT_LOADER[slot], ent)
            outs.append(val)
            if lab:
                labels.append(lab)

        if all(o is None for o in outs[1:]):
            raise ValueError(f"[模型枢纽] 组「{gname}」所有槽位都为空，无东西可加载。")

        log.info("[模型枢纽] 组=%s 加载: %s", gname, "; ".join(labels) or "（仅组名，全空槽）")
        return tuple(outs)


NODE_CLASS_MAPPINGS = {"DeciiaModelHub": DeciiaModelHub}
NODE_DISPLAY_NAME_MAPPINGS = {"DeciiaModelHub": "Deciia 模型加载枢纽 · 预设组"}
