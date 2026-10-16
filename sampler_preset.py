# -*- coding: utf-8 -*-
"""Deiia 采样预设 · 采样器+调度器（v2 分组/双采兼容版）。

一个预设 = 一个采样场景（单采 / T8双采 / selflift-Avatar…），
内含一采与二采两组参数（sampler_name / scheduler / steps / denoise）。
输出：一采Sigmas、二采Sigmas、一采采样器方案、二采采样器方案。
Sigmas 计算逐字对齐内核 BasicScheduler；采样器对象逐字对齐 KSamplerSelect。
"""

import json

import comfy.samplers
import folder_paths
from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_DEFAULT_PRESETS = {
    "current": "H3无损融合单采",
    "presets": [
        {
            "name": "H3无损融合单采", "group": "H3无损融合单采",
            "sampler_name": "euler", "scheduler": "beta", "steps": 6, "denoise": 1.0,
            "p2_sampler_name": "euler", "p2_scheduler": "beta", "p2_steps": 4, "p2_denoise": 1.0,
        },
        {
            "name": "T8双采 4+4", "group": "T8双采",
            "sampler_name": "euler", "scheduler": "beta", "steps": 4, "denoise": 1.0,
            "p2_sampler_name": "euler", "p2_scheduler": "beta", "p2_steps": 4, "p2_denoise": 1.0,
        },
        {
            "name": "Selflift-Avatar", "group": "selflift-Avatar",
            "sampler_name": "euler", "scheduler": "beta", "steps": 6, "denoise": 1.0,
            "p2_sampler_name": "euler", "p2_scheduler": "beta", "p2_steps": 4, "p2_denoise": 1.0,
        },
    ],
}


def _sigmas_for(model, sampler_name, scheduler, steps, denoise):
    """逐字对齐内核 BasicScheduler（nodes_custom_sampler.py:33-42）。"""
    steps = int(steps)
    total_steps = steps
    if denoise < 1.0:
        if denoise <= 0.0:
            return None
        total_steps = int(steps / denoise)
    sigmas = comfy.samplers.calculate_sigmas(
        model.get_model_object("model_sampling"), scheduler, total_steps).cpu()
    return sigmas[-(steps + 1):]


class DeciiaSamplerPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSamplerPreset",
            display_name="Deiia 采样预设 · 采样器+调度器",
            category="Deciia/local",
            description=(
                "采样设置预设：兼容单采 / T8双采 / selflift-Avatar 等场景，"
                "每个预设含一采与二采两组参数（采样器/调度器/步数/去噪）。"
                "输出一采/二采 Sigmas 与采样器方案，Sigmas 算法与内核 BasicScheduler 一致。"
            ),
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler",
                               tooltip="一采采样器（预设切换时自动同步）。"),
                io.Combo.Input("scheduler", options=comfy.samplers.SCHEDULER_NAMES, default="beta",
                               tooltip="一采调度器。"),
                io.Int.Input("steps", default=6, min=1, max=10000, tooltip="一采总步数。"),
                io.Float.Input("denoise", default=1.0, min=0.0, max=1.0, step=0.01,
                               tooltip="一采去噪强度（<1.0 按内核规则折算步数）。"),
                io.Combo.Input("p2_sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler", advanced=True,
                               tooltip="二采采样器。"),
                io.Combo.Input("p2_scheduler", options=comfy.samplers.SCHEDULER_NAMES, default="beta", advanced=True,
                               tooltip="二采调度器。"),
                io.Int.Input("p2_steps", default=4, min=1, max=10000, advanced=True, tooltip="二采总步数。"),
                io.Float.Input("p2_denoise", default=1.0, min=0.0, max=1.0, step=0.01, advanced=True,
                               tooltip="二采去噪强度。"),
                io.String.Input("presets_json", default=json.dumps(_DEFAULT_PRESETS, ensure_ascii=False),
                                multiline=True, advanced=True,
                                tooltip="预设数据（前端 ⚙ 菜单自动维护，一般不用手改）。"),
            ],
            outputs=[
                io.Sigmas.Output(display_name="一采Sigmas"),
                io.Sigmas.Output(display_name="二采Sigmas"),
                io.Sampler.Output(display_name="一采采样器方案"),
                io.Sampler.Output(display_name="二采采样器方案"),
            ],
        )

    @classmethod
    def execute(cls, model, sampler_name, scheduler, steps, denoise,
                p2_sampler_name, p2_scheduler, p2_steps, p2_denoise, presets_json="") -> io.NodeOutput:
        sigmas1 = _sigmas_for(model, sampler_name, scheduler, steps, denoise)
        sigmas2 = _sigmas_for(model, p2_sampler_name, p2_scheduler, p2_steps, p2_denoise)
        sampler1 = comfy.samplers.sampler_object(sampler_name)
        sampler2 = comfy.samplers.sampler_object(p2_sampler_name)
        import torch
        s1 = sigmas1 if sigmas1 is not None else torch.FloatTensor([])
        s2 = sigmas2 if sigmas2 is not None else torch.FloatTensor([])
        return io.NodeOutput(s1, s2, sampler1, sampler2)


NODE_CLASS_MAPPINGS["DeciiaSamplerPreset"] = DeciiaSamplerPreset
NODE_DISPLAY_NAME_MAPPINGS["DeciiaSamplerPreset"] = "Deiia 采样预设 · 采样器+调度器"
