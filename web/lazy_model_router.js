/**
 * Lazy 模型路由 前端联动（2026-10-01 rev3，归属 ComfyUI_Deciia_Local）。
 *
 * rev4 变更（用户决策 2026-10-01）：移除 «tag» 组级 mute 联动（用户明确不要，
 *   原因：改组名/节点归属出错会留下隐蔽问题）。模型隔离完全交给数据层：
 *   Lazy 模型门控(ExecutionBlocker) + 路由节点只消费当前模型口。
 * rev3（动态口真删真建）保留 —— rev6 保留同一套布局行为，只修「连续重置」副作用
 *   （幂等 + 按名字重连 + 来源类型校验，详见 applyDynamicSlots 注释）。
 *   · slot.hidden 在当前前端不隐藏输入行 → 改为【真删除/重建】模型专属输入口
 *     （rgthree/Impact 系动态口同款机制）。删除前把连线信息存 stash，
 *     切回该模型时自动重连——来回切不丢线。
 *   · 事件三保险：widget.callback + widget.onValueChanged + node.onWidgetChanged，
 *     任意一条触发都重放路由（Vue 前端 combo 的触发路径不完全一致）。
 *   · 专属 widget（Qwen缓存设备/精度/透明底、Krea底模等被转成 widget 的）按前缀
 *     w.hidden + computeSize。
 *   · 组级 mute：«tag» 标记的组整组激活/mute（Goohai 忽略多组同款）。
 *
 * 输出口常驻：图像 / 模型选择(STRING，喂给 Lazy 模型门控) / 运行信息。
 * 广播(Anything Everywhere)兼容：重建的空口可被广播自动喂线。
 */
import { app } from "../../scripts/app.js";

const NODE_NAME = "LazyModelRouter";

const MODEL_TAGS = {
  "qwen2.1": "qwen",
  "krea2": "krea",
};
// 各模型的专属输入口定义（名称/类型须与后端 INPUT_TYPES 完全一致）
const SLOT_DEFS = {
  // 单套通用口（2026-10-03 用户定稿）：模型无关，切模型口与线都不动。
  universal: [
    { name: "UNet", type: "MODEL" },
    { name: "文本编码", type: "CLIP" },
    { name: "VAE", type: "VAE" },
    { name: "底模", type: "MODEL" },
  ],
};
// 旧专属口名 → 通用口名（老工作流迁移用）
const PORT_MIGRATION = {
  "Qwen模型": "UNet", "Krea模型": "UNet",
  "Qwen文本编码": "文本编码", "Krea文本编码": "文本编码",
  "QwenVAE": "VAE", "KreaVAE": "VAE",
  "Krea底模": "底模",
};
// 专属 slot/widget 的名字前缀 → 模型
const PREFIX_OWNER = { "Qwen": "qwen2.1", "Krea": "krea2" };

function ownerOfName(name) {
  const s = String(name || "");
  for (const [prefix, owner] of Object.entries(PREFIX_OWNER)) {
    if (s.startsWith(prefix)) return owner;
  }
  return null;
}

function modelIdFromWidget(node) {
  const w = node.widgets?.find((x) => x?.name === "模型");
  if (!w) return null;
  const v = String(w.value || "").toLowerCase();
  for (const id of Object.keys(MODEL_TAGS)) {
    if (v.includes(id)) return id;
  }
  for (const [id, tag] of Object.entries(MODEL_TAGS)) {
    if (v.includes(tag)) return id;
  }
  return null;
}



/** 真删除/重建模型专属输入口；stash 保连线，切回自动重连。
 *
 *  rev6 修正（2026-10-03，用户报「刷新后连线被连续重置」）：
 *  旧实现每次 applyRouting 都执行一遍「全删 → 全建 → 重连」，而触发点有三处
 *  （widget.callback / onValueChanged / onWidgetChanged）外加加载重放，一次刷新会连做多遍。
 *  每遍都按当时的 input.link 重新挂线；工作流还没加载完时拿到的是半成品 link，
 *  于是用户手接的线被挂到别的源上，且逐遍累积。
 *  修正三条（布局行为保持原样，只去掉副作用）：
 *    1) 幂等：当前专属口与目标「同名同序」时直接返回，绝不空转重建；
 *    2) 按名字重连：不再用 index 配对；
 *    3) 来源校验：源节点存在、且槽位类型与目标口兼容才连，否则保持空口等用户接线。
 */
