"""Lazy 模型门控（2026-10-01，参考 Goohai 任意切换 GH 的阻断机制）。

用法：
  Lazy 合并台「模型选择」出口 ──► 本节点「模型选择」输入口
  模型专属链的数据（CONDITIONING / MODEL / IMAGE …）──►「数据」口
  本节点输出 ──► 汇入「任意切换 GH」（或直接接消费节点）

规则（rev2 旁路开关语义）：
      匹配     → 透传「数据」（专属链处理后的结果，如 ControlNet 后条件）。
      不匹配   → 「原始数据」有连接 → 旁路透传原始数据（= 忽略/跳过本链，效果上
                 ControlNet 不存在）；未连接 → ExecutionBlocker 阻断。
      ExecutionBlocker 会被下游级联传染（comfy execution.py 行269-277）：
      收到 blocker 的节点整串跳过。
布线（旁路开关形态，无环）：
      原始正向条件 ──┬──► ControlNet 正向口
                    └──► 本节点「原始数据」
      ControlNet 输出 ──► 本节点「数据」
      本节点输出 ──► 下游
      （注意：ControlNet 的输入直接取原始条件，不经本节点——否则成环被拒绝。）

上游剪枝提示：ExecutionBlocker 只阻断本节点下游；要整链不执行省显存，
把专属链放进 «tag» 组（«qwen» / «krea»），由 Lazy 模型路由的前端联动
整组 mute（Goohai 忽略多组同款）。两层机制互补：组联动省显存，本节点兜底语义。
"""
from __future__ import annotations

import logging

log = logging.getLogger("LazyModelGate")

try:
    from comfy_execution.graph import ExecutionBlocker
except Exception:  # pragma: no cover
    ExecutionBlocker = ()


class _AnyType(str):
    def __ne__(self, value): return False
    def __eq__(self, value): return True
    def __str__(self): return "*"


ANY = _AnyType("*")

# 与 LazyModelRouter.MODEL_REGISTRY 保持一致
_MODEL_IDS = ["qwen2.1", "krea2"]


def _normalize(value: str) -> str:
    v = str(value or "").lower()
    for mid in _MODEL_IDS:
        if mid in v:
            return mid
    if "krea" in v:
        return "krea2"
    if "qwen" in v:
        return "qwen2.1"
    return v


class LazyModelGate:
    """模型门控 · 匹配放行，不匹配阻断。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模型选择": ("STRING", {
                    "forceInput": True,
                    "tooltip": "接 Lazy 合并台「模型选择」出口（当前模型 id，如 qwen2.1 / krea2）。",
                }),
                "本链模型": (_MODEL_IDS, {
                    "default": _MODEL_IDS[0],
                    "tooltip": "本条专属链服务的模型。与合并台当前模型一致才放行数据。",
                }),
            },
            "optional": {
                "数据": (ANY, {"tooltip": "匹配时透传的数据（专属链处理后的输出，如 ControlNet 后的条件）。"}),
                "原始数据": (ANY, {"tooltip": "不匹配时旁路透传的数据（如未经 ControlNet 的原始正向条件）。不连则输出阻断。"}),
            },
        }

    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("数据",)
    FUNCTION = "gate"
    CATEGORY = "Lazy"
    DESCRIPTION = "Lazy 模型门控 · 模型匹配放行 / 不匹配阻断"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def gate(self, 模型选择="", 本链模型=_MODEL_IDS[0], 数据=None, **kwargs):
        current = _normalize(模型选择)
        mine = _normalize(本链模型)
        if current != mine:
            if 原始数据 is not None:
                log.info("[Lazy模型门控] 当前=%s 本链=%s → 旁路透传原始数据(忽略本链)", current, mine)
                return (原始数据,)
            log.info("[Lazy模型门控] 当前=%s 本链=%s → 阻断", current, mine)
            if ExecutionBlocker:
                return (ExecutionBlocker(f"模型门控: 当前 {current} ≠ 本链 {mine}"),)
            raise RuntimeError(f"模型门控阻断（当前 {current} ≠ 本链 {mine}）且环境无 ExecutionBlocker。")
        if 数据 is None:
            raise ValueError("模型匹配但「数据」口未连接。")
        log.info("[Lazy模型门控] 当前=%s 本链=%s → 放行", current, mine)
        return (数据,)


NODE_CLASS_MAPPINGS = {"LazyModelGate": LazyModelGate}
NODE_DISPLAY_NAME_MAPPINGS = {"LazyModelGate": "Lazy 模型门控 · 匹配放行"}
