# -*- coding: utf-8 -*-
"""Deiia 采样预设 · 采样器+调度器（终版）。

输入模型，按当前预设输出 Sigmas 与采样器方案；支持调度器 custom（自定义 Sigma 阶梯）。
多预设由前端 ⚙ 菜单管理。Sigmas 计算逐字对齐内核 BasicScheduler；
采样器对象逐字对齐 KSamplerSelect。
"""

import torch
import comfy.samplers
import folder_paths
from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


class DeciiaSamplerPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSamplerPreset",
            display_name="Deiia 采样预设 · 采样器+调度器",
            category="Deciia/local",
            description=(
                "采样设置预设：输入模型，按当前预设输出 Sigmas 与采样器方案，"
                "支持多预设切换与调度器 custom（自定义 Sigma 阶梯）。"
                "Sigmas 算法与内核 BasicScheduler 一致。"
            ),
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler",
                               tooltip="采样器方案（预设切换时自动同步）。"),
                io.Combo.Input("scheduler", options=comfy.samplers.SCHEDULER_NAMES + ["custom"],
                               default="beta",
                               tooltip="调度器。选 custom 时使用「自定义 Sigma」输入框里的阶梯。"),
                io.Int.Input("steps", default=4, min=1, max=10000, tooltip="总步数。"),
                io.Float.Input("denoise", default=1.0, min=0.0, max=1.0, step=0.01,
                               tooltip="去噪强度（<1.0 按内核规则折算步数）。"),
                io.String.Input("custom_sigmas", default="", multiline=True, advanced=True,
                                tooltip="自定义 Sigma 阶梯：逗号分隔数值（降序，含末位 0），"
                                        "仅调度器选 custom 时生效。如 14.61,3.2,1.0,0"),
            ],
            outputs=[
                io.Sigmas.Output(display_name="Sigmas"),
                io.Sampler.Output(display_name="采样器方案"),
            ],
        )

    @classmethod
    def execute(cls, model, sampler_name, scheduler, steps, denoise, custom_sigmas="") -> io.NodeOutput:
        sampler = comfy.samplers.sampler_object(sampler_name)

        if scheduler == "custom":
            raw = (custom_sigmas or "").strip()
            if not raw:
                raise RuntimeError(
                    "调度器选择了 custom（自定义），但「自定义 Sigma」为空——"
                    "请填写逗号分隔的 Sigma 阶梯（如 14.61,3.2,1.0,0），或把调度器改回具体类型")
            vals = [float(x) for x in raw.replace("，", ",").split(",") if x.strip()]
            return io.NodeOutput(torch.FloatTensor(vals), sampler)

        steps = int(steps)
        total_steps = steps
        if denoise < 1.0:
            if denoise <= 0.0:
                return io.NodeOutput(torch.FloatTensor([]), sampler)
            total_steps = int(steps / denoise)
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"), scheduler, total_steps).cpu()
        sigmas = sigmas[-(steps + 1):]
        return io.NodeOutput(sigmas, sampler)


NODE_CLASS_MAPPINGS["DeciiaSamplerPreset"] = DeciiaSamplerPreset
NODE_DISPLAY_NAME_MAPPINGS["DeciiaSamplerPreset"] = "Deiia 采样预设 · 采样器+调度器"
