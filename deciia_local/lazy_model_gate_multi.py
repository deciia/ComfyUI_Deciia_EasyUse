"""Lazy 模型门控·主路旁路（2026-10-01 rev5，按异恒简化定稿）。

三口一出口，就一条规则：

    模型选择 == 本链模型 → 主路通：出口 = 主路入口数据
    模型选择 ≠ 本链模型 → 走旁路：
        ① 旁路入口未接上游 → 出口 = 主路入口数据（原样直通）
        ② 旁路入口接了上游 → 出口 = 旁路入口数据

放法：门控摆在被跳过节点的【旁边】——
    上游数据 ──► 主路入口                  ┌──(被跳过节点不在此路径)──► 出口 ──► 下游
    旁路源   ──► 旁路入口(可不接)
被跳过的节点链（如 Fun ControlNet）从【上游数据的另一条分叉】进、其输出
不接本门控（接了也不读）——不匹配时引擎只调度被点名那条的上游，被跳过链
整支不执行（lazy 机制，不产生 blocker）。

匹配时主路入口→出口直通；被跳过链要不要跑由它自己的消费者决定
（通常它就在主路上：上游分叉 → 被跳过节点 → 门控出口之前的下游）。
"""
from __future__ import annotations

import logging

log = logging.getLogger("LazyModelGateMulti")

_MODEL_IDS = ["qwen2.1", "krea2"]


class _AnyType(str):
    def __ne__(self, value): return False
    def __eq__(self, value): return True
    def __str__(self): return "*"


ANY = _AnyType("*")


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


class LazyModelGateMulti:
    """模型门控 · 主路/旁路（if-else 单通路版）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模型选择": ("STRING", {
                    "forceInput": True,
                    "tooltip": "接合并台「模型选择」/ 模型加载枢纽「当前组」。",
                }),
                "本链模型": (_MODEL_IDS, {"default": _MODEL_IDS[0], "tooltip": "本门控服务的模型。"}),
            },
            "optional": {
                "主路": (ANY, {"lazy": True, "tooltip": "主路数据入口（经被门控节点链）。匹配时主路通。"}),
                "旁路": (ANY, {"lazy": True, "tooltip": "旁路数据入口（绕过被门控链的直连分叉）。不匹配时旁路通。"}),
            },
            "hidden": {
                "出口连线": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = (ANY, ANY)
    RETURN_NAMES = ("主路出口", "旁路出口")
    FUNCTION = "gate"
    CATEGORY = "Lazy"
    DESCRIPTION = "Lazy 模型门控 · 主路旁路双通道（匹配→主路通旁路断；不匹配→旁路通主路断）"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def check_lazy_status(self, 模型选择="", 本链模型=_MODEL_IDS[0], 出口连线="", **kwargs):
        """只点名当前通的那条；断的那条上游整支不执行。
        出口连线: 前端维护的 hidden 串，如 "主路出口:1,旁路出口:0"（1=有下游）。

        坑（2026-10-02 实测 · 路由节点拿到 None 的根因）：
        lazy 输入在 check_lazy_status 里**必定还是 None**——它就是因为没求值才要你点名。
        所以绝不能"先看它的值，非 None 才点名"，那样永远点不到，节点会带着
        None 直接执行，下游拿到 None（表现为"请连接 Qwen模型/…"）。
        只能按非 lazy 信号判断：本链模型是否匹配 + 出口连线有没有下游。
        """
        matched = _normalize(模型选择) == _normalize(本链模型)
        main_out_used = "主路出口:1" in str(出口连线 or "")
        bypass_out_used = "旁路出口:1" in str(出口连线 or "")
        need = []
        if matched:
            need.append("主路")            # 出口 = 主路数据，必须求值
        else:
            if main_out_used or bypass_out_used:
                need.append("旁路")        # 不匹配时的数据源（旁路口没接→None，无害）
            if bypass_out_used:
                need.append("主路")        # 旁路口没接时，旁路出口回退主路数据
        return need or None

    def gate(self, 模型选择="", 本链模型=_MODEL_IDS[0], 出口连线="", **kwargs):
        current = _normalize(模型选择)
        mine = _normalize(本链模型)
        matched = current == mine
        main_v = kwargs.get("主路")
        bypass_v = kwargs.get("旁路")
        bypass_in = bypass_v is not None
        main_out_used = "主路出口:1" in str(出口连线 or "")
        bypass_out_used = "旁路出口:1" in str(出口连线 or "")
        if matched:
            main_out = main_v
            bypass_out = None
            tag = "主路通/旁路断"
        else:
            if bypass_in:
                # 旁路入口接了：旁路出口=旁路数据；主路出口=有下游才给旁路数据（对称回退），否则 None
                bypass_out = bypass_v
                main_out = bypass_v if main_out_used else None
                tag = "主路断/旁路通" + ("（主路出口回退旁路数据）" if main_out_used else "")
            else:
                # 旁路入口没接：旁路出口=主路数据（有下游才需要）；主路出口=None
                bypass_out = main_v if bypass_out_used else None
                main_out = None
                tag = "主路断/旁路取主路数据"
        log.info("[模型门控·主旁路] 当前=%s 本链=%s → %s", current, mine, tag)
        return (main_out, bypass_out)


NODE_CLASS_MAPPINGS = {"LazyModelGateMulti": LazyModelGateMulti}
NODE_DISPLAY_NAME_MAPPINGS = {"LazyModelGateMulti": "Lazy 模型门控 · 主路旁路"}