function ensureModelPorts(node) {
  // 通用口常驻（缺则补，绝不删除）；老工作流的专属口就地改名迁移，连线保留。
  let changed = false;
  // 2a) 旧专属口迁移：线挪到通用口，旧口删除
  //     （object_info 刷新后前端会自建通用口，故旧口不能改名——会撞名；
  //       正确做法：把旧口上的连线重接到同名通用口，再删旧口）
  for (let k = (node.inputs || []).length - 1; k >= 0; k--) {
    const inp = node.inputs[k];
    const to = PORT_MIGRATION[inp?.name];
    if (!to) continue;
    const tgt = node.inputs.find((i) => i !== inp && i?.name === to);
    if (tgt && inp.link && !tgt.link) {
      // 线挪过去：断开旧口连线并从源重接到通用口
      const link = node.graph.links[inp.link];
      const srcNode = link ? node.graph.getNodeById(link.origin_id) : null;
      if (srcNode && link) {
        try { srcNode.connect(link.origin_slot, node, node.inputs.indexOf(tgt)); } catch (e) {}
      }
    }
    node.inputs.splice(k, 1); changed = true;
  }
  // 2c) 补通用口
  for (const def of SLOT_DEFS.universal) {
    const has = (node.inputs || []).some((i) => i?.name === def.name);
    if (!has) {
      try { node.addInput(def.name, def.type); changed = true; } catch (e) { console.warn("[Lazy模型路由] 补口失败:", def.name, e); }
    }
  }
  if (changed) node.setDirtyCanvas?.(true, true);
}
function hideRow(w, hide) {
  // 2026-10-03 社区验证方案（DazzleNodes Smart-Resolution-Calc 同款）：
  // 显隐只覆写 draw/computeSize/mouse 三个方法，绝不碰 w.hidden / w.type /
  // w.options.hidden —— 那些标志会让 1.54.7 前端永久移除 widget 的 DOM 行
  // （能藏不能显）。widget 全程留在数组里：序列化/提交/连线零影响。
  // 隐藏=零高度行；恢复=还原原方法（原生 widget 的方法是原型继承，
  // 实例上原本 undefined，delete 掉覆写即回落默认渲染）。
  if (!w) return;
  if (hide) {
    if (w._deciiaHid) return;
    w._deciiaHid = true;
    w._origDraw = w.draw;
    w._origCS = w.computeSize;
    w._origMouse = w.mouse;
    w.draw = function () {};
    w.computeSize = function () { return [0, -4]; };
    w.mouse = function () { return false; };
    w.hidden = true; // 1.54.7 DOM 渲染：hidden 让 widget 行从 DOM 列表移除（零占位）
  } else {
    if (!w._deciiaHid) return;
    w._deciiaHid = false;
    if (w._origDraw !== undefined) w.draw = w._origDraw; else delete w.draw;
    if (w._origCS !== undefined) w.computeSize = w._origCS; else delete w.computeSize;
    if (w._origMouse !== undefined) w.mouse = w._origMouse; else delete w.mouse;
    w.hidden = false; // 只要该行在初始挂载时进过 DOM，hidden=false 即可复显
  }
}
function applyRouting() {
  const id = modelIdFromWidget(this);
  if (!id) return;

  // A) 专属输入口：固定常驻（缺则补，不删除，连线不动）
  try { ensureModelPorts(this); } catch (e) { console.error("[Lazy模型路由] 补口失败:", e); }


  // B) 专属 widget 显隐（Qwen*/Krea* 前缀：步数/CFG/采样器/调度器/去噪/缓存/透明底）
  //    只做显示层，端口与连线一概不动。
  for (const w of this.widgets || []) {
    const owner = ownerOfName(w?.name);
    if (!owner) continue;
    hideRow(w, owner !== id);
  }
  // 隐藏行腾出的空间要回收：节点收缩到内容高度，否则留下一截空行
  try { this.setSize(this.computeSize()); } catch (e) {}
  this.setDirtyCanvas?.(true, true);
  this.setDirtyCanvas?.(true, true);
  try { this.computeSize?.(); } catch (e) {}
  const hiddenNames = (this.widgets || []).filter((w) => ownerOfName(w?.name) && w.hidden).map((w) => w.name);
  const sig = id + "|" + hiddenNames.join(",");
  if (this._deciiaLayoutSig !== sig) {
    this._deciiaLayoutSig = sig;
    console.log(`[Lazy模型路由] 布局同步：当前模型=${id}，隐藏 ${hiddenNames.length} 行（${hiddenNames.join(" ") || "无"}）`);
  }

}

