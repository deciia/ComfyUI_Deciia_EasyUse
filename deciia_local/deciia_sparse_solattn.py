# -*- coding: utf-8 -*-
"""Deiia 稀疏注意力（DeciiaSparseSolAttn）——四方法注意力预设节点 v3。

零内核重复实现，全部委托上游本体：
- sol-attn   → 委托 Patch Sol-Attn (MiniMax) 插件本体
               (comfyui-minimax-h3-audio-T8/sol_attn_minimax_v2.py 的
               SolAttnMiniMax._apply_patch)，参数集与其 UI 逐项 1:1 对齐
               （含 morton / morton_curve / centroid_tail / routed_cap_percent /
               reuse_qkv_memory / tau_profile），默认值 = P3a #88 在用值；
- sla / vsa  → 官方 comfy_extras/nodes_sparse_attention.py 的
               apply_block_sparse_attention()（keep_percent 官方默认 10）；
- spark_sm120 → 按路径懒加载 ComfyUI-Spark-H3 的
               MiniMaxH3SparkAttentionSM120 并委托其 patch()（默认 = P3a #137）。

互斥纪律：同一 MODEL 链上注意力补丁只能挂一个。
"""

import os
import sys

from comfy_api.latest import io

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_SPARK_DIR = r"D:\ComfyUI-aki\ComfyUI-aki-v3.2\ComfyUI\custom_nodes\ComfyUI-Spark-H3"
_SOLATTN_PATH = (r"D:\ComfyUI-aki\ComfyUI-aki-v3.2\ComfyUI\custom_nodes"
                 r"\comfyui-minimax-h3-audio-T8\sol_attn_minimax_v2.py")
_cache = {}


