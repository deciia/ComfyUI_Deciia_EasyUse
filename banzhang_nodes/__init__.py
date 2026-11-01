# ==============================================================================
# banzhang_nodes —— 班长captain 分享的节点（经其同意收录）
#
# 原插件 ComfyUI_Deciia_Banzhang（BanZhang 全家桶）未整体开源；这里只收录
# P3a 参考工作流（example_workflows/P3a-Easy_Project_AllInOnev_beta3）用到的
# 6 个节点，代码与原插件逐字一致（仅加署名头）：
#   🛡️⚡ 显存守卫            BanZhang_VRAM_Guard
#   📈   活动监视器·内存显存  BanZhang_Mem_Graph
#        班长 MiniMax H3 预览覆盖 MiniMaxH3PreviewOverride
#   🔍   RTX 超分降噪        BanZhang_RTX_SuperResolution（需 NVIDIA Maxine/nvvfx）
#   🎞️   插帧·RIFE           BanZhang_RIFE_Interpolation
#   🧹   全能系统净化        BanZhang_VRAM_Cleaner
#
# 来源：班长captain（B站昵称）分享。其插件亦集成其他作者的功能，本署名表示分享来源，不代表节点原作者。同步以原插件为准。
# 若本机同时安装了原插件，路由（/banzhang/mem_graph 等）以先加载的插件为准，
# 节点注册以 ComfyUI 加载顺序后者覆盖，两份代码一致、行为相同。
# ==============================================================================
from . import (  # noqa: F401
    banzhang_mem_graph,
    banzhang_vram_cleaner,
    banzhang_mmh3_preview,
    banzhang_nvidia_vfx,
    banzhang_rife,
)

_KEEP = {
    "BanZhang_VRAM_Guard",
    "BanZhang_Mem_Graph",
    "MiniMaxH3PreviewOverride",
    "BanZhang_RTX_SuperResolution",
    "BanZhang_RIFE_Interpolation",
    "BanZhang_VRAM_Cleaner",
}

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
for _mod in (banzhang_mem_graph, banzhang_vram_cleaner, banzhang_mmh3_preview, banzhang_nvidia_vfx, banzhang_rife):
    _cls = getattr(_mod, "NODE_CLASS_MAPPINGS", {})
    _disp = getattr(_mod, "NODE_DISPLAY_NAME_MAPPINGS", {})
    for _name, _obj in _cls.items():
        if _name in _KEEP:
            NODE_CLASS_MAPPINGS[_name] = _obj
            NODE_DISPLAY_NAME_MAPPINGS[_name] = _disp.get(_name, _name)

assert set(NODE_CLASS_MAPPINGS) == _KEEP, f"收录不完整: {_KEEP - set(NODE_CLASS_MAPPINGS)}"
