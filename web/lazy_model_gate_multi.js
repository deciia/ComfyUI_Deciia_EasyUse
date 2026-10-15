/**
 * Lazy 模型门控·主路旁路 前端（2026-10-01 rev5）。
 *
 * 固定三口：主路(入) + 旁路(入,可不接) + 出口(出)。无自动增长。
 * 只做 legacy 清理：rev2~rev4 的多通路旧节点实例打开时，把多余的
 * 数据K/旁路K/原始数据K 输入口与多余出口删掉（保号最小的那组，
 * 连线保留在保留口上，其余连线断开——旧布局本就要重摆）。
 */
import { app } from "../../scripts/app.js";

const NODE_NAME = "LazyModelGateMulti";

app.registerExtension({
  name: "deciia_local.lazy_model_gate_multi",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;

    const cleanup = (node) => {
      try {
        // 删 rev2~rev4 遗留的编号口（数据K/旁路K/原始数据K），只留一个 主路
        const dropNames = [];
        let firstDataKept = false;
        for (const input of [...(node.inputs || [])]) {
          const n = String(input?.name || "");
          if (/^(数据|旁路|原始数据)\d+$/.test(n)) {
            if (!firstDataKept && n.startsWith("数据")) {
              // 第一个 数据K 原地改名 主路（保住连线）
              input.name = "主路";
              firstDataKept = true;
            } else {
              dropNames.push(input);
            }
          }
          // 第一个 旁路K 改名 旁路
        }
        let firstBypassKept = false;
        for (const input of [...(node.inputs || [])]) {
          const n = String(input?.name || "");
          if (/^旁路\d+$/.test(n)) {
            if (!firstBypassKept) { input.name = "旁路"; firstBypassKept = true; }
            else dropNames.push(input);
          }
        }
        for (const input of dropNames) {
          if (input.link != null) {
            try { node.graph?.removeLink(input.link); } catch (e) {}
          }
          node.removeInput(node.inputs.indexOf(input));
        }
        // 出口：保留前两个，改名 主路出口/旁路出口
        const outs = (node.outputs || []).filter((o) => /^出口\d+$/.test(String(o?.name || "")));
        const NAMES = ["主路出口", "旁路出口"];
        outs.forEach((o, i) => {
          if (i < 2) { o.name = NAMES[i]; }
          else {
            if (o.links && o.links.length) { for (const lid of [...o.links]) { try { node.graph?.removeLink(lid); } catch (e) {} } }
            node.removeOutput(node.outputs.indexOf(o));
          }
        });
        node.computeSize?.();
        node.setDirtyCanvas?.(true, true);
      } catch (e) { console.error("[模型门控] legacy清理", e); }
    };

    const updateConnWidget = (node) => {
      try {
        const mainUsed = (node.outputs?.[0]?.links || []).length > 0;
        const bypassUsed = (node.outputs?.[1]?.links || []).length > 0;
        const val = `主路出口:${mainUsed ? 1 : 0},旁路出口:${bypassUsed ? 1 : 0}`;
        // 只认后端物化的 widget，绝不自建（自建会挤到本链模型前面 → 切页后值错位）
        const w = (node.widgets || []).find((x) => x?.name === "出口连线");
        if (w && w.value !== val) {
          w.value = val;
        }
        // canvas 绘制的 text widget 不认 hidden 标志 —— 用 vramsafe 同款
        // 零尺寸方案真正藏住（computeSize 0 + draw/mouse noop）
        if (w) {
          w.hidden = true;
          w.type = "hidden";
          w.computeSize = () => [0, 0];
          w.draw = () => {};
          w.mouse = () => {};
          try { w.element && (w.element.style.display = "none"); } catch (e) {}
        }
        node.computeSize?.();
      } catch (e) {}
    };

    const origConnChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
      const r = origConnChange?.apply(this, arguments);
      updateConnWidget(this);
      return r;
    };
    const origSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (o) {
      const r = origSerialize?.apply(this, arguments);
      try {
        // hidden widget 会被前端序列化跳过 —— 强制写回 widgets_values
        const mainUsed = (this.outputs?.[0]?.links || []).length > 0;
        const bypassUsed = (this.outputs?.[1]?.links || []).length > 0;
        const val = `主路出口:${mainUsed ? 1 : 0},旁路出口:${bypassUsed ? 1 : 0}`;
        const names = (this.widgets || []).map((w) => w?.name);
        const idx = names.indexOf("出口连线");
        if (idx >= 0 && Array.isArray(o.widgets_values)) {
          o.widgets_values[idx] = val; // widget 存在才写，且实时读 outputs.links
        }
      } catch (e) {}
      return r;
    };

    const origConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      const r = origConfigure?.apply(this, arguments);
      // 标签页切换/工作流加载时 widget 物化时机不定 — 轮询守卫反复隐藏
      let tries = 0;
      const guard = () => {
        try {
          cleanup(this);
          updateConnWidget(this);
        } catch (e) {}
        if (++tries < 20) setTimeout(guard, 500);
      };
      setTimeout(guard, 50);
      return r;
    };
    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = origCreated?.apply(this, arguments);
      setTimeout(() => { cleanup(this); updateConnWidget(this); }, 20);
      return r;
    };
  },
});