def _load_by_path(mod_name, path):
    if mod_name in _cache:
        return _cache[mod_name]
    import importlib.util
    if not os.path.isfile(path):
        raise RuntimeError("找不到插件文件: " + path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _cache[mod_name] = mod
    return mod


def _load_spark_class():
    if "spark_cls" in _cache:
        return _cache["spark_cls"]
    if _SPARK_DIR not in sys.path:
        sys.path.insert(0, _SPARK_DIR)   # 其 fallback 绝对导入依赖它
    mod = _load_by_path("deciia_spark_h3_nodes", os.path.join(_SPARK_DIR, "comfyui_nodes.py"))
    cls = getattr(mod, "MiniMaxH3SparkAttentionSM120")
    _cache["spark_cls"] = cls
    return cls


def _load_solattn_mod():
    return _load_by_path("deciia_sol_attn_minimax_v2", _SOLATTN_PATH)


class DeciiaSparseSolAttn(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DeciiaSparseSolAttn",
            display_name="Deiia 稀疏注意力 · 四方法预设",
            category="Deciia/local",
            is_experimental=True,
            description=(
                "四方法注意力预设。sol-attn 档委托 Patch Sol-Attn (MiniMax) 插件本体，"
                "参数逐项 1:1 对齐（默认值 = P3a #88 在用值）；"
                "sla/vsa 走官方模型稀疏注意力入口；spark_sm120 委托 Spark-H3 插件本体。"
                "互斥纪律：同一 MODEL 链上只能挂一个注意力补丁。"
            ),
            inputs=[
                io.Model.Input("model", tooltip="接在模型加载/LoRA 之后、采样器之前。"),
                io.DynamicCombo.Input("method", display_name="method", options=[
                    # ---- sol-attn：与 Patch Sol-Attn (MiniMax) 参数逐项对齐 ----
                    io.DynamicCombo.Option("sol-attn", [
                        io.Float.Input("tau", default=1.3, min=0.0, max=4.0, step=0.05,
                                       tooltip="阈值 β。越大越稀疏：1.0≈16% 块保留精确，1.5≈7%，2.0≈2.7%。默认 1.3 = P3a 在用值。"),
                        io.Float.Input("start_percent", default=0.2, min=0.0, max=1.0, step=0.01,
                                       tooltip="在此之前保持稠密。论文用 0.2。"),
                        io.Float.Input("end_percent", default=0.9, min=0.0, max=1.0, step=0.01,
                                       tooltip="在此之后回到稠密。默认 0.9 = P3a 在用值。"),
                        io.Int.Input("min_tokens", default=12288, min=0, max=1048576, step=512,
                                     tooltip="短于该 token 数的序列保持稠密。"),
                        io.Combo.Input("sink_conditioning",
                                       options=["exact_kv", "exact_kv_and_rows", "off"],
                                       default="exact_kv_and_rows",
                                       tooltip="exact_kv：每条 query 精确看到打包的文本/音频/参考行（约 3% 开销）；exact_kv_and_rows：再把目标音频 query 行跑稠密（保住生成音频）。"),
                        io.Boolean.Input("morton", default=False, advanced=True,
                                         tooltip="把视频 token 重排为 Morton（Z 序），使每个 64-token 块是紧凑的 3D 邻域。对稠密注意力完全中性。"),
                        io.Combo.Input("morton_curve", options=["3d", "2d_frame"],
                                       default="2d_frame", advanced=True,
                                       tooltip="2d_frame：帧内 Z 序、帧顺序不变——适配 H3 的非均匀时间轴。"),
                        io.Boolean.Input("centroid_tail", default=True, advanced=True,
                                         tooltip="每 64-token query 块在其质心求一次池化分支而非逐行计算，约快 1.4 倍；质量 A/B 时请关闭。"),
                        io.Int.Input("routed_cap_percent", default=0, min=0, max=100, step=5,
                                     advanced=True,
                                     tooltip="路由块列表上限（占序列 %）；0=不设限。tau=1.4 时 ~30 即 3 倍余量且实测无损。"),
                        io.Boolean.Input("reuse_qkv_memory", default=False, advanced=True,
                                         tooltip="把注意力输出写入模型融合的 qkv 缓冲，峰值显存少约一个输出尺寸张量。对 MiniMax-H3 安全。"),
                        io.Boolean.Input("verbose", default=False, advanced=True,
                                         tooltip="日志打印每次注意力走稀疏还是稠密及原因。"),
                        io.String.Input("tau_profile", default="", optional=True, force_input=True, advanced=True,
                                        tooltip="逐块 tau 覆盖基础值。多条 '块号=tau' 用 ';' 或换行分隔。作为可选输入槽暴露，可外接字符串。"),
                        io.String.Input("dense_blocks", default="", advanced=True,
                                        tooltip="保持稠密的 Transformer 块，如 '0-2,-1'。首尾块对近似最敏感。"),
                    ]),
                    # ---- sla：官方模型稀疏注意力入口 ----
                    io.DynamicCombo.Option("sla", [
                        io.Float.Input("keep_percent", default=10.0, min=0.5, max=95.0, step=0.5,
                                       tooltip="每个 query 块精确保留的 key 比例（%）。SLA 蒸馏 LoRA 在 10 训练；无蒸馏权重时越高越接近稠密。等价换算：班长的「省多少计算」90 = 这里的 10。"),
                        io.DynamicCombo.Input("sla_dense_mode", display_name="dense_mode", options=[
                            io.DynamicCombo.Option("percent", [
                                io.Float.Input("start_percent", default=0.2, min=0.0, max=1.0, step=0.01,
                                               tooltip="在此之前保持稠密。"),
                                io.Float.Input("end_percent", default=1.0, min=0.0, max=1.0, step=0.01,
                                               tooltip="在此之后回到稠密。"),
                            ]),
                            io.DynamicCombo.Option("steps", [
                                io.Int.Input("sla_dense_first_steps", default=2, min=0, max=8, step=1,
                                             tooltip="开头这几步保持稠密（构图与人物长相靠它们，完整算画面更稳）。"),
                                io.Int.Input("sla_dense_last_steps", default=0, min=0, max=8, step=1,
                                             tooltip="最后这几步用完整计算收尾，画面更稳更细，代价是慢一点。"),
                                io.Int.Input("sla_steps", default=8, min=1, max=200, step=1,
                                             tooltip="本次采样链的模型评估总次数——必须填实际次数。"),
                            ]),
                        ], tooltip="稠密窗口表示法：percent 按百分比窗口；steps 按步数（照班长 SLA 的习惯，对 4/8 步 turbo 采样更直观）。"),
                        io.Int.Input("min_tokens", default=12288, min=0, max=1048576, step=512,
                                     tooltip="短于该 token 数的序列保持稠密。"),
                        io.Combo.Input("sink_conditioning",
                                       options=["exact_kv", "exact_kv_and_rows", "off"],
                                       default="exact_kv_and_rows",
                                       tooltip="MiniMax-H3 的 conditioning sink 策略。"),
                        io.String.Input("dense_blocks", default="", advanced=True,
                                        tooltip="保持稠密的块，如 '0, 1, 47-49'。"),
                        io.Int.Input("extra_tokens", default=256, min=0, max=256, step=64, advanced=True,
                                     tooltip="每 query 块额外精看的 top token 数；官方推荐 256。"),
                        io.Boolean.Input("verbose", default=False, advanced=True,
                                         tooltip="日志打印稀疏/稠密决策。"),
                    ]),
                    # ---- vsa：官方模型稀疏注意力入口 ----
                    io.DynamicCombo.Option("vsa", [
                        io.Float.Input("keep_percent", default=10.0, min=0.5, max=95.0, step=0.5,
                                       tooltip="每个视频立方精确保留比例（%）。FastH3-VSA 权重在 10 训练；需要 MiniMax-H3 模型与 to_gate_compress 层。"),
                        io.Float.Input("start_percent", default=0.2, min=0.0, max=1.0, step=0.01,
                                       tooltip="在此之前保持稠密。"),
                        io.Float.Input("end_percent", default=1.0, min=0.0, max=1.0, step=0.01,
                                       tooltip="在此之后回到稠密。"),
                        io.Int.Input("min_tokens", default=12288, min=0, max=1048576, step=512,
                                     tooltip="短于该 token 数的序列保持稠密。"),
                        io.Combo.Input("sink_conditioning",
                                       options=["exact_kv", "exact_kv_and_rows", "off"],
                                       default="exact_kv_and_rows",
                                       tooltip="MiniMax-H3 的 conditioning sink 策略。"),
                        io.String.Input("dense_blocks", default="", advanced=True,
                                        tooltip="保持稠密的块，如 '0, 1, 47-49'。"),
                        io.Boolean.Input("verbose", default=False, advanced=True,
                                         tooltip="日志打印稀疏/稠密决策。"),
                    ]),
                    # ---- spark_sm120：委托 Spark-H3 插件本体 ----
                    io.DynamicCombo.Option("spark_sm120", [
                        io.Int.Input("spark_steps", default=8, min=1, max=200, step=1,
                                     tooltip="本次采样链的模型评估总次数——必须填实际次数，它驱动 Spark 的预热与门控时序。默认 8 = P3a #137 在用值。"),
                        io.Float.Input("spark_warmup_ratio", default=0.25, min=0.0, max=1.0, step=0.01,
                                       tooltip="开头保持 dense 的调用比例。默认 0.25 = P3a #137 在用值。"),
                        io.Float.Input("spark_topk_ratio", default=0.2, min=0.01, max=1.0, step=0.01,
                                       tooltip="精确计算的候选块比例（0.1 最快 / 0.3 最保真）。默认 0.2 = P3a #137 在用值。"),
                        io.Int.Input("spark_min_tokens", default=12288, min=256, max=262144, step=256,
                                     advanced=True,
                                     tooltip="短序列保持 dense 的阈值。默认 12288 = P3a #137 在用值。"),
                        io.Int.Input("spark_dense_layers", default=0, min=0, max=50, step=1,
                                     advanced=True,
                                     tooltip="始终 dense 的前 N 层。默认 0 = P3a #137 在用值。"),
                        io.Boolean.Input("spark_strict", default=True, advanced=True,
                                         tooltip="开启：不兼容输入直接报错；关闭：回退 dense 并记日志。默认 True = P3a #137 在用值。"),
                        io.Combo.Input("spark_tail_granularity", options=["query", "block"],
                                       default="query", advanced=True,
                                       tooltip="近似分支的 Q 粒度：query（默认）对应 sol-engine Sol，只下采样 K/V、保留逐条真实 Q；block 对应 ComfyUI Sol，Q 和 K/V 都按块下采样。精确分支仍使用真实 Q。"),
                        io.Combo.Input("spark_reblock_layout", options=["q_reuse_k", "independent"],
                                       default="q_reuse_k", advanced=True,
                                       tooltip="reblock 布局：q_reuse_k 只构造 K 侧布局并让 Q 复用，减少开销；independent 分别构造 Q/K 布局，用于兼容旧结果。"),
                    ]),
                ], tooltip="sol-attn：委托 Patch Sol-Attn (MiniMax) 本体（参数 1:1）；"
                           "sla/vsa：官方模型稀疏注意力入口；"
                           "spark_sm120：委托 Spark-H3 插件本体（RTX 50 系 Blackwell）。"),
                io.Boolean.Input("enabled", default=True,
                                 tooltip="总开关：关闭时原样返回模型（等于不加速），不需要 bypass 节点。"),
                io.Boolean.Input("fail_soft", default=True, advanced=True,
                                 tooltip="开启：注意力补丁挂载失败时打日志并按不加速继续出图（不中断长跑生成）；关闭：直接报错。参考班长 SLA 的容错设计，默认开启。"),
            ],
            outputs=[io.Model.Output(display_name="model")],
        )

    @classmethod
    def execute(cls, model, method, enabled=True, fail_soft=True, **kwargs) -> io.NodeOutput:
        # DynamicCombo 会把「{子控件名: 值, ..., 'method': 选中项}」整包作为
        # method 参数传入（与官方 BlockSparseAttention 的 selection 同构）。
        sel = method if isinstance(method, dict) else {"method": method, **kwargs}
        mode = sel.get("method")

        def g(k, d=None):
            return sel[k] if k in sel else kwargs.get(k, d)

        if not enabled:
            return io.NodeOutput(model)

        def _dispatch():
            if mode == "sol-attn":
                mod = _load_solattn_mod()
                out = mod._apply_patch(
                    model,
                    tau=float(g("tau", 1.3)),
                    start_percent=float(g("start_percent", 0.2)),
                    end_percent=float(g("end_percent", 0.9)),
                    min_tokens=int(g("min_tokens", 12288)),
                    sink_conditioning=g("sink_conditioning", "exact_kv_and_rows"),
                    morton=bool(g("morton", False)),
                    morton_curve=g("morton_curve", "2d_frame"),
                    dense_blocks=g("dense_blocks", "") or "",
                    verbose=bool(g("verbose", False)),
                    tau_profile=g("tau_profile") or "",
                    routed_cap_percent=int(g("routed_cap_percent", 0)),
                    centroid_tail=bool(g("centroid_tail", True)),
                    reuse_qkv_memory=bool(g("reuse_qkv_memory", False)),
                )
                return io.NodeOutput(_unwrap_model(out))
            if mode in ("sla", "vsa"):
                from comfy_extras.nodes_sparse_attention import (
                    apply_block_sparse_attention, parse_block_list)
                keep = float(g("keep_percent", 10.0))
                start = float(g("start_percent", 0.2))
                end = float(g("end_percent", 1.0))
                if mode == "sla":
                    # 嵌套 DynamicCombo：sla_dense_mode 可能是
                    # {'sla_dense_mode': 'percent'|'steps', ...子控件}，兼容字符串旧形状
                    sdm = g("sla_dense_mode", {})
                    if isinstance(sdm, dict):
                        dm = sdm.get("sla_dense_mode", "percent")
                        s_start = sdm.get("start_percent")
                        s_end = sdm.get("end_percent")
                        s_first = sdm.get("sla_dense_first_steps")
                        s_last = sdm.get("sla_dense_last_steps")
                        s_steps = sdm.get("sla_steps")
                    else:
                        dm, s_start, s_end = str(sdm or "percent"), None, None
                        s_first = s_last = s_steps = None
                    if dm == "steps":
                        S = int(s_steps or 8)
                        first = int(s_first or 0)
                        last = int(s_last or 0)
                        if S > 0:
                            start = min(1.0, first / S)
                            end = max(0.0, 1.0 - last / S)
                    else:
                        if s_start is not None:
                            start = float(s_start)
                        if s_end is not None:
                            end = float(s_end)
                return io.NodeOutput(apply_block_sparse_attention(
                    model,
                    tau=float(g("tau", 1.3)),
                    topk_ratio=keep / 100.0,
                    vsa=(mode == "vsa"),
                    start_percent=start,
                    end_percent=end,
                    min_tokens=int(g("min_tokens", 12288)),
                    dense_blocks=parse_block_list(g("dense_blocks", "") or ""),
                    sink_conditioning=g("sink_conditioning", "exact_kv_and_rows"),
                    extra_tokens=0 if mode == "vsa" else int(g("extra_tokens", 256)),
                    verbose=bool(g("verbose", False)),
                ))
            if mode == "spark_sm120":
                spark = _load_spark_class()
                return io.NodeOutput(spark().patch(
                    model,
                    enabled=True,
                    steps=int(g("spark_steps", 8)),
                    warmup_mode="warmup_ratio",
                    warmup_ratio=float(g("spark_warmup_ratio", 0.25)),
                    warmup_steps=2,
                    topk_mode="topk_ratio",
                    topk_ratio=float(g("spark_topk_ratio", 0.2)),
                    topk_blocks=228,
                    dense_layers=int(g("spark_dense_layers", 0)),
                    min_tokens=int(g("spark_min_tokens", 12288)),
                    strict=bool(g("spark_strict", True)),
                    tail_granularity=g("spark_tail_granularity", "query"),
                    reblock_layout=g("spark_reblock_layout", "q_reuse_k"),
                ))
            raise ValueError("未知 method: " + str(mode))

        if not fail_soft:
            return _dispatch()
        try:
            return _dispatch()
        except Exception:
            import logging
            logging.exception(
                "[DeciiaSparseSolAttn] 注意力补丁挂载失败，本次按不加速继续出图"
                "（fail_soft=True；要硬报错请关闭 fail_soft）。")
            return io.NodeOutput(model)


def _unwrap_model(out):
    """从上游 io.NodeOutput 里取出 MODEL（兼容不同字段命名）。"""
    res = getattr(out, "result", None)
    if res is None:
        res = getattr(out, "outputs", None)
    if isinstance(res, (tuple, list)):
        res = res[0] if res else None
    if res is None:
        raise RuntimeError("上游节点未返回 MODEL")
    return res


NODE_CLASS_MAPPINGS["DeciiaSparseSolAttn"] = DeciiaSparseSolAttn
NODE_DISPLAY_NAME_MAPPINGS["DeciiaSparseSolAttn"] = "Deiia 稀疏注意力 · 四方法预设"
