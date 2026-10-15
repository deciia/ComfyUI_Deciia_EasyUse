"""Deciia 本地曜石导演台 — 独立于 T8 原版的第二套实现。

架构：不搬 T8 的 139 模块闭包，而是把 vendored 的 `h3_t8/director_*.py`
挂成子包 `deciia_t8_director_shim.h3_t8`，并把缺失依赖委托给原包已加载的
`h3_t8`（ComfyUI 启动时已按真实包名导入过一次）。

关键点：子包挂 PEP 562 的 `__getattr__`，把找不到的名字转交原包。于是
vendored 文件里的 `from .ffmpeg_utils import ...`、`from .h3_weight_diagnostics
import ...` 自动取到原包代码——既不用逐个手工注入，也不会出现"模块被注册到
错误包名下"（手工 setattr 到 shim 会让原包模块内部的相对 import 反过来指向
shim，报 No module named 'deciia_t8_director_shim.xxx'）。

这样：
- 原包一个字节都不改，git pull 干净，随时换回官方导演台
- 采样节点 / 共享依赖继续用原包的，不重复注册、不改 id
- 只有导演台的 node_id 与路由前缀与官方隔离

原包缺失时本模块整体不注册（见 __init__.py 的 try）。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM_DIRNAME = "comfyui-minimax-h3-audio-T8"
SYNTH = "deciia_t8_director_shim"

_lock = threading.RLock()
_upstream: types.ModuleType | None = None


def _custom_nodes() -> Path:
    # .../custom_nodes/ComfyUI_Deciia_Local/minimax_h3/director/t8_bridge.py
    return HERE.parents[2]


def upstream_dir() -> Path:
    for child in sorted(_custom_nodes().iterdir()):
        if not child.is_dir():
            continue
        if child.name in (UPSTREAM_DIRNAME, UPSTREAM_DIRNAME + ".disabled"):
            if (child / "h3_t8" / "director_routes.py").is_file():
                return child
    raise ImportError(f"T8 package '{UPSTREAM_DIRNAME}' not found under {_custom_nodes()}")


def upstream_h3_t8() -> types.ModuleType:
    """The real upstream h3_t8 package (ComfyUI already imported it at startup)."""
    global _upstream
    if _upstream is not None:
        return _upstream

    # 1) reuse what ComfyUI imported under the real package name
    for mod in list(sys.modules.values()):
        if mod is not None and getattr(mod, "__name__", "") == "h3_t8" and hasattr(mod, "__path__"):
            _upstream = mod
            return mod

    # 2) otherwise import it ourselves (needs the package root on sys.path)
    root = upstream_dir()
    if root.name.endswith(".disabled"):
        raise ImportError(f"{root.name} is disabled; enable it to use the Deciia director")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _upstream = importlib.import_module("h3_t8")
    return _upstream


def _delegate(name: str):
    """PEP 562 hook: resolve vendored-package misses against upstream h3_t8."""
    if name.startswith("__"):
        raise AttributeError(name)
    upstream = upstream_h3_t8()
    try:
        return getattr(upstream, name)
    except AttributeError:
        pass
    try:
        return importlib.import_module(f"h3_t8.{name}")
    except Exception as exc:
        raise AttributeError(f"upstream h3_t8 has no {name!r}: {exc}") from exc


def build_namespace_package() -> types.ModuleType:
    """Create SYNTH + SYNTH.h3_t8 so the vendored files' `from .x import` resolves.

    A PEP 562 `__getattr__` is NOT enough: `from .ffmpeg_utils import x` asks
    importlib for the *submodule*, and submodule lookup never consults
    `__getattr__`. So the child package also installs a meta-path finder that
    materialises any `SYNTH.h3_t8.<name>` the vendored tree references but does
    not ship, by aliasing the already-imported upstream module into sys.modules.
    """
    with _lock:
        pkg = sys.modules.get(SYNTH)
        if pkg is None:
            pkg = types.ModuleType(SYNTH)
            pkg.__path__ = [str(HERE)]
            sys.modules[SYNTH] = pkg

        child_name = f"{SYNTH}.h3_t8"
        child = sys.modules.get(child_name)
        if child is None:
            child = types.ModuleType(child_name)
            child.__path__ = [str(HERE / "h3_t8")]
            child.__package__ = child_name
            child.__getattr__ = _delegate  # type: ignore[attr-defined]
            sys.modules[child_name] = child
        setattr(pkg, "h3_t8", child)

        if not any(isinstance(f, _UpstreamAliasFinder) for f in sys.meta_path):
            sys.meta_path.append(_UpstreamAliasFinder())
        return pkg


class _UpstreamAliasFinder:
    """Resolve `deciia_t8_director_shim.h3_t8.<x>` to upstream `h3_t8.<x>`."""

    PREFIX = f"{SYNTH}.h3_t8."

    def find_module(self, fullname, path=None):  # legacy API, unused
        return None

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.PREFIX):
            return None
        leaf = fullname[len(self.PREFIX):]
        if "." in leaf:
            return None
        upstream = HERE / "h3_t8" / f"{leaf}.py"
        if upstream.is_file():
            return None  # vendored locally; let the normal path finder win
        try:
            mod = importlib.import_module(f"h3_t8.{leaf}")
        except Exception:
            return None
        sys.modules[fullname] = mod
        spec = importlib.util.spec_from_loader(fullname, loader=_AliasLoader(mod))
        return spec


class _AliasLoader:
    """Loader that returns an already-built module object unchanged."""

    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):
        return None


def preload() -> str:
    """Bind the namespace package and prove upstream is reachable."""
    pkg = build_namespace_package()
    upstream_h3_t8()
    return pkg.__name__
