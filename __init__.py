"""ComfyUI_Deciia_All（作者 deciia）

自建 ComfyUI 自定义节点合集：MiniMax-H3 采样执行器、跨插件桥接节点、
LoRA 串管理，以及配套前端面板。

子包布局（按模型域划分，便于以后扩展其它模型）：
- minimax_h3/  H3 专属：h3_sampling（分块/时间分块二采执行器）、
  ght8_bridge、reft8_bridge（跨插件桥接）
- stacks/      模型无关：DeciiaVramSafeLoraStack
- qwen_image_21/ Qwen-Image 2.1：Lazy 预览保存（仅预览切换+图像透传）
- web/         前端 JS（LoRA 面板）
- examples/    示例工作流
- docs/        上游依赖关系与节点说明

上游插件（T8 / GH / MiniMaxRefDirector）全部运行时互操作，零修改、
零代码复制，可独立正常更新；详见 docs/upstream-dependencies.md。
"""

from .minimax_h3.h3_sampling import (
    chunked_pass2 as _chunked_pass2,
    tiled_second_pass as _tiled_second_pass,
)
from .stacks import (
    vramsafe_lora_stack as _vramsafe_lora_stack,
)
from .minimax_h3.ght8_bridge import nodes as _ght8_nodes
from .minimax_h3.reft8_bridge import nodes as _reft8_nodes
from .workstation import nodes as _workstation_nodes
from .qwen_image_21 import (
    NODE_CLASS_MAPPINGS as _qwen21_class,
    NODE_DISPLAY_NAME_MAPPINGS as _qwen21_display,
)
from .workstation import store as _workstation_store

NODE_CLASS_MAPPINGS = {
    **_tiled_second_pass.NODE_CLASS_MAPPINGS,
    **_chunked_pass2.NODE_CLASS_MAPPINGS,
    **_vramsafe_lora_stack.NODE_CLASS_MAPPINGS,
    **_ght8_nodes.NODE_CLASS_MAPPINGS,
    **_reft8_nodes.NODE_CLASS_MAPPINGS,
    **_workstation_nodes.NODE_CLASS_MAPPINGS,
    **_qwen21_class,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **_tiled_second_pass.NODE_DISPLAY_NAME_MAPPINGS,
    **_chunked_pass2.NODE_DISPLAY_NAME_MAPPINGS,
    **_vramsafe_lora_stack.NODE_DISPLAY_NAME_MAPPINGS,
    **_ght8_nodes.NODE_DISPLAY_NAME_MAPPINGS,
    **_reft8_nodes.NODE_DISPLAY_NAME_MAPPINGS,
    **_workstation_nodes.NODE_DISPLAY_NAME_MAPPINGS,
    **_qwen21_display,
}

WEB_DIRECTORY = "./web"

# --- Sol-Attn 签名兼容垫片 ---
# sol_attn_minimax_v2 按旧内核 API 传参，comfy_kitchen 新内核已移除这些参数
# → TypeError → Sol-Attn 每步 fallback 慢速注意力。包导入期安装进程级
# 幂等包装（详见 minimax_h3/h3_sampling/solattn_compat.py）。
def _install_solattn_shim() -> None:
    from .minimax_h3.h3_sampling.solattn_compat import install
    install()


try:
    _install_solattn_shim()
except Exception as _e:  # 垫片失败不影响本包主功能
    import logging
    logging.getLogger(__name__).warning("[Deciia] Sol-Attn 垫片安装失败(忽略): %s", _e)

# --- 工作台 HTTP 路由（/deciia_workstation/tools、/probe） ---
# main.py 中 PromptServer 先于 init_extra_nodes 创建，import 期即可注册。
try:
    if not _workstation_store.register_routes():
        import logging
        logging.getLogger(__name__).warning(
            "[Deciia] 工作台路由未注册（PromptServer 尚未就绪）——重启 ComfyUI 后生效"
        )
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning("[Deciia] 工作台路由注册失败: %s", _e)

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]

# --- deciia_local 子包（ServiceBridge/路由门禁/Lazy 路由/模型枢纽/导演台；2026-10-16 并入 ComfyUI_Deciia_Local）---
try:
    from . import deciia_local as _deciia_local  # noqa: F401  (含节点注册与服务路由)
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning("[DeciiaEasyUse] deciia_local 加载失败: %s", _e)
