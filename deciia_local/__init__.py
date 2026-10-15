"""Deiia Easy Use · deciia_local 子包（原 ComfyUI_Deciia_Local，2026-10-16 并入）。

包含：ServiceBridge（配置在用户目录 service_bridge.json）、路由门禁、
Lazy 模型路由/门控、模型枢纽、曜石导演台、分块 PASS2、稀疏注意力预设。
端点与域名等敏感配置一律放用户目录，不进仓库。
"""

from . import local_service  # noqa: F401  (registers server routes on import)

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# --- Deciia 分块 PASS2 V2 ---
try:
    from .minimax_h3.h3_sampling import chunked_pass2_v2 as _chunked_pass2_v2
    NODE_CLASS_MAPPINGS.update(_chunked_pass2_v2.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_chunked_pass2_v2.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] chunked_pass2_v2 加载失败:", _e)

# --- Deciia 路由门禁 ---
try:
    from . import deciia_route_gate as _deciia_route_gate  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_deciia_route_gate.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_deciia_route_gate.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] deciia_route_gate 加载失败:", _e)

# --- Lazy 模型路由 ---
try:
    from . import lazy_model_router as _lazy_model_router  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_lazy_model_router.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_lazy_model_router.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] lazy_model_router 加载失败:", _e)

# --- Lazy 模型门控 ---
try:
    from . import lazy_model_gate as _lazy_model_gate  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_lazy_model_gate.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_lazy_model_gate.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] lazy_model_gate 加载失败:", _e)

# --- Lazy 模型门控·多通路 ---
try:
    from . import lazy_model_gate_multi as _lazy_model_gate_multi  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_lazy_model_gate_multi.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_lazy_model_gate_multi.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] lazy_model_gate_multi 加载失败:", _e)

# --- Deciia 模型加载枢纽 ---
try:
    from . import model_hub as _model_hub  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_model_hub.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_model_hub.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] model_hub 加载失败:", _e)

# --- Deciia 曜石导演台 ---
try:
    from .minimax_h3 import director as _deciia_director  # noqa: F401
    NODE_CLASS_MAPPINGS.update(_deciia_director.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_deciia_director.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] deciia_director 加载失败:", _e)


# --- Deciia 稀疏注意力 · Sol-Attn 预设 ---
try:
    from . import deciia_sparse_solattn as _deciia_sparse_solattn
    NODE_CLASS_MAPPINGS.update(_deciia_sparse_solattn.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_deciia_sparse_solattn.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _e:
    print("[deciia_local] deciia_sparse_solattn 加载失败:", _e)


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
