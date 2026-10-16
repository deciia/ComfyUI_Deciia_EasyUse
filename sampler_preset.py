# -*- coding: utf-8 -*-
"""Deiia 采样预设 · 采样器+调度器（稳定模式版）。

输入模型，按当前预设输出 Sigmas 与采样器方案。全部为普通控件：
scheduler 选 custom 时用自定义 Sigma 阶梯（空则明确报错），否则按 BasicScheduler 算法计算。
Sigmas 计算逐字对齐内核 BasicScheduler；采样器对象逐字对齐 KSamplerSelect。
"""

import json

import torch
import comfy.samplers
import folder_paths
from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_DEFAULT_PRESETS = {
    "current": "通用",
    "presets": [{
        "name": "通用", "group": "通用",
        "sampler_name": "euler", "scheduler": "simple", "steps": 8, "denoise": 1.0,
        "custom_sigmas": "",
    }],
}


class DeciiaSamplerPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSamplerPreset",
            display_name="Deiia 采样预设 · 采样器+调度器",
            category="Deciia/local",
            description=(
                "采样设置预设：输入模型，按当前预设输出 Sigmas 与采样器方案。"
                "scheduler 选 custom 用自定义 Sigma 阶梯，否则按 steps/denoise 计算。"
                "多预设由 ⚙ 菜单管理。"
            ),
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler",
                               tooltip="采样器方案（预设切换时自动同步）。"),
                io.Combo.Input("scheduler", options=["custom"] + comfy.samplers.SCHEDULER_NAMES,
                               default="simple",
                               tooltip="调度器。选 custom 时使用自定义 Sigma 阶梯。"),
                io.Int.Input("steps", default=8, min=1, max=10000, tooltip="总步数。"),
                io.Float.Input("denoise", default=1.0, min=0.0, max=1.0, step=0.01,
                               tooltip="去噪强度（<1.0 按内核规则折算步数）。"),
                io.String.Input("custom_sigmas", default="",
                                tooltip="自定义 Sigma 阶梯：逗号分隔数值（降序，含末位 0），仅 scheduler=custom 时显示并生效。如 14.61,3.2,1.0,0"),
                io.String.Input("presets_json", default=json.dumps(_DEFAULT_PRESETS, ensure_ascii=False),
                                multiline=True, advanced=True,
                                tooltip="预设数据（前端 ⚙ 菜单自动维护，一般不用手改）。"),
            ],
            outputs=[
                io.Sigmas.Output(display_name="Sigmas"),
                io.Sampler.Output(display_name="采样器方案"),
            ],
        )

    @classmethod
    def execute(cls, model, sampler_name, scheduler, steps, denoise, custom_sigmas="", presets_json="") -> io.NodeOutput:
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
