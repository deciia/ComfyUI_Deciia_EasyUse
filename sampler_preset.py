# -*- coding: utf-8 -*-
"""Deiia 采样预设 · 采样器+调度器（DynamicCombo 原生显隐版）。

输入模型，按当前预设输出 Sigmas 与采样器方案。scheduler 为 DynamicCombo：
选 custom 只显示自定义 Sigma 输入框；选标准调度器显示 steps/denoise——
显隐由前端原生处理（同 Deiia 稀疏注意力节点的 dense_mode 机制），无自定义 JS。
Sigmas 计算逐字对齐内核 BasicScheduler；采样器对象逐字对齐 KSamplerSelect。
"""

import torch
import comfy.samplers
import folder_paths
from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def _scheduler_combo():
    opts = [io.DynamicCombo.Option("custom", [
        io.String.Input("custom_sigmas", default="",
                        tooltip="自定义 Sigma 阶梯：逗号分隔数值（降序，含末位 0）。如 14.61,3.2,1.0,0"),
    ])]
    for s in comfy.samplers.SCHEDULER_NAMES:
        opts.append(io.DynamicCombo.Option(s, [
            io.Int.Input("steps", default=4, min=1, max=10000, tooltip="总步数。"),
            io.Float.Input("denoise", default=1.0, min=0.0, max=1.0, step=0.01,
                           tooltip="去噪强度（<1.0 按内核规则折算步数）。"),
        ]))
    return io.DynamicCombo.Input("scheduler", options=opts,
                                 tooltip="调度器。选 custom 用自定义 Sigma 阶梯；选标准调度器按 steps/denoise 计算。")


class DeciiaSamplerPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSamplerPreset",
            display_name="Deiia 采样预设 · 采样器+调度器",
            category="Deciia/local",
            description=(
                "采样设置预设：输入模型，按当前预设输出 Sigmas 与采样器方案。"
                "scheduler 选 custom 只显示自定义 Sigma 框，选标准调度器显示 steps/denoise（原生联动显隐）。"
            ),
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler",
                               tooltip="采样器方案（预设切换时自动同步）。"),
                _scheduler_combo(),
            ],
            outputs=[
                io.Sigmas.Output(display_name="Sigmas"),
                io.Sampler.Output(display_name="采样器方案"),
            ],
        )

    @classmethod
    def execute(cls, model, sampler_name, scheduler) -> io.NodeOutput:
        sampler = comfy.samplers.sampler_object(sampler_name)

        # DynamicCombo 解包：dict 以组合 id 为键（见 _io.py DynamicCombo）
        sel = scheduler.get("scheduler", "beta") if isinstance(scheduler, dict) else scheduler

        if sel == "custom":
            raw = (scheduler.get("custom_sigmas", "") or "").strip() if isinstance(scheduler, dict) else ""
            if not raw:
                raise RuntimeError(
                    "调度器选择了 custom（自定义），但「自定义 Sigma」为空——"
                    "请填写逗号分隔的 Sigma 阶梯（如 14.61,3.2,1.0,0），或把调度器改回具体类型")
            vals = [float(x) for x in raw.replace("，", ",").split(",") if x.strip()]
            return io.NodeOutput(torch.FloatTensor(vals), sampler)

        steps = int(scheduler.get("steps", 4)) if isinstance(scheduler, dict) else 4
        denoise = float(scheduler.get("denoise", 1.0)) if isinstance(scheduler, dict) else 1.0
        total_steps = steps
        if denoise < 1.0:
            if denoise <= 0.0:
                return io.NodeOutput(torch.FloatTensor([]), sampler)
            total_steps = int(steps / denoise)
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"), sel, total_steps).cpu()
        sigmas = sigmas[-(steps + 1):]
        return io.NodeOutput(sigmas, sampler)


NODE_CLASS_MAPPINGS["DeciiaSamplerPreset"] = DeciiaSamplerPreset
NODE_DISPLAY_NAME_MAPPINGS["DeciiaSamplerPreset"] = "Deiia 采样预设 · 采样器+调度器"
