# -*- coding: utf-8 -*-
"""Deiia 采样预设 · 采样器+调度器（v3：用户真实分组版）。

输入模型，按当前预设输出 Sigmas 与采样器方案。多预设按分组管理
（分组对齐用户真实场景：H3无损融合单采 / T8双采 / YZ金鱼Selflift双采 / selflift-Avatar）。
支持每预设自定义 Sigma 阶梯（custom_sigmas，逗号分隔，非空时优先输出）。
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
    "current": "H3无损融合单采/一采采样和调度",
    "presets": [
        {"name": "一采采样和调度", "group": "H3无损融合单采",
         "sampler_name": "euler", "scheduler": "beta", "steps": 6, "denoise": 1.0, "custom_sigmas": ""},
        {"name": "一采采样和调度", "group": "T8双采",
         "sampler_name": "euler", "scheduler": "beta", "steps": 4, "denoise": 1.0, "custom_sigmas": ""},
        {"name": "二采采样和调度", "group": "T8双采",
         "sampler_name": "euler", "scheduler": "beta", "steps": 4, "denoise": 1.0, "custom_sigmas": ""},
        {"name": "一采采样和调度", "group": "YZ金鱼Selflift双采",
         "sampler_name": "euler", "scheduler": "beta", "steps": 6, "denoise": 1.0, "custom_sigmas": ""},
        {"name": "二采采样和调度", "group": "YZ金鱼Selflift双采",
         "sampler_name": "euler", "scheduler": "beta", "steps": 4, "denoise": 1.0, "custom_sigmas": ""},
        {"name": "采样", "group": "selflift-Avatar",
         "sampler_name": "euler", "scheduler": "beta", "steps": 6, "denoise": 1.0, "custom_sigmas": ""},
    ],
}


class DeciiaSamplerPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSamplerPreset",
            display_name="Deiia 采样预设 · 采样器+调度器",
            category="Deciia/local",
            description=(
                "采样设置预设：按分组管理（H3无损融合单采 / T8双采 / YZ金鱼Selflift双采 / selflift-Avatar…），"
                "每组内可建多个预设（如 一采采样和调度 / 二采采样和调度）。"
                "输出 Sigmas 与采样器方案；Sigmas 算法与内核 BasicScheduler 一致，"
                "预设里填了 custom_sigmas 时优先输出自定义阶梯。"
            ),
            inputs=[
                io.Model.Input("model"),
                io.Combo.Input("sampler_name", options=comfy.samplers.SAMPLER_NAMES, default="euler",
                               tooltip="采样器方案（预设切换时自动同步）。"),
                io.Combo.Input("scheduler", options=comfy.samplers.SCHEDULER_NAMES, default="beta",
                               tooltip="调度器。"),
                io.Int.Input("steps", default=6, min=1, max=10000, tooltip="总步数。"),
                io.Float.Input("denoise", default=1.0, min=0.0, max=1.0, step=0.01,
                               tooltip="去噪强度（<1.0 按内核规则折算步数）。"),
                io.String.Input("custom_sigmas", default="", advanced=True, multiline=True,
                                tooltip="自定义 Sigma 阶梯：逗号分隔的数值（降序，含末位 0），"
                                        "非空时优先于调度器/步数计算。如 '14.61,3.2,1.0,0'。"),
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
    def execute(cls, model, sampler_name, scheduler, steps, denoise,
                custom_sigmas="", presets_json="") -> io.NodeOutput:
        sampler = comfy.samplers.sampler_object(sampler_name)

        raw = (custom_sigmas or "").strip()
        if raw:
            vals = [float(x) for x in raw.replace("，", ",").replace("，", ",").split(",") if x.strip()]
            if vals:
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
