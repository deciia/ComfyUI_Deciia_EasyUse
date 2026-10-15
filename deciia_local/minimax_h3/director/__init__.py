"""曜石导演台 · Deciia 版 — 独立于 T8 原版的并行实现。

与原版共存：node_id 与路由前缀都带 `_deciia` 隔离，采样节点等共享依赖
继续用 T8 原包（见 t8_bridge.py），因此两边可随时切换或同时开。

原包被 `.disabled` 时本模块整体不注册，不影响 ComfyUI_Deciia_Local 其它功能。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "t8_bridge.py"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import t8_bridge  # noqa: E402  (needs HERE on sys.path)

NODE_CLASS_MAPPINGS: dict[str, type] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

ROUTED = False


def _register() -> None:
    """Load the vendored director stack and register node + routes."""
    global ROUTED
    t8_bridge.preload()

    # The vendored files sit inside the shim's h3_t8 child package, so they must
    # be imported under that name — importing them as top-level `h3_t8` would
    # collide with the upstream package ComfyUI already loaded.
    import importlib

    director_routes = importlib.import_module(f"{t8_bridge.SYNTH}.h3_t8.director_routes")
    nodes_director = importlib.import_module(f"{t8_bridge.SYNTH}.h3_t8.nodes_director")

    node_cls = nodes_director.MiniMaxH3DirectorProjectDeciia
    NODE_CLASS_MAPPINGS[node_cls.__name__] = node_cls
    NODE_DISPLAY_NAME_MAPPINGS[node_cls.__name__] = "曜石导演台 · Deciia 版"

    director_routes.register_director_routes()
    ROUTED = True


try:
    _register()
except Exception as exc:  # never take the rest of Deciia_Local down with us
    print(f"[Deciia Director] 加载失败（不影响 ComfyUI_Deciia_Local 其它功能）: {exc}")
    import traceback

    traceback.print_exc()
