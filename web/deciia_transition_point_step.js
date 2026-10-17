/* ===== Deciia 过渡点：加减号步进自适应（2026-10-17）=====================
   多轨项目节点的「过渡点」是双语义控件：
     0~1  = 比例（低清 NFE 占比）
     >=1  = 步数（低清评估次数）
   前端 FLOAT 控件只有一个固定 step，这里在值变化时动态改写 widget.options.step，
   使 +/- 步进符合直觉：<1 时 0.05（比例细调），>=1 时 1（步数整跳）。
   设计约束：不做 DOM 注入、不加定时器、只包一层 callback；异常一律吞掉并告警，
   保证即使前端改版也只会退化成「步进不变」，不会让节点或页面崩。
   回滚：删除本文件并刷新页面。
   ====================================================================== */
import { app } from "/scripts/app.js";

const TARGET_NODE = "easy multitrackProject";
// 兼容旧控件名（若某工作流仍是旧 schema）
const TARGET_WIDGETS = ["transition_point", "transition_step"];
const RATIO_STEP = 0.05;
const STEP_STEP = 1;

function patchWidget(node) {
    try {
        if (!node || !Array.isArray(node.widgets)) return;
        for (const name of TARGET_WIDGETS) {
            const w = node.widgets.find((x) => x && x.name === name);
            if (!w || w.__deciiaAdaptiveStep) continue;

            const sync = () => {
                const v = Number(w.value);
                w.options = w.options || {};
                w.options.step = Number.isFinite(v) && v >= 1 ? STEP_STEP : RATIO_STEP;
            };

            const original = w.callback;
            w.callback = function (...args) {
                const result = typeof original === "function" ? original.apply(this, args) : undefined;
                sync();
                return result;
            };

            w.__deciiaAdaptiveStep = true;
            sync();
        }
    } catch (error) {
        console.warn("[Deciia] 过渡点步进自适应未生效（已忽略）：", error);
    }
}

app.registerExtension({
    name: "Deciia.TransitionPointAdaptiveStep",
    nodeCreated(node) {
        const type = node && (node.comfyClass || node.type);
        if (type !== TARGET_NODE) return;
        patchWidget(node);
        // DynamicCombo 切换采样模式会重建子控件，节点高度变化时再补一次
        const originalResize = node.onResize;
        node.onResize = function (...args) {
            const result = typeof originalResize === "function" ? originalResize.apply(this, args) : undefined;
            patchWidget(node);
            return result;
        };
    },
});
/* ===== End Deciia 过渡点步进自适应 ===== */