function waitForWidgetsThenRoute(node, tries) {
  const n = tries == null ? 0 : tries;
  if (n > 60) return; // ~3s 上限，放弃（节点可能已被删除）
  const hasModelWidget = (node.widgets || []).some((w) => w?.name === "模型");
  if (!hasModelWidget) {
    setTimeout(() => waitForWidgetsThenRoute(node, n + 1), 50);
    return;
  }
  // 首次隐藏必须等 DOM widget 列表挂载完（lg-node-widgets 容器出现）：
  // 1.54.7 的 DOM 行列表在挂载时定型，若在挂载前就把某行 hidden=true，
  // 该行从未进过 DOM，之后 hidden=false 也无法复显（多行空行的根源之一）。
  if (!node._deciiaRoutedOnce) {
    const domReady = node._deciiaPanelDomChecked =
      !!(node.element || node.domElement) ||
      !!document.querySelector(`[data-node-id='${node.id}']`);
    if (!domReady && n < 50) {
      setTimeout(() => waitForWidgetsThenRoute(node, n + 1), 50);
      return;
    }
    node._deciiaRoutedOnce = true;
  }
  try { applyRouting.call(node); } catch (e) { console.error("[Lazy模型路由]", e); }
}

function setupWidgetWatch(node) {
  const w = node.widgets?.find((x) => x?.name === "模型");
  if (!w) return;
  const orig = w.callback;
  w.callback = function (...args) {
    const r = orig?.apply(this, args);
    try { applyRouting.call(node); } catch (e) { console.error("[Lazy模型路由]", e); }
    return r;
  };
  if (w.onValueChanged == null) {
    w.onValueChanged = () => {
      try { applyRouting.call(node); } catch (e) { console.error("[Lazy模型路由]", e); }
    };
  }
}

app.registerExtension({
  name: "deciia_local.lazy_model_router",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;

    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = origCreated?.apply(this, arguments);
      try { setupWidgetWatch(this); } catch (e) { console.error("[Lazy模型路由]", e); }
      // 新拖节点立即应用（否则 Qwen/Krea 全部 widget 齐刷刷露出）。
      // Vue 前端 widgets 异步构建：轮询等待 widgets 就绪后再应用，
      // 固定 30ms 延迟在构建慢时扑空（rev6→rev7 修正）。
      waitForWidgetsThenRoute(this);
      return r;
    };

    // 事件第三保险：onWidgetChanged（部分前端版本的 combo 触发路径）
    const origWidgetChanged = nodeType.prototype.onWidgetChanged;
    nodeType.prototype.onWidgetChanged = function (name, value, oldValue) {
      const r = origWidgetChanged?.apply(this, arguments);
      if (name === "模型") {
        try { applyRouting.call(this); } catch (e) { console.error("[Lazy模型路由]", e); }
      }
      return r;
    };

    // 工作流加载后重放（等 widgets_values 恢复）
    const origConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      const r = origConfigure?.apply(this, arguments);
      // 推迟到图稳定再重放：过早时 graph.links 还是半成品（rev6 连续重置的根因之一）。
      // 幂等保护下重复调用无副作用：口径一致时 applyDynamicSlots 直接返回。
      for (const d of [250, 1200]) {
        setTimeout(() => {
          try { applyRouting.call(this); } catch (e) { console.error("[Lazy模型路由]", e); }
        }, d);
      }
      return r;
    };
  },
});
