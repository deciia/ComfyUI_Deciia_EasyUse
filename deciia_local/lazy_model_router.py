"""Lazy 模型路由节点 rev4（2026-10-01，P2a-beta2 专用多模型采样台）。

rev4 变更（用户需求）：
  1. 采样参数按模型独立：Qwen步数/Krea步数 等各一套（krea2=8步、qwen=40步
     来回切换不丢设置）；前端按当前模型显隐对应 widget。
  2. 新增入口：工作台包（Lazy 合并台 PACK）+ LoRA配置（KREA_LORA_STACK）。
     pack 携带画布时覆盖宽高（与 LazyMergeGenerate 同语义）。
  3. 种子通用化：种子模式 fixed / increment / decrement / random + 种子步进。
     - fixed: 用「种子」原值
     - increment/decrement: 种子 += / -= 步进（每次执行变化；配合 ComfyUI
       的节点缓存, 参数不变则重跑不会重新计算——IS_CHANGED 用 nan 保证重跑）
     - random: 每次执行取 0..2^48 随机
  4. 保留 rev3：模型下拉 + 动态输入口（前端真删真建）+ 模型选择输出。
  5. rev5：本地下拉改名「模型」（原生 COMBO，撤掉自绘铺垫）；新增 optional 输入口
     「模型选择」(STRING, forceInput) 收广播/直连，有值覆盖下拉。

采样核心：comfy.sample.sample（与 Lazy 节点同原语）；LoRA 应用：
KREA_LORA_STACK 由 lazy_krea_lora_stack 产出的 (model, clip) 对直接覆盖
采样用 MODEL/CLIP（Krea 路线），Qwen 路线 LoRA 经 ModelPatch 由上游处理。
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("LazyModelRouter")

MODEL_REGISTRY = [
    {
        "id": "qwen2.1", "tag": "qwen", "label": "Qwen Image 2.1",
        "slots": [("模型", "MODEL"), ("文本编码", "CLIP"), ("VAE", "VAE")],
    },
    {
        "id": "krea2", "tag": "krea", "label": "Krea 2",
        "slots": [("模型", "MODEL"), ("文本编码", "CLIP"), ("VAE", "VAE")],
    },
]
_MODEL_IDS = [m["id"] for m in MODEL_REGISTRY]
_MODEL_LABELS = [f'{m["label"]} ({m["id"]})' for m in MODEL_REGISTRY]
_LABEL2ID = {lbl: m["id"] for lbl, m in zip(_MODEL_LABELS, MODEL_REGISTRY)}

_SAMPLERS = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde"]
MANUAL_SIGMAS_NAME = "ManualSigmas"
# Qwen2.1 的 9 点手工 sigma 阶梯（与 LazyQwenGenerate 同源）。
# 前段密（细去噪）、后段跳（快速收敛）。步数不同时按线性插值重采样到 steps+1 档。
QWEN_MANUAL_SIGMAS = (
    1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0,
)
_SCHEDULERS = ["simple", "normal", "beta", "sgm_uniform", MANUAL_SIGMAS_NAME]

# 每模型独立的采样参数名（前端按模型显隐同款前缀）
_PER_MODEL_PARAMS = {
    "qwen2.1": ["Qwen步数", "QwenCFG", "Qwen采样器", "Qwen调度器", "Qwen去噪"],
    "krea2": ["Krea步数", "KreaCFG", "Krea采样器", "Krea调度器", "Krea去噪"],
}


def _manual_sigmas(sigmas):
    """归一成 1D float32 tensor。接受 tensor / 序列。"""
    import torch as _torch
    if _torch.is_tensor(sigmas):
        out = sigmas.detach().float().cpu().flatten()
    else:
        out = _torch.tensor([float(x) for x in sigmas], dtype=_torch.float32)
    if int(out.numel()) < 2:
        raise ValueError("ManualSigmas 至少需要 2 个数值。")
    return out


def _resample_sigmas(sigmas, steps: int):
    """按填写的步数重采样 sigma 曲线。步数+1 等于原档数时保持原值。"""
    import torch as _torch
    steps = max(1, int(steps))
    src = sigmas.detach().float().cpu().flatten()
    target = steps + 1
    if int(src.numel()) == target:
        return src
    out = _torch.nn.functional.interpolate(
        src.view(1, 1, -1), size=target, mode="linear", align_corners=True,
    ).view(-1).contiguous()
    out[0] = src[0]
    out[-1] = src[-1]
    return out


def _resolve_model(value: str) -> str:
    if value in _MODEL_IDS:
        return value
    if value in _LABEL2ID:
        return _LABEL2ID[value]
    low = str(value).lower()
    for m in MODEL_REGISTRY:
        if m["tag"] in low or m["id"] in low:
            return m["id"]
    raise ValueError(f"未知模型: {value!r}; 可选: {_MODEL_IDS}")


class _AnyPack(str):
    def __ne__(self, value): return False
    def __eq__(self, value): return True
    def __str__(self): return "MERGE_PACK"


PACK = _AnyPack("MERGE_PACK")


class LazyModelRouter:
    """多模型采样台 · 每模型独立采样参数 + 工作台包/LoRA + 通用种子。"""

    @classmethod
    def INPUT_TYPES(cls):
        samplers = _SAMPLERS
        schedulers = _SCHEDULERS
        return {
            "required": {
                # 本地下拉（原生 COMBO）。入口「模型选择」有值（广播/直连）时，以入口为准。
                "模型": (_MODEL_IDS, {"default": _MODEL_IDS[0], "tooltip": "本地下拉：qwen2.1 = Qwen Image 2.1，krea2 = Krea 2。切换时前端联动：动态输入口 + 对应模型采样参数显隐。若入口「模型选择」有值（广播/直连），以入口为准。"}),
                # ── 通用：种子（原生 control_after_generate：固定/递增/递减/随机） ──
                "种子": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                  "control_after_generate": True,
                                  "tooltip": "种子。右键「自动更新该值」或种子框旁控制：固定/递增/递减/随机。"}),
                # ── 通用：尺寸（宽高来自工作台包画布；无画布时用参考分辨率） ──
                "参考分辨率": ("INT", {"default": 2048, "min": 0, "max": 4096, "step": 64,
                                       "tooltip": "宽高上限（面积语义，同 Lazy 合并生成）。工作台包带画布时优先用画布宽高；无画布的文生图按此分辨率生成。0=1024 方图。"}),
                # ── Qwen 独立采样参数 ──
                "Qwen步数": ("INT", {"default": 40, "min": 1, "max": 100, "tooltip": "[Qwen] 采样步数（Qwen2.1 常用 25-40）。"}),
                "QwenCFG": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1, "tooltip": "[Qwen] CFG。"}),
                "Qwen采样器": (samplers, {"default": "euler", "tooltip": "[Qwen] 采样器。"}),
                "Qwen调度器": (schedulers, {"default": "simple", "tooltip": "[Qwen] 调度器。"}),
                "Qwen去噪": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "[Qwen] denoise。"}),
                # ── Krea 独立采样参数 ──
                "Krea步数": ("INT", {"default": 8, "min": 1, "max": 100, "tooltip": "[Krea] 采样步数（Krea2 常用 6-10）。"}),
                "KreaCFG": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1, "tooltip": "[Krea] CFG。"}),
                "Krea采样器": (samplers, {"default": "euler", "tooltip": "[Krea] 采样器。"}),
                "Krea调度器": (schedulers, {"default": "simple", "tooltip": "[Krea] 调度器。"}),
                "Krea去噪": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "[Krea] denoise（img2img 重绘调低）。"}),
                # ── Qwen 专属选项 ──
                "Qwen缓存设备": (["auto", "gpu", "cpu", "off"], {"default": "auto", "tooltip": "[Qwen] 缓存设备。"}),
                "Qwen缓存精度": (["default", "int8", "int4"], {"default": "default", "tooltip": "[Qwen] 缓存精度。"}),
                "Qwen透明底": ("BOOLEAN", {"default": False, "tooltip": "[Qwen] 透明背景。"}),
            },
            "optional": {
                # ── 模型接线（单套通用口，2026-10-03 用户定稿：模型无关） ──
                # 「模型」口一条实体线接枢纽/加载器，切模型线不动；
                # 文本编码/VAE/底模悬空，由 Anything Everywhere 广播按类型自动投递。
                "UNet": ("MODEL", {"tooltip": "当前模型 UNET（固定实体线，接枢纽 UNet 出口）。"}),
                "文本编码": ("CLIP", {"tooltip": "当前模型文本编码（悬空走广播）。"}),
                "VAE": ("VAE", {"tooltip": "当前模型 VAE（悬空走广播）。"}),
                "底模": ("MODEL", {"tooltip": "底模（四视图用，悬空走广播）。"}),
                # ── rev4 新增 ──
                "工作台包": (PACK, {"tooltip": "Lazy 合并台输出。携带画布/提示词/模式；画布覆盖宽高。"}),
                "LoRA配置": ("KREA_LORA_STACK", {"tooltip": "Krea 多LoRA 配置（Lazy 合并台 LoRA 栈输出）。Krea 路线时覆盖采样 MODEL/CLIP。"}),
                # ── 通用数据口 ──
                "正向条件": ("CONDITIONING", {"tooltip": "正向条件（各模型专属链经门控/任意切换收口后接此口）。"}),
                "负向条件": ("CONDITIONING", {"tooltip": "负向条件。"}),
                "latent": ("LATENT", {"tooltip": "latent（空画布或 ControlNet 后）。"}),
                # ── 外部模型选择入口（广播/直连；有值覆盖本地下拉）──
                # 必须 STRING：Anything Everywhere 只能投 node.inputs 上的端口，
                # 且服务器 validate_node_input 对「STRING 上游 → 列表型 COMBO」直接判 false。
                "模型选择": ("STRING", {"default": "", "forceInput": True,
                                      "tooltip": "外部模型选择（广播/直连）：有值则覆盖本地下拉「模型」。留空用下拉。"}),
                # ── 手工 sigmas 阶梯入口（2026-10-11 方案A）：接入后覆盖步数/调度器，denoise 由阶梯决定 ──
                "Sigmas": ("SIGMAS", {"tooltip": "手工 sigmas 阶梯。① 外部节点接入本口即生效（优先级最高）；② 不接本口、而把下方「Qwen调度器/ Krea调度器」选成 ManualSigmas，则用内置 9 点 Qwen 阶梯。两条路都走sample_custom，覆盖「步数/调度器/去噪」，采样器仍取下拉。"})
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("图像", "模型选择", "运行信息")
    FUNCTION = "route"
    CATEGORY = "Lazy"
    DESCRIPTION = "Lazy 模型路由 · 多模型采样台（每模型独立参数）"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return ""

    # ── Qwen2.1 VL 多图编码（2026-10-02，自 lazy_qwen_generate 移植）──
    # 包内有参考图时：图像进 Qwen3VL 视觉塔（压白后 RGB），原图 VAE latent 挂
    # conditioning.reference_latents（Qwen2.1 原生参考机制，替代 AnyAngle 之外的
    # 硬参考通路）。@图片N 自动转 <imageN>；漏写标签自动补前缀。无图时返回 None
    # 走原纯文本兜底。
    _AT_RE = re.compile(r"@(图片|image)\s*(\d+)", re.IGNORECASE)

    @staticmethod
    def _expand_at_tags(text):
        return LazyModelRouter._AT_RE.sub(lambda m: f"<image{int(m.group(2))}>", text or "")

    @staticmethod
    def _has_image_tag(prompt, n):
        p = (prompt or "").lower()
        return f"<image{n}>" in p or f"<image {n}>" in p

    @staticmethod
    def _ensure_image_tags(prompt, n_img):
        prompt = prompt or ""
        if n_img <= 0:
            return prompt
        missing = [i for i in range(1, n_img + 1) if not LazyModelRouter._has_image_tag(prompt, i)]
        if not missing:
            return prompt
        if n_img == 1:
            prefix = "根据 <image1> "
        else:
            prefix = "根据 " + " ".join(f"<image{i}>" for i in range(1, n_img + 1)) + " "
        if prompt.strip().startswith(prefix.strip()):
            return prompt
        return prefix + prompt

    @staticmethod
    def _encode_qwen21_vl(clip, vae, pos_txt, neg_txt, images, resolution=2048):
        """参考图 VL 编码。images: [tensor(H,W,C) 3或4通道]。返回 (pos, neg) 或 None。"""
        import math
        import torch
        import comfy.utils
        # node_helpers 是 ComfyUI 根目录下的模块（comfy/ 包里没有），
        # 旧写法 `from comfy import node_helpers` 在 0.37 必失败 → VL 参考编码静默退化成纯文本。
        try:
            import node_helpers
        except ImportError:
            from comfy import node_helpers  # 兼容旧版布局
        if not images:
            return None
        ref_latents = []
        images_vl = []
        for image in images:
            if image is None:
                continue
            t = image if image.ndim == 4 else image.unsqueeze(0)
            t = t[:1]
            samples = t.movedim(-1, 1)
            # 分辨率约束（面积语义，对齐 32；不放大）
            h0, w0 = int(samples.shape[2]), int(samples.shape[3])
            ratio = w0 / max(1, h0)
            if resolution > 0:
                width = round(math.sqrt(resolution * resolution * ratio) / 32) * 32
                height = round(math.sqrt(resolution * resolution / ratio) / 32) * 32
            else:
                width, height = round(w0 / 32) * 32, round(h0 / 32) * 32
            width, height = max(32, width), max(32, height)
            if (width, height) == (w0, h0):
                s = t
            else:
                s = comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)
            rgb = s[:, :, :, :3]
            if s.shape[-1] > 3:
                rgb = rgb * s[:, :, :, 3:] + (1.0 - s[:, :, :, 3:])
            images_vl.append(rgb)
            if vae is not None:
                # 视觉塔看压白后 RGB；VAE 保留原图通道（含 alpha）
                ref_latents.append(vae.encode(s))
        if not images_vl:
            return None
        keep_vision = len(ref_latents) == 0
        pos_txt = LazyModelRouter._ensure_image_tags(LazyModelRouter._expand_at_tags(pos_txt), len(images_vl))
        neg_txt = LazyModelRouter._expand_at_tags(neg_txt)
        try:
            positive = clip.encode_from_tokens_scheduled(
                clip.tokenize(pos_txt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
            negative = clip.encode_from_tokens_scheduled(
                clip.tokenize(neg_txt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        except TypeError:
            positive = clip.encode_from_tokens_scheduled(clip.tokenize(pos_txt, images=images_vl))
            negative = clip.encode_from_tokens_scheduled(clip.tokenize(neg_txt, images=images_vl))
        if ref_latents:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)
        return positive, negative

    def route(self, **kwargs):
        g = kwargs.get
        # 入口优先：模型选择（广播/直连）> 本地下拉「模型」> 注册表首个模型
        model_id = _resolve_model(str(g("模型选择") or g("模型") or _MODEL_IDS[0]))

        # ── 种子（control_after_generate 由前端在每次排队后改写 widget 值） ──
        seed = int(g("种子") or 0)
        mode = str(g("control_after_generate") or "fixed")

        # ── 尺寸：宽高来自合并台画布（pack），节点只设参考分辨率 ──
        pack = g("工作台包")
        resolution = int(g("参考分辨率") or 0)
        width = height = max(1024, resolution) if resolution > 0 else 1024
        if isinstance(pack, dict):
            cw = int(pack.get("canvas_w") or 0)
            chh = int(pack.get("canvas_h") or 0)
            if cw > 0 and chh > 0:
                width, height = cw, chh
            else:
                # pack 无画布：若 latent 已有尺寸（编辑/图生图链）跟随 latent；
                # 其次有参考图时跟随第一张参考图（编辑/参考语义，2026-10-02）
                lt = g("latent")
                try:
                    shp = lt["samples"].shape if lt is not None else None
                    if shp is not None and shp[-1] > 0:
                        width, height = int(shp[-1] * 8), int(shp[-2] * 8)
                except Exception:
                    pass
                if width == height and isinstance(pack.get("images"), (list, tuple)) and pack["images"]:
                    try:
                        t0 = pack["images"][0]
                        h0 = int(t0.shape[1] if t0.ndim == 4 else t0.shape[0])
                        w0 = int(t0.shape[2] if t0.ndim == 4 else t0.shape[1])
                        if h0 > 0 and w0 > 0:
                            width = max(32, round(w0 / 32) * 32)
                            height = max(32, round(h0 / 32) * 32)
                    except Exception:
                        pass

        # ── 按模型取独立参数 ──
        if model_id == "qwen2.1":
            model = g("UNet"); clip = g("文本编码"); vae = g("VAE")
            if model is None or clip is None or vae is None:
                _miss = [k for k, v in (("UNet", model), ("文本编码", clip),
                                        ("VAE", vae)) if v is None]
                log.error("[Lazy模型路由] qwen2.1 缺输入 %s｜收到的键=%s｜类型 model=%s clip=%s vae=%s",
                          _miss, sorted(kwargs.keys()),
                          type(model).__name__, type(clip).__name__, type(vae).__name__)
                raise ValueError(f"当前模型 qwen2.1：缺 {', '.join(_miss)}"
                                 f"（收到 model={type(model).__name__} clip={type(clip).__name__}"
                                 f" vae={type(vae).__name__}）。")
            steps = int(g("Qwen步数") or 40)
            cfg = float(g("QwenCFG") or 1.0)
            sampler = str(g("Qwen采样器") or "euler")
            scheduler = str(g("Qwen调度器") or "simple")
            denoise = float(g("Qwen去噪") or 1.0)
            info_tail = f"缓存={g('Qwen缓存设备')}/{g('Qwen缓存精度')}"
        elif model_id == "krea2":
            model = g("UNet"); clip = g("文本编码"); vae = g("VAE")
            if model is None or clip is None or vae is None:
                _miss = [k for k, v in (("UNet", model), ("文本编码", clip),
                                        ("VAE", vae)) if v is None]
                log.error("[Lazy模型路由] krea2 缺输入 %s｜收到的键=%s｜类型 model=%s clip=%s vae=%s",
                          _miss, sorted(kwargs.keys()),
                          type(model).__name__, type(clip).__name__, type(vae).__name__)
                raise ValueError(f"当前模型 krea2：缺 {', '.join(_miss)}"
                                 f"（收到 model={type(model).__name__} clip={type(clip).__name__}"
                                 f" vae={type(vae).__name__}）。")
            # LoRA 栈（Krea 路线）：覆盖采样用 MODEL/CLIP
            lora_stack = g("LoRA配置")
            if lora_stack is not None:
                # 735 VramSafeLoraStack 输出1 = KREA_LORA_STACK 配置包(dict)：
                # LoRA 已由 735 应用进其输出0（= UNet 口进来的 MODEL），
                # 这里【不得】用它覆盖 model/clip（dict 解包会把 model 换成
                # key 字符串 → 'dict'/'str' has no 'load_device' 根因）。
                # 仅当真是旧契约 (MODEL, CLIP) 二元组时才覆盖。
                try:
                    if isinstance(lora_stack, dict):
                        log.info("[Lazy模型路由] Krea LoRA配置包已收到(%s行)，"
                                 "LoRA已由上游挂载，直接用UNet口模型",
                                 lora_stack.get("lora_count", "?"))
                    else:
                        lm, lc = lora_stack
                        if lm is not None and hasattr(lm, "model"): model = lm
                        if lc is not None and hasattr(lc, "encode"): clip = lc
                        log.info("[Lazy模型路由] Krea LoRA栈已应用(旧契约二元组)")
                except Exception as e:
                    log.warning("[Lazy模型路由] LoRA配置解析失败(忽略): %s", e)
            steps = int(g("Krea步数") or 8)
            cfg = float(g("KreaCFG") or 1.0)
            sampler = str(g("Krea采样器") or "euler")
            scheduler = str(g("Krea调度器") or "simple")
            denoise = float(g("Krea去噪") or 1.0)
            info_tail = "krea2"
        else:
            raise ValueError(f"模型 {model_id} 尚未接入采样原语。")

        positive = g("正向条件")
        negative = g("负向条件")
        latent = g("latent")
        pack = g("工作台包")
        # 工作台包兜底编码（2026-10-01）：条件口未接时，用包内文本 + 当前模型
        # 的 CLIP 现场编码。正向无条件来源才报错；负向始终允许兜底（空文本→None）。
        if positive is None or negative is None:
            def _pack_texts(p):
                if not isinstance(p, dict):
                    return "", ""
                pr = p.get("prompts") or []
                if isinstance(pr, str): pr = [pr]
                pos = str(pr[0]) if pr else ""
                neg = str(p.get("negative") or "")
                return pos, neg
            pos_txt, neg_txt = _pack_texts(pack)
            # VL 多图编码（2026-10-02）：qwen2.1 且包内有参考图时，图像进
            # Qwen3VL 视觉塔 + reference_latents 挂 conditioning（官方编辑/
            # 参考机制）。文本经 @图片N→<imageN> 转写并自动补标签。
            pack_images = pack.get("images") if isinstance(pack, dict) else None
            if (positive is None or negative is None) and model_id == "qwen2.1" and pack_images:
                try:
                    vl = self._encode_qwen21_vl(clip, vae, pos_txt, neg_txt, pack_images,
                                                resolution=resolution)
                except Exception as e:
                    vl = None
                    log.warning("[Lazy模型路由] VL参考编码失败，回退纯文本: %s", e)
                if vl is not None:
                    if positive is None:
                        positive = vl[0]
                        log.info("[Lazy模型路由] 正向条件未接：已用 VL 多图编码（%d 张参考图）",
                                 len(pack_images))
                    if negative is None:
                        negative = vl[1] or negative
                        if negative is not None:
                            log.info("[Lazy模型路由] 负向条件未接：已用 VL 多图编码")
            if positive is None:
                if not pos_txt:
                    raise ValueError(
                        "正向条件未接，且工作台包无正向文本：请连接 正向条件，"
                        "或在合并台输入正向提示词。")
                positive = clip.encode(pos_txt)
                log.info("[Lazy模型路由] 正向条件未接：已用工作台包文本兜底编码")
            if negative is None and neg_txt:
                negative = clip.encode(neg_txt)
                log.info("[Lazy模型路由] 负向条件未接：已用工作台包负面文本兜底编码")

        # ── Krea2 编辑链（2026-10-03 移植自 LazyKreaGenerate）：pack 带参考图时 ──
        # 文生图路径零改动；仅 krea2 + images 非空时切换为编辑采样：
        #   参考图 → VAE 编码 → Krea2EditModelPatch 注入模型
        #   提示词 → Krea2EditGroundedEncode 带图接地编码（30720 维）
        #   空 latent 用 16 通道 SD3 形态（qwen VAE 带 T 维由 fix_empty_latent_channels 处理）
        pack_images = pack.get("images") if isinstance(pack, dict) else None
        if model_id == "krea2" and pack_images:
            try:
                imgs = [im for im in pack_images if im is not None]
                log.info("[Lazy模型路由] Krea2 编辑链启动：%d 张参考图", len(imgs))
                img_a = _dc_scale_image(imgs[0], 1.0)
                img_b = _dc_scale_image(imgs[1], 1.0) if len(imgs) >= 2 else None
                src_lat = _dc_vae_encode(vae, img_a[:1])
                src_lat_b = _dc_vae_encode(vae, img_b[:1]) if img_b is not None else None
                model = _dc_edit_patch(
                    model, src_lat, src_lat_b, vae=vae,
                    source_image=img_a[:1],
                    source_image_b=(img_b[:1] if img_b is not None else None),
                )
                pos_txt_edit = pos_txt or ""
                positive = _dc_grounded_encode(clip, pos_txt_edit, image=img_a[:1],
                                               image_b=(img_b[:1] if img_b is not None else None),
                                               grounding_px=768)
                negative = _dc_grounded_encode(clip, "", image=img_a[:1],
                                               image_b=(img_b[:1] if img_b is not None else None),
                                               grounding_px=768)
                log.info("[Lazy模型路由] Krea2 编辑链：模型注入+接地编码完成")
                # 编辑模式尺寸跟随参考图（无画布时）
                if not (isinstance(pack, dict) and pack.get("canvas_w")):
                    _h, _w = int(img_a.shape[1]), int(img_a.shape[2])
                    width = max(64, (_w // 16) * 16)
                    height = max(64, (_h // 16) * 16)
                    log.info("[Lazy模型路由] 编辑模式画布未指定 → 用参考图尺寸 %dx%d", width, height)
                # 编辑用 16 通道空 latent（4 通道会 mat1/mat2 爆）
                latent = _dc_empty_krea_latent(width, height, 1)
            except Exception as e:
                raise ValueError(f"Krea2 编辑链失败：{e}\n"
                                 f"检查：参考图是否有效；krea2edit 包是否安装；"
                                 f"CLIP type 是否为 krea2（qwen3vl_*）。")

        if latent is None:
            # 0.37 没有 comfy.sample.empty_latent_image（实测 hasattr=False）。
            # 直接用核心节点造空 latent，等价于工作流里拖一个「空 Latent」。
            try:
                import nodes as _nodes
                _empty = _nodes.EmptyLatentImage()
                latent = _empty.generate(width, height, 1)[0]
            except Exception as _e:
                import torch
                log.warning("[Lazy模型路由] 空 latent 走节点失败(%s)，改用 torch.zeros", _e)
                latent = {"samples": torch.zeros([1, 4, height // 8, width // 8])}
            log.info("[Lazy模型路由] latent 未接：已造空 latent %dx%d", width, height)

        import torch
        import comfy.sample
        import latent_preview

        samples0 = latent["samples"]
        try:
            fixed = comfy.sample.fix_empty_latent_channels(
                model, samples0,
                latent.get("downscale_ratio_spacial"),
                latent.get("downscale_ratio_temporal"),
            )
            if isinstance(fixed, torch.Tensor):
                samples0 = fixed
                latent = dict(latent); latent["samples"] = samples0
        except Exception as e:
            log.warning("[Lazy模型路由] fix_empty_latent_channels 跳过: %s", e)

        # cond 结构规整（2026-10-03 文生图崩溃修复）：cond_has_hooks 期望条目
        # 形如 [tensor, dict]；若某条目第二元素不是 dict（Tensor/str/缺失），
        # 视为无效结构 —— 记日志并剔条目，避免 "hooks" in Tensor 崩溃。
        def _sanitize_conds(c, tag):
            import torch as _torch
            if c is None:
                return None
            # 裸 Tensor：有效信号缺 [[tensor, dict]] 壳 —— 自动补壳而不是丢弃
            if isinstance(c, _torch.Tensor):
                log.warning("[Lazy模型路由] %s 收到裸 Tensor(shape=%s)，已自动包成标准条件结构",
                            tag, tuple(c.shape))
                return [[c, {}]]
            clean = []
            for item in c:
                meta = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else None
                if not isinstance(meta, dict):
                    # 条目缺 dict 壳（如 [tensor]）：补空 dict
                    if isinstance(item, (list, tuple)) and len(item) >= 1:
                        log.warning("[Lazy模型路由] %s 条目缺元数据壳(len=%s)，已补壳", tag, len(item))
                        clean.append([*item[:1], {}])
                        continue
                    log.warning("[Lazy模型路由] %s 条目结构异常(type=%s)，已剔除", tag, type(item).__name__)
                    continue
                clean.append(item)
            return clean or None

        _dbg_pos, _dbg_neg = positive, negative
        positive = _sanitize_conds(positive, "正向条件")
        negative = _sanitize_conds(negative, "负向条件")
        if positive is None:
            def _desc(c):
                if c is None:
                    return "None"
                try:
                    return f"type={type(c).__name__} len={len(c)} 条目=" + "; ".join(
                        f"[{type(x).__name__}{'×' + str(len(x)) if isinstance(x, (list, tuple)) else ''}"
                        f" meta={type(x[1]).__name__ if isinstance(x, (list, tuple)) and len(x) > 1 else '缺失'}]"
                        for x in c)
                except Exception as e:
                    return f"<描述失败 {e}>"
            raise ValueError(
                f"正向条件结构异常（条目全部无效）。正向原始: {_desc(_dbg_pos)}；"
                f"负向原始: {_desc(_dbg_neg)}；模型={model_id}")

        noise = comfy.sample.prepare_noise(samples0, seed, None)
        callback = latent_preview.prepare_callback(model, steps)
        _sig = g("Sigmas")
        if _sig is None and str(scheduler) == MANUAL_SIGMAS_NAME:
            # 下拉选 ManualSigmas：走内置 9 点阶梯（2026-10-12）。
            # 优先级低于「Sigmas」口——口接了外部阶梯就以外部为准。
            _sig = QWEN_MANUAL_SIGMAS
        if _sig is not None:
            # 手工 sigmas 阶梯（方案A 2026-10-11）：走 sample_custom，
            # 采样器沿用下拉，步数/调度器/去噪被阶梯取代（预览回调仍按步数）
            import comfy.samplers
            _sig_t = _resample_sigmas(_manual_sigmas(_sig), steps)
            _ks = comfy.samplers.sampler_object(sampler)
            log.info("[Lazy模型路由] 手工sigmas生效：%d 档（%s → %d），覆盖 步数/调度器/去噪",
                     len(_sig), sampler, len(_sig_t))
            samples = comfy.sample.sample_custom(
                model, noise, cfg, _ks, _sig_t, positive, negative, latent["samples"],
                noise_mask=latent.get("noise_mask"),
                callback=callback,
                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                seed=seed,
            )
        else:
            samples = comfy.sample.sample(
                model, noise, steps, cfg, sampler, scheduler,
                positive, negative, latent["samples"],
                denoise=denoise,
                disable_noise=False,
                start_step=None, last_step=None,
                force_full_denoise=True,
                noise_mask=latent.get("noise_mask"),
                callback=callback,
                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                seed=seed,
            )

        out_latent = dict(latent); out_latent["samples"] = samples
        pixels = vae.decode(samples)
        # 形状归一化（移植自 LazyKreaGenerate._vae_decode 收尾段，2026-10-03）：
        # qwen_image 系 VAE 是 latent_dim=3 型（带时间维 T），对 4D latent 解码会
        # 把 H 当 T，输出 5D/4D 帧张量（如 (1,1,1024,3)）——下游保存节点只吃 [B,H,W,C]。
        import torch as _torch
        if isinstance(pixels, _torch.Tensor):
            if pixels.ndim == 5:
                if pixels.shape[1] in (1, 3, 4) and pixels.shape[-1] not in (1, 3, 4):
                    pixels = pixels[:, :, 0].movedim(1, -1)
                else:
                    pixels = pixels[:, 0]
            if pixels.ndim == 4 and pixels.shape[1] in (1, 3, 4) and pixels.shape[-1] not in (1, 3, 4):
                pixels = pixels.movedim(1, -1)
            if pixels.ndim == 3:
                pixels = pixels.unsqueeze(0)
            if pixels.shape[-1] > 3:
                pixels = pixels[..., :3]
        info = (f"模型={model_id} seed={seed}({mode}) 步数={steps} cfg={cfg} "
                f"{sampler}/{scheduler} {width}x{height} denoise={denoise} {info_tail}")
        log.info("[Lazy模型路由] %s", info)
        return (pixels, model_id, info)




# ═══════════════ Krea2 编辑链（移植自 Lazybuxuexi lazy_krea_generate，2026-10-03）═══════════════
# 自包含副本：不跨包 import，避免 Deciia_Local ↔ Lazybuxuexi 耦合。
# 源头语义：编辑/四视图 = 参考图 VAE 编码 → _edit_patch 注入模型 + _grounded_encode
# 带图接地编码（30720 维）；文生图路径不受影响。

def _dc_resolve_node(class_name):
    """从 Comfy 全局注册表取节点类实例（同 lazy_h3_common.resolve_h3_node）。"""
    try:
        import nodes as _nodes
        cls = (getattr(_nodes, "NODE_CLASS_MAPPINGS", {}) or {}).get(class_name)
        return cls() if cls is not None else None
    except Exception as e:
        log.warning("[Lazy模型路由] 无法加载节点 %s: %s", class_name, e)
        return None


def _dc_call_node(node_obj, **kwargs):
    """调用节点 FUNCTION，按真实 execute 签名过滤参数（同 lazy_h3_common.call_node_function）。"""
    import inspect
    cls = node_obj.__class__
    real_fn = None
    for name in ("execute", getattr(cls, "FUNCTION", None), "run"):
        if not name:
            continue
        fn = getattr(cls, name, None)
        if callable(fn):
            real_fn = fn
            break
    if real_fn is None:
        raise RuntimeError(f"节点 {cls.__name__} 无可调用函数")
    try:
        sig = inspect.signature(real_fn)
        params = list(sig.parameters.values())
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        if not has_var_kw:
            ok = {p.name for p in params if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
            if "self" in ok and not inspect.isfunction(real_fn):
                ok = ok - {"self"}
            kwargs = {k: v for k, v in kwargs.items() if k in ok}
    except (ValueError, TypeError):
        pass
    return real_fn(node_obj, **kwargs) if not inspect.isfunction(real_fn) else real_fn(node_obj, **kwargs)


def _dc_as_list(out):
    if out is None:
        return []
    if isinstance(out, (tuple, list)):
        return list(out)
    for attr in ("args", "result", "outputs"):
        if hasattr(out, attr):
            try:
                return list(getattr(out, attr))
            except Exception:
                pass
    return [out]


def _dc_vae_latent_dim(vae) -> int:
    """qwen_image_vae 复用 WanVAE 类，latent_dim=3（含时间维）。"""
    try:
        return int(getattr(vae, "latent_dim", 2) or 2)
    except Exception:
        return 2


def _dc_normalize_latent(latent, tag, keep_temporal=True):
    """规范化 latent 到 [1,C,T?,H,W]（qwen/Wan 式 VAE 需 T 维）。"""
    import torch
    if not isinstance(latent, dict) or "samples" not in latent:
        raise RuntimeError(f"{tag}：latent 无效")
    s = latent["samples"]
    if not isinstance(s, torch.Tensor):
        raise RuntimeError(f"{tag}：samples 类型异常 {type(s)}")
    if s.ndim == 5:
        if s.shape[2] > 1:
            log.warning("[Lazy模型路由] %s latent T=%d → 只取 T=0", tag, s.shape[2])
            s = s[:, :, :1]
        if not keep_temporal:
            s = s[:, :, 0]
    elif s.ndim == 4:
        if keep_temporal:
            s = s.unsqueeze(2)
    else:
        raise RuntimeError(f"{tag}：期望 4D/5D latent，得到 {tuple(s.shape)}")
    if s.shape[0] != 1:
        log.warning("[Lazy模型路由] %s latent batch=%d → 强制 1", tag, s.shape[0])
        s = s[:1].contiguous()
    out = dict(latent)
    out["samples"] = s
    return out


def _dc_vae_encode(vae, image):
    """参考图 → latent（走 VAEEncode 节点优先，回退 vae.encode）。"""
    import torch
    if image is None:
        raise ValueError("VAE 编码：图像为空")
    img = image
    if img.ndim == 3:
        img = img.unsqueeze(0)
    img = img[:, :, :, :3]
    if img.shape[0] != 1:
        img = img[:1]
    keep_t = _dc_vae_latent_dim(vae) >= 3
    node = _dc_resolve_node("VAEEncode")
    if node is not None:
        try:
            out = _dc_call_node(node, pixels=img, vae=vae)
            args = _dc_as_list(out)
            if args and isinstance(args[0], dict) and "samples" in args[0]:
                return _dc_normalize_latent(args[0], "VAE编码", keep_temporal=keep_t)
        except Exception as e:
            log.warning("[Lazy模型路由] VAEEncode 节点失败，回退 vae.encode: %s", e)
    enc = vae.encode(img)
    if isinstance(enc, dict):
        return _dc_normalize_latent(enc, "VAE编码", keep_temporal=keep_t)
    return _dc_normalize_latent({"samples": enc}, "VAE编码", keep_temporal=keep_t)


def _dc_scale_image(image, megapixels=1.0):
    """参考图缩放到目标百万像素（lanczos，8 对齐）。"""
    node = _dc_resolve_node("ImageScaleToTotalPixels")
    if node is not None:
        try:
            out = _dc_call_node(node, image=image, upscale_method="lanczos",
                                megapixels=float(megapixels), resolution_steps=8)
            args = _dc_as_list(out)
            if args:
                return args[0]
        except Exception as e:
            log.warning("[Lazy模型路由] ImageScaleToTotalPixels 失败: %s", e)
    import comfy.utils
    b, h, w, c = image.shape
    target = max(1.0, float(megapixels)) * 1_000_000
    cur = float(h * w)
    if cur <= 0:
        return image
    sc = (target / cur) ** 0.5
    nh = max(64, int(round(h * sc / 8) * 8))
    nw = max(64, int(round(w * sc / 8) * 8))
    t = image.movedim(-1, 1)
    t = comfy.utils.common_upscale(t, nw, nh, "lanczos", "disabled")
    return t.movedim(1, -1)


def _dc_edit_patch(model, source_latent, source_latent_b=None, vae=None,
                   source_image=None, source_image_b=None,
                   ref_boost=4.0, ref_boost_a=1.0, fit_mode="fit"):
    """参考 latent 注入模型（Krea2EditModelPatch 节点）。"""
    node = _dc_resolve_node("Krea2EditModelPatch")
    if node is None:
        raise RuntimeError("未找到 Krea2EditModelPatch 节点（需要 comfyui-krea2edit 包或 Lazybuxuexi 内置后端）。")
    kw = {
        "model": model,
        "source_latent": source_latent,
        "ref_boost": float(ref_boost),
        "ref_boost_a": float(ref_boost_a),
        "fit_mode": fit_mode if fit_mode in ("fit", "crop (legacy)") else "fit",
    }
    if source_latent_b is not None:
        kw["source_latent_b"] = source_latent_b
    if vae is not None:
        kw["vae"] = vae
    if source_image is not None:
        kw["source_image"] = source_image
    if source_image_b is not None:
        kw["source_image_b"] = source_image_b
    out = _dc_call_node(node, **kw)
    args = _dc_as_list(out)
    return args[0] if args else model


def _dc_grounded_encode(clip, prompt, image=None, image_b=None, grounding_px=768):
    """Krea2 带图接地编码（30720 维）。禁止回退普通 encode（4096 维会采样炸）。"""
    node = _dc_resolve_node("Krea2EditGroundedEncode")
    if node is None:
        raise RuntimeError("未找到 Krea2EditGroundedEncode 节点。")
    if image is None:
        raise RuntimeError("编辑编码需要参考图像，但 image 为空。")
    try:
        out = node.encode(clip=clip, prompt=prompt or "", image=image,
                          image_b=image_b, grounding_px=int(grounding_px or 0),
                          system_prompt="")
    except TypeError:
        out = node.encode(clip, prompt or "", image, image_b, int(grounding_px or 0), "")
    args = _dc_as_list(out)
    if not args:
        raise RuntimeError("Krea2EditGroundedEncode 返回空。")
    cond = args[0]
    dim = _dc_cond_feat_dim(cond)
    if dim != 30720:
        raise RuntimeError(
            f"Krea2 条件维度错误：得到 {dim}，需要 30720（12×2560）。\n"
            f"请检查：CLIPLoader 的 type 必须是 krea2，clip 文件为 qwen3vl_*。")
    log.info("[Lazy模型路由] grounded encode ok dim=%s imgs=%s",
             dim, 1 + (1 if image_b is not None else 0))
    return cond


def _dc_cond_feat_dim(cond) -> int:
    try:
        return int(cond[0][0].shape[-1])
    except Exception:
        return -1


def _dc_empty_krea_latent(w, h, batch=1):
    """Krea2 文生/编辑统一 16 通道空 latent（EmptySD3LatentImage 语义）。"""
    w = max(64, int(w) // 16 * 16)
    h = max(64, int(h) // 16 * 16)
    node = _dc_resolve_node("EmptySD3LatentImage")
    if node is not None:
        try:
            out = _dc_call_node(node, width=w, height=h, batch_size=max(1, int(batch)))
            args = _dc_as_list(out)
            if args and isinstance(args[0], dict) and "samples" in args[0]:
                return args[0]
        except Exception as e:
            log.warning("[Lazy模型路由] EmptySD3LatentImage 失败，回退手造: %s", e)
    import torch
    return {"samples": torch.zeros([max(1, int(batch)), 16, max(64, h // 8), max(64, w // 8)])}


NODE_CLASS_MAPPINGS = {"LazyModelRouter": LazyModelRouter}
NODE_DISPLAY_NAME_MAPPINGS = {"LazyModelRouter": "Lazy 模型路由 · 多模型切换采样"}
