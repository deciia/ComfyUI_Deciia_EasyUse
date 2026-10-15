"""Deciia 路由门禁（2026-10-02，beta2「是否反推」联动用）。

复刻 GoohaiRouteBlocker 语义（是否阻断 / 阻断模式 / any 透传），
另加一个「是否阻断」BOOLEAN 输出口：把本节点的开关值广播出去，
供下游路由阻断节点（GoohaiRouteBlocker.是否阻断）联动——
一处手动开关，多道门同步。

典型布线（beta2）：
  姿势控制组原图 → any ─┐
  是否阻断 = false(反推) │ any 透传 → PERewrite/PEApiBoost.image_1
                        └ 是否阻断 → [813]路由阻断.是否阻断（converted input）
  即：不反推时图既不给增强器、也不进合并台。
"""
from __future__ import annotations

log = __import__("logging").getLogger("DeciiaRouteGate")

try:  # ComfyUI 原生静默阻断原语
    from comfy_execution.devices import ExecutionBlocker  # type: ignore
except Exception:  # pragma: no cover - 兼容旧版路径
    try:
        from execution import ExecutionBlocker  # type: ignore
    except Exception:
        ExecutionBlocker = None

ANY = "*"


class DeciiaRouteGate:
    """按开关透传 any，同时广播「是否阻断」布尔值（BOOLEAN 输出口）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "是否阻断": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "阻断",
                        "label_off": "通过",
                    },
                ),
                "阻断模式": (
                    ["仅输出空值", "中断后续分支"],
                    {"default": "仅输出空值"},
                ),
            },
            "optional": {
                "any": (ANY,),
            },
        }

    RETURN_TYPES = (ANY, "BOOLEAN")
    RETURN_NAMES = ("any", "是否阻断")
    FUNCTION = "gate"
    CATEGORY = "deciiia/门控"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    @staticmethod
    def gate(any=None, 是否阻断=False, 阻断模式="仅输出空值"):
        if not 是否阻断:
            return (any, False,)
        # 阻断时布尔出口仍输出 True（门禁状态与数据通路独立）
        if 阻断模式 == "仅输出空值":
            return (None, True,)
        if isinstance(ExecutionBlocker, type):
            return (ExecutionBlocker(None), True,)
        return (None, True,)


NODE_CLASS_MAPPINGS = {"DeciiaRouteGate": DeciiaRouteGate}
NODE_DISPLAY_NAME_MAPPINGS = {"DeciiaRouteGate": "Deciia 路由门禁 (RouteGate)"}
