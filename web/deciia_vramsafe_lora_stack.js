/**
 * 🛡️ Deciia 显存安全 LoRA 串 v1（作者标记 deciia）
 * ============================================================
 * 班长面板 UX（banzhang_lora_loader v2.1）+ Deciia 方式列（v12 内核）合并。
 * 目标节点：DeciiaVramSafeLoraStack（后端 deciia_vramsafe_lora_stack.py）
 *
 * 每行：[启用勾选] [LoRA文件(Filter+文件夹树弹层)] [强度] [方式图标] [备注] [×删除]
 *   方式图标（点击展开列表，选中后只显示图标、悬浮出说明）：
 *           灰·层叠=标准（权重融合，默认）  绿·分流=旁路（前向叠加不改权重）
 *           蓝·调色板=风格（下游按风格屏蔽） 紫·人像=人物（始终保留）
 *   扩展：DVZ_MODES 加一条（图标/配色/说明） + 后端 MODE_TABLE 加一条
 * 底部：[＋ 添加 LoRA] [↑ 上移] [↓ 下移]（点行选中），最多 16 行
 * 面板行(on/file/strength/mode/note)整体序列化进「LoRA配置」STRING widget；
 * 「LoRA文件」「模型强度」兜底 widget 隐藏不删（扩展未加载时仍可单 LoRA 使用）。
 *
 * 方式判定纪律（2026-09-15 修正）：旁路按「变体」定，不按「加速类」一刀切。
 * ============================================================
 */
import { app } from "../../../scripts/app.js";

const NODE_NAME = "DeciiaVramSafeLoraStack";
console.log("[Deciia VramSafe LoRA] JS v20261001-3 (preset groups) 加载");
const MAX_ROWS = 16;
const MODE_STD = "标准";
const MODE_BYPASS = "旁路";
const MODE_STYLE = "风格";
const MODE_PERSON = "人物";

// ── 方式注册表（前端单一扩展点）──────────────────────────────────────────
// 加新类型：这里加一条 + 后端 MODE_TABLE 加一条。id 同时是写进配置 JSON 的值。
//   cls  : chip / 列表图标的配色类（与 .dvz-std/.dvz-bypass/... 对应）
//   icon : 14px 内联 SVG（stroke 用 currentColor，随配色走）
const DVZ_MODES = [
  { id: MODE_STD,    label: "标准", desc: "权重融合（默认）",                    cls: "dvz-std",
    icon: '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="M3 13l9 5 9-5"/>' },
  { id: MODE_BYPASS, label: "旁路", desc: "前向叠加，不改权重（量化基座变体）",   cls: "dvz-bypass",
    icon: '<path d="M12 20v-9"/><path d="M12 11 6 5"/><path d="M12 11l6-6"/>' },
  { id: MODE_STYLE,  label: "风格", desc: "选工作台风格时由下游自动屏蔽",         cls: "dvz-style",
    icon: '<circle cx="12" cy="12" r="8.5"/><circle cx="9" cy="10" r="1.2"/><circle cx="15" cy="10" r="1.2"/><circle cx="12" cy="15" r="1.2"/>' },
  { id: MODE_PERSON, label: "人物", desc: "始终保留（不被风格屏蔽）",             cls: "dvz-person",
    icon: '<circle cx="12" cy="8" r="3.6"/><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0"/>' },
];
const DVZ_MODE_MAP = Object.fromEntries(DVZ_MODES.map((m) => [m.id, m]));
function modeSVG(m, px) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
    + 'stroke-linecap="round" stroke-linejoin="round" style="width:' + px + 'px;height:' + px
    + 'px;display:block">' + m.icon + '</svg>';
}

// ── 样式注入（dvz- 前缀，不与班长 bzl- 冲突）────────────────
(function injectCss() {
  const ID = "dvz-lora-css";
  if (document.getElementById(ID)) return;
  const s = document.createElement("style");
  s.id = ID;
  s.textContent = `
.dvz-wrap{width:100%;padding:6px 10px 8px;box-sizing:border-box;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}
.dvz-row{display:flex;align-items:center;gap:6px;margin-bottom:6px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);border-radius:8px;padding:5px 7px;cursor:pointer}
.dvz-row.dvz-off{opacity:.42}
.dvz-row.dvz-sel{border-color:#4a9eff}
.dvz-row input[type="checkbox"]{width:15px;height:15px;accent-color:#4a9eff;cursor:pointer;flex-shrink:0;margin:0}
.dvz-row .dvz-file{flex:1.3;min-width:0;background:#22242a;color:#e8e8e8;border:1px solid #3a3d45;border-radius:6px;padding:4px 6px;font-size:12px;outline:none;cursor:pointer;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:inherit}
.dvz-row .dvz-file:hover{border-color:#4a9eff}
.dvz-pop{position:fixed;z-index:99999;background:#1c1e24;border:1px solid #3a3d45;border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.55);overflow:hidden;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}
.dvz-mask{position:fixed;inset:0;z-index:99998;background:transparent}
.dvz-filter{width:100%;box-sizing:border-box;background:#22242a;border:none;border-bottom:1px solid #3a3d45;color:#e8e8e8;padding:8px 10px;font-size:12.5px;outline:none}
.dvz-tree{max-height:280px;overflow:auto;padding:4px 0}
.dvz-trow{display:flex;align-items:center;gap:6px;padding:5px 10px;font-size:12.5px;color:#dcdcdc;cursor:pointer;white-space:nowrap;overflow:hidden}
.dvz-trow:hover{background:rgba(255,255,255,.07)}
.dvz-trow.dvz-cur{color:#4a9eff}
.dvz-dir{color:#c8cad0;font-weight:600}
.dvz-arrow{width:12px;flex-shrink:0;color:#8a8f99}
.dvz-empty{padding:10px;color:#8a8f99;font-size:12px;text-align:center}
.dvz-row .dvz-str{width:58px;flex-shrink:0;background:#22242a;color:#e8e8e8;border:1px solid #3a3d45;border-radius:6px;padding:4px;font-size:12px;outline:none}
.dvz-row .dvz-str:focus{border-color:#4a9eff}
  .dvz-row .dvz-mode{width:26px;height:24px;flex-shrink:0;border-radius:6px;font-size:13px;cursor:pointer;user-select:none;line-height:1;padding:0;display:inline-flex;align-items:center;justify-content:center}
  .dvz-row .dvz-mode.dvz-std{background:transparent;border:1px solid #666;color:#9aa0aa}
  .dvz-row .dvz-mode.dvz-bypass{background:#2d5a3e;border:1px solid #3f8f5f;color:#9fe8b8}
  .dvz-row .dvz-mode.dvz-style{background:#1e3e66;border:1px solid #4a9eff;color:#96c8ff}
  .dvz-row .dvz-mode.dvz-person{background:#3e2c5c;border:1px solid #aa82dc;color:#d6baff}
  .dvz-row .dvz-mode:hover{filter:brightness(1.25)}
  .dvz-menu{padding:4px}
  .dvz-mi{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:6px;cursor:pointer;color:#e8e8e8;font-size:12.5px}
  .dvz-mi:hover{background:rgba(255,255,255,.07)}
  .dvz-mi .dvz-mii{width:26px;height:24px;flex-shrink:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center}
  .dvz-mi .dvz-mii.dvz-std{background:transparent;border:1px solid #666;color:#9aa0aa}
  .dvz-mi .dvz-mii.dvz-bypass{background:#2d5a3e;border:1px solid #3f8f5f;color:#9fe8b8}
  .dvz-mi .dvz-mii.dvz-style{background:#1e3e66;border:1px solid #4a9eff;color:#96c8ff}
  .dvz-mi .dvz-mii.dvz-person{background:#3e2c5c;border:1px solid #aa82dc;color:#d6baff}
  .dvz-mi .dvz-mil{flex-shrink:0;min-width:34px}
  .dvz-mi .dvz-mid{color:#9aa0aa;font-size:11px;white-space:nowrap}
  .dvz-mi .dvz-cnt{margin-left:auto;color:#4a9eff;font-size:12px;padding-left:6px}
.dvz-row .dvz-note{flex:.5;min-width:0;background:transparent;color:#cfcfcf;border:none;border-bottom:1px dashed #3a3d45;padding:4px 2px;font-size:12px;outline:none}
.dvz-row .dvz-note:focus{border-bottom-color:#4a9eff}
.dvz-row .dvz-del{width:20px;height:20px;line-height:18px;text-align:center;border:none;border-radius:5px;background:transparent;color:#ff6b6b;font-size:15px;cursor:pointer;flex-shrink:0;padding:0}
.dvz-row .dvz-del:hover{background:rgba(255,107,107,.15)}
.dvz-bar{display:flex;gap:6px;align-items:center;width:100%;margin-top:2px}
.dvz-bar .dvz-add{flex:1;text-align:center;padding:6px 0;border:1px dashed #3a3d45;border-radius:8px;color:#9aa0aa;font-size:12.5px;cursor:pointer;user-select:none;background:rgba(255,255,255,.03)}
.dvz-bar .dvz-add:hover{border-color:#4a9eff;color:#4a9eff}
.dvz-bar .dvz-mv{width:34px;text-align:center;padding:6px 0;border:1px solid #3a3d45;border-radius:8px;color:#9aa0aa;font-size:12.5px;cursor:pointer;user-select:none;background:rgba(255,255,255,.03)}
.dvz-bar .dvz-mv:hover{border-color:#4a9eff;color:#4a9eff}
.dvz-bar .dvz-cnt{font-size:11px;color:#8a8f99;flex-shrink:0;min-width:34px;text-align:center}
.dvz-full{color:#e8a13c;font-size:11.5px;text-align:center;margin-top:4px}
.dvz-tip{font-size:11px;color:#8a8f99;text-align:center;margin-top:4px;line-height:1.3}
`;
  document.head.appendChild(s);
})();

// ── LoRA 文件清单（在线拉取，Windows 路径归一化）──────────────
let LORA_FILES = null;
let LORA_FILES_PROMISE = null;

async function fetchLoraFiles() {
  for (const url of ["/api/object_info/LoraLoaderModelOnly", "/object_info/LoraLoaderModelOnly", "/api/object_info/LoraLoader"]) {
    try {
      const r = await fetch(url);
      if (!r.ok) continue;
      const d = await r.json();
      const values =
        d?.LoraLoaderModelOnly?.input?.required?.lora_name?.[0] ??
        d?.LoraLoader?.input?.required?.lora_name?.[0];
      if (Array.isArray(values) && values.length) return values;
    } catch (e) { /* 下一条路由重试 */ }
  }
  return null;
}

function ensureLoraList(node) {
  if (!LORA_FILES_PROMISE) {
    LORA_FILES_PROMISE = fetchLoraFiles().then((v) => {
      if (v) {
        LORA_FILES = v;
        if (node) rebuildPanel(node);
      }
      return v;
    });
  }
  return LORA_FILES_PROMISE;
}

function getLoraList() {
  return Array.isArray(LORA_FILES) ? LORA_FILES : [];
}

const normPath = (p) => String(p).replace(/\\/g, "/");

// ── 树形选择弹窗（Filter 搜索 + 文件夹树，同原生加载器形态）────
let DVZ_POP = null;
let DVZ_MASK = null;
let DVZ_PLACE = null;
function closeTreePopup() {
  if (DVZ_POP) { DVZ_POP.remove(); DVZ_POP = null; }
  if (DVZ_MASK) { DVZ_MASK.remove(); DVZ_MASK = null; }
  if (DVZ_PLACE) { window.removeEventListener("resize", DVZ_PLACE); DVZ_PLACE = null; }
}

function openTreePopup(anchor, files, current, onPick, ev) {
  closeTreePopup();
  DVZ_MASK = document.createElement("div");
  DVZ_MASK.className = "dvz-mask";
  DVZ_MASK.addEventListener("mousedown", closeTreePopup);
  document.body.appendChild(DVZ_MASK);

  const pop = document.createElement("div");
  pop.className = "dvz-pop";
  const inp = document.createElement("input");
  inp.className = "dvz-filter";
  inp.placeholder = "Filter list";
  const tree = document.createElement("div");
  tree.className = "dvz-tree";
  pop.append(inp, tree);
  document.body.appendChild(pop);
  DVZ_POP = pop;

  const place = () => {
    const r = anchor.getBoundingClientRect();
    const W = Math.max(280, r.width || 280);
    pop.style.width = W + "px";
    let left = r.left;
    let top = r.bottom + 4;
    if ((!r.width && !r.height) && ev) { left = ev.clientX; top = ev.clientY + 4; }
    left = Math.max(8, Math.min(left, window.innerWidth - W - 8));
    if (top + pop.offsetHeight > window.innerHeight - 8) {
      top = Math.max(8, (r.top || (ev ? ev.clientY : 0)) - pop.offsetHeight - 4);
    }
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  };
  place();
  requestAnimationFrame(place);
  window.addEventListener("resize", place);
  DVZ_PLACE = place;

  const expanded = new Set();
  if (current) {
    const parts = normPath(current).split("/");
    for (let i = 1; i < parts.length; i++) expanded.add(parts.slice(0, i).join("/"));
  }

  const addFileRow = (f, depth, showPath) => {
    const d = document.createElement("div");
    d.className = "dvz-trow" + (f === current ? " dvz-cur" : "");
    d.style.paddingLeft = 10 + depth * 14 + "px";
    d.textContent = showPath ? normPath(f) : normPath(f).split("/").pop();
    d.title = normPath(f);
    d.onclick = () => { closeTreePopup(); onPick(f); };
    tree.appendChild(d);
  };

  const render = () => {
    const kw = inp.value.trim().toLowerCase();
    tree.innerHTML = "";
    if (!files.length) {
      const e = document.createElement("div");
      e.className = "dvz-empty";
      e.textContent = "（未找到 LoRA 文件）";
      tree.appendChild(e);
      return;
    }
    if (kw) {
      const hits = files.filter((f) => normPath(f).toLowerCase().includes(kw));
      hits.forEach((f) => addFileRow(f, 0, true));
      if (!hits.length) {
        const e = document.createElement("div");
        e.className = "dvz-empty";
        e.textContent = "无匹配";
        tree.appendChild(e);
      }
      return;
    }
    const root = { dirs: new Map(), files: [] };
    for (const f of files) {
      const parts = normPath(f).split("/");
      let n = root;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!n.dirs.has(parts[i])) n.dirs.set(parts[i], { dirs: new Map(), files: [] });
        n = n.dirs.get(parts[i]);
      }
      n.files.push(f);
    }
    const walk = (dirsMap, fileArr, depth, path) => {
      [...dirsMap.keys()].sort().forEach((name) => {
        const full = path ? path + "/" + name : name;
        const open = expanded.has(full);
        const d = document.createElement("div");
        d.className = "dvz-trow dvz-dir";
        d.style.paddingLeft = 10 + depth * 14 + "px";
        const arrow = document.createElement("span");
        arrow.className = "dvz-arrow";
        arrow.textContent = open ? "▾" : "▸";
        const label = document.createElement("span");
        label.textContent = "📁 " + name;
        d.append(arrow, label);
        d.onclick = () => {
          if (expanded.has(full)) expanded.delete(full); else expanded.add(full);
          render();
        };
        tree.appendChild(d);
        if (open) {
          const sub = dirsMap.get(name);
          walk(sub.dirs, sub.files, depth + 1, full);
        }
      });
      fileArr.forEach((f) => addFileRow(f, depth, false));
    };
    walk(root.dirs, root.files, 0, "");
  };

  inp.oninput = render;
  inp.onkeydown = (e) => { if (e.key === "Escape") closeTreePopup(); };
  render();
  inp.focus();
}

// ── 行数据 ────────────────────────────────────────────────────
function normMode(v) {
  const k = v == null ? "" : String(v).trim();
  return DVZ_MODE_MAP[k] ? DVZ_MODE_MAP[k].id : MODE_STD;
}

function defaultRow() {
  const files = getLoraList();
  return { on: true, file: files.length ? files[0] : "", strength: 1.0, mode: MODE_STD, note: "" };
}

function syncConfig(node) {
  // 2026-10-02: _dvzRows 与组 rows 可能不同引用（restoreRows/switchGroup 对
  // 空组走 [defaultRow()] 兜底时替换了数组）— 打包前必须把当前行写回组，
  // 否则序列化读到的是组里滞留的旧行，编辑在切页/保存时全部丢失。
  _applyRowsToGroup(node);
  const cfg = node.widgets?.find((w) => w.name === "LoRA配置");
  const json = JSON.stringify(_packPresets(node));
  if (cfg) cfg.value = json;
  // 2026-10-02: DOM 面板编辑绕过了 widget 交互管线, changeTracker 不会
  // 捕获状态 → 切换工作流标签页时 activeState 还是打开时的旧快照, 编辑丢失。
  // 按官方事件协议(litegraph:canvas before/after-change 成对派发)通知
  // 状态层: afterChange 归零时 captureCanvasState 会 serialize 整图(取
  // widget.value = 刚写入的新 JSON)存入 activeState。
  try {
    document.dispatchEvent(new CustomEvent("litegraph:canvas", { detail: { subType: "before-change" } }));
    document.dispatchEvent(new CustomEvent("litegraph:canvas", { detail: { subType: "after-change" } }));
  } catch (e) { console.warn("[Deciia VramSafe LoRA] canvas event:", e); }
}

// ── 预设分组（2026-10-01；对齐 DeciiaModelHub 的组语义） ─────────
function _packPresets(node) {
  const groups = node._dvzPresets && node._dvzPresets.length ? node._dvzPresets : [{ name: "默认", rows: [] }];
  return { presets: groups.map((g) => ({ name: g.name, rows: g.rows })), current: node._dvzGroup || groups[0].name };
}

function _unpackPresets(obj, node) {
  // 兼容旧格式（纯数组 = "默认"组一行到底）
  if (Array.isArray(obj)) {
    return { groups: [{ name: "默认", rows: obj }], current: "默认" };
  }
  if (obj && Array.isArray(obj.presets) && obj.presets.length) {
    const groups = obj.presets
      .filter((g) => g && typeof g === "object")
      .map((g) => ({ name: String(g.name || "组"), rows: Array.isArray(g.rows) ? g.rows : [] }));
    const cur = String(obj.current || groups[0].name);
    return { groups, current: groups.some((g) => g.name === cur) ? cur : groups[0].name };
  }
  return { groups: [{ name: "默认", rows: [] }], current: "默认" };
}

function _normRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((x) => x && typeof x === "object")
    .map((x) => ({
      on: x.on !== false,
      file: typeof x.file === "string" ? x.file : "",
      strength: Number.isFinite(Number(x.strength)) ? Number(x.strength) : 1.0,
      mode: normMode(x.mode),
      note: typeof x.note === "string" ? x.note : "",
    }));
}

// 从 LoRA配置 恢复面板行；兼容 v0 老行（无 mode 键 → 标准）与旧纯数组格式
function restoreRows(node) {
  const cfg = node.widgets?.find((w) => w.name === "LoRA配置");
  let obj;
  try {
    obj = JSON.parse(cfg?.value ?? "null");
  } catch (e) { obj = null; }
  if (obj == null || (Array.isArray(obj) && !obj.length)) {
    // widget 值尚未灌入（异步物化窗口）或为空：已有预设则保现状，别清面板
    if (node._dvzPresets?.length) return;
    obj = [];
  }
  const { groups, current } = _unpackPresets(obj, node);
  node._dvzPresets = groups.map((g) => ({ name: g.name, rows: _normRows(g.rows) }));
  node._dvzGroup = current;
  const g = node._dvzPresets.find((x) => x.name === node._dvzGroup) || node._dvzPresets[0];
  node._dvzRows = g.rows.length ? g.rows : [defaultRow()];
  node._dvzRestoredOk = !!(obj && (Array.isArray(obj) ? obj.length : obj.presets?.length));
  console.log("[Deciia VramSafe LoRA] restoreRows:", node._dvzRestoredOk ? "已载入" : "空/未灌值",
    "| 组数", node._dvzPresets.length, "| 当前行数", node._dvzRows.length);
}

function _applyRowsToGroup(node) {
  const g = node._dvzPresets?.find((x) => x.name === node._dvzGroup);
  if (g) g.rows = node._dvzRows || [];
}

function _switchGroup(node, name) {
  _applyRowsToGroup(node); // 当前行先写回组
  const g = node._dvzPresets.find((x) => x.name === name);
  if (!g) return;
  node._dvzGroup = name;
  node._dvzRows = g.rows.length ? g.rows : [defaultRow()];
  node._dvzSel = node._dvzRows.length - 1;
  rebuildPanel(node);
  syncConfig(node);
}

// ── 行构建 ────────────────────────────────────────────────────
function applyModeBtn(btn, mode) {
  const m = DVZ_MODE_MAP[mode] || DVZ_MODE_MAP[MODE_STD];
  for (const x of DVZ_MODES) btn.classList.toggle(x.cls, x.id === m.id);
  btn.innerHTML = modeSVG(m, 14);
  btn.title = m.label + "：" + m.desc + "。点击展开方式列表";
}

// 点击方式按钮 → 展开列表（沿用 dvz-pop / dvz-mask，一次只开一个弹层）
function openModeMenu(anchor, current, onPick, ev) {
  closeTreePopup();
  DVZ_MASK = document.createElement("div");
  DVZ_MASK.className = "dvz-mask";
  DVZ_MASK.addEventListener("mousedown", closeTreePopup);
  document.body.appendChild(DVZ_MASK);

  const menu = document.createElement("div");
  menu.className = "dvz-pop dvz-menu";
  for (const m of DVZ_MODES) {
    const it = document.createElement("div");
    it.className = "dvz-mi";
    it.title = m.label + "：" + m.desc;
    const ii = document.createElement("span");
    ii.className = "dvz-mii " + m.cls;
    ii.innerHTML = modeSVG(m, 14);
    const il = document.createElement("span");
    il.className = "dvz-mil";
    il.textContent = m.id === MODE_STD ? "标准（默认）" : m.label;
    const idd = document.createElement("span");
    idd.className = "dvz-mid";
    idd.textContent = m.desc;
    it.append(ii, il, idd);
    if (m.id === current) {
      const ck = document.createElement("span");
      ck.className = "dvz-cnt";
      ck.textContent = "✓";
      it.append(ck);
    }
    it.onclick = (e) => { e.stopPropagation(); closeTreePopup(); onPick(m.id); };
    menu.appendChild(it);
  }
  document.body.appendChild(menu);
  DVZ_POP = menu;

  const place = () => {
    const r = anchor.getBoundingClientRect();
    const w = menu.offsetWidth || 232;
    let left = r.left + r.width - w;
    let top = r.bottom + 4;
    left = Math.max(6, Math.min(left, window.innerWidth - w - 6));
    if (top + menu.offsetHeight > window.innerHeight - 6) top = Math.max(6, r.top - menu.offsetHeight - 4);
    menu.style.left = left + "px";
    menu.style.top = top + "px";
  };
  place();
  DVZ_PLACE = place;
  window.addEventListener("resize", place);
}

function buildRow(node, row, index) {
  const div = document.createElement("div");
  div.className = "dvz-row" + (row.on ? "" : " dvz-off") + (node._dvzSel === index ? " dvz-sel" : "");
  div.onclick = () => { node._dvzSel = index; markSelection(node); };

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = !!row.on;
  cb.title = "勾选启用 / 取消禁用该 LoRA";
  cb.onclick = (e) => e.stopPropagation();
  cb.onchange = () => {
    row.on = cb.checked;
    div.classList.toggle("dvz-off", !row.on);
    syncConfig(node);
  };

  const fileBtn = document.createElement("button");
  fileBtn.type = "button";
  fileBtn.className = "dvz-file";
  const setName = (v) => {
    fileBtn.textContent = v ? normPath(v).split("/").pop() : "（未选择 LoRA）";
    fileBtn.title = v || "未选择";
  };
  if (!row.file) {
    const files = getLoraList();
    if (files.length) row.file = files[0];
  }
  setName(row.file);
  fileBtn.onclick = (e) => {
    e.stopPropagation();
    openTreePopup(fileBtn, getLoraList(), row.file, (v) => {
      row.file = v;
      setName(v);
      syncConfig(node);
    }, e);
  };

  const str = document.createElement("input");
  str.className = "dvz-str";
  str.type = "number";
  str.step = "0.05";
  str.min = "0";
  str.max = "2";
  str.value = row.strength ?? 1;
  str.title = "模型强度 (0 ~ 2)";
  str.onclick = (e) => e.stopPropagation();
  const onStr = () => {
    const v = parseFloat(str.value);
    if (!isNaN(v)) {
      row.strength = Math.max(0, Math.min(2, v));
      syncConfig(node);
    }
  };
  str.oninput = onStr;
  str.onchange = onStr;

  const mode = document.createElement("button");
  mode.type = "button";
  mode.className = "dvz-mode";
  applyModeBtn(mode, row.mode);
  mode.onclick = (e) => {
    e.stopPropagation();
    openModeMenu(mode, row.mode, (picked) => {
      row.mode = picked;
      applyModeBtn(mode, row.mode);
      syncConfig(node);
    }, e);
  };

  const note = document.createElement("input");
  note.className = "dvz-note";
  note.type = "text";
  note.placeholder = "备注";
  note.title = "该 LoRA 的备注";
  note.value = row.note || "";
  note.onclick = (e) => e.stopPropagation();
  note.oninput = () => { row.note = note.value; syncConfig(node); };

  const del = document.createElement("button");
  del.className = "dvz-del";
  del.textContent = "×";
  del.title = "删除该行";
  del.onclick = (e) => {
    e.stopPropagation();
    node._dvzRows.splice(index, 1);
    if ((node._dvzSel ?? -1) >= node._dvzRows.length) node._dvzSel = node._dvzRows.length - 1;
    rebuildPanel(node);
    syncConfig(node);
  };

  div.append(cb, fileBtn, str, mode, note, del);
  return div;
}

function markSelection(node) {
  const wrap = node._dvzWrap;
  if (!wrap) return;
  [...wrap.querySelectorAll(".dvz-row")].forEach((el, i) => {
    el.classList.toggle("dvz-sel", i === (node._dvzSel ?? -1));
  });
}

// ── 面板重建 ──────────────────────────────────────────────────
function rebuildPanel(node) {
  const wrap = node._dvzWrap;
  if (!wrap) return;
  wrap.innerHTML = "";

  const rows = node._dvzRows;

  // ── 组条（预设分组，2026-10-01）：组下拉 + 组管理，行面板以上轻量一条 ──
  const gbar = document.createElement("div");
  gbar.className = "dvz-bar";
  gbar.style.marginBottom = "4px";
  const gsel = document.createElement("div");
  gsel.className = "dvz-file";
  gsel.style.flex = "1";
  gsel.textContent = `组：${node._dvzGroup || "默认"}`;
  gsel.title = "当前预设组。点击切换 / 管理";
  gsel.onclick = (e) => {
    e.stopPropagation();
    closeTreePopup();
    DVZ_MASK = document.createElement("div");
    DVZ_MASK.className = "dvz-mask";
    DVZ_MASK.addEventListener("mousedown", closeTreePopup);
    document.body.appendChild(DVZ_MASK);
    const menu = document.createElement("div");
    menu.className = "dvz-pop dvz-menu";
    (node._dvzPresets || []).forEach((g) => {
      const it = document.createElement("div");
      it.className = "dvz-mi";
      const il = document.createElement("span");
      il.className = "dvz-mil";
      il.textContent = g.name;
      const idd = document.createElement("span");
      idd.className = "dvz-mid";
      idd.textContent = `${g.rows.length} 行`;
      it.append(il, idd);
      if (g.name === node._dvzGroup) {
        const ck = document.createElement("span");
        ck.className = "dvz-cnt";
        ck.textContent = "✓";
        it.append(ck);
      }
      it.onclick = (ev) => { ev.stopPropagation(); closeTreePopup(); _switchGroup(node, g.name); };
      menu.appendChild(it);
    });
    const mk = document.createElement("div");
    mk.className = "dvz-mi";
    const ml = document.createElement("span");
    ml.className = "dvz-mil";
    ml.textContent = "＋ 新组";
    mk.appendChild(ml);
    mk.onclick = (ev) => {
      ev.stopPropagation(); closeTreePopup();
      _deiiaAsk("dvz-new", "新组名（如 qwen2.1 / krea2）", `组${(node._dvzPresets || []).length + 1}`, (name) => {
        if ((node._dvzPresets || []).some((g) => g.name === name)) {
          _deiiaMsg("dvz-new-dup", `组「${name}」已存在`);
          return;
        }
        _applyRowsToGroup(node);
        node._dvzPresets.push({ name, rows: [] });
        _switchGroup(node, name);
      });
    };
    menu.appendChild(mk);
    const rn = document.createElement("div");
    rn.className = "dvz-mi";
    const rl = document.createElement("span");
    rl.className = "dvz-mil";
    rl.textContent = "✎ 改名";
    rn.appendChild(rl);
    rn.onclick = (ev) => {
      ev.stopPropagation(); closeTreePopup();
      const g = node._dvzPresets?.find((x) => x.name === node._dvzGroup);
      if (!g) return;
      _deiiaAsk("dvz-rename", "组改名", g.name, (name) => {
        if (!name || name === g.name) return;
        if (node._dvzPresets.some((x) => x.name === name)) {
          _deiiaMsg("dvz-rename-dup", `组「${name}」已存在`);
          return;
        }
        g.name = name;
        node._dvzGroup = name;
        rebuildPanel(node);
        syncConfig(node);
      });
    };
    menu.appendChild(rn);
    const dl = document.createElement("div");
    dl.className = "dvz-mi";
    const dll = document.createElement("span");
    dll.className = "dvz-mil";
    dll.textContent = "✕ 删除当前组";
    dl.appendChild(dll);
    dl.onclick = (ev) => {
      ev.stopPropagation(); closeTreePopup();
      if ((node._dvzPresets || []).length <= 1) {
        _deiiaMsg("dvz-del-min", "至少保留一个组");
        return;
      }
      _deiiaConfirm("dvz-del", `删除组「${node._dvzGroup}」？`, () => {
        node._dvzPresets = node._dvzPresets.filter((g) => g.name !== node._dvzGroup);
        _switchGroup(node, node._dvzPresets[0].name);
      });
    };
    menu.appendChild(dl);
    document.body.appendChild(menu);
    DVZ_POP = menu;
    const place = () => {
      const r = gsel.getBoundingClientRect();
      const w = menu.offsetWidth || 232;
      let left = Math.max(6, Math.min(r.left, window.innerWidth - w - 6));
      let top = r.bottom + 4;
      if (top + menu.offsetHeight > window.innerHeight - 6) top = Math.max(6, r.top - menu.offsetHeight - 4);
      menu.style.left = left + "px";
      menu.style.top = top + "px";
    };
    place();
    DVZ_PLACE = place;
    window.addEventListener("resize", place);
  };
  gbar.appendChild(gsel);
  wrap.appendChild(gbar);

  rows.forEach((row, i) => wrap.appendChild(buildRow(node, row, i)));

  const bar = document.createElement("div");
  bar.className = "dvz-bar";

  const add = document.createElement("div");
  add.className = "dvz-add";
  add.textContent = "＋ 添加 LoRA";
  add.onclick = (e) => {
    e.stopPropagation();
    node._dvzRows.push(defaultRow());
    node._dvzSel = node._dvzRows.length - 1;
    rebuildPanel(node);
    syncConfig(node);
  };
  const up = document.createElement("div");
  up.className = "dvz-mv";
  up.textContent = "↑";
  up.title = "选中行上移";
  up.onclick = (e) => { e.stopPropagation(); moveRow(node, -1); };
  const down = document.createElement("div");
  down.className = "dvz-mv";
  down.textContent = "↓";
  down.title = "选中行下移";
  down.onclick = (e) => { e.stopPropagation(); moveRow(node, +1); };
  const cnt = document.createElement("div");
  cnt.className = "dvz-cnt";
  cnt.textContent = `${rows.length}/${MAX_ROWS}`;
  bar.append(add, up, down, cnt);
  wrap.appendChild(bar);

  if (rows.length >= MAX_ROWS) {
    const full = document.createElement("div");
    full.className = "dvz-full";
    full.textContent = `最多 ${MAX_ROWS} 个 LoRA，先删除再添加`;
    wrap.appendChild(full);
  }
  const tip = document.createElement("div");
  tip.className = "dvz-tip";
  tip.textContent = "方式：点图标展开列表（标准/旁路/风格/人物）；点行选中后可 ↑↓ 排序";
  wrap.appendChild(tip);

  markSelection(node);

  // 高度：行 ~40px + 工具条/提示 ~78px；同步 canvas(computeSize) 与 Vue 布局层(get*Height)
  node._dvzHeight = rows.length * 40 + 108; // +30 组条(2026-10-01)
  if (node._dvzDomW) {
    node._dvzDomW.computeSize = () => [node.size[0], node._dvzHeight];
  }
  resizeNode(node);
}

function moveRow(node, dir) {
  const rows = node._dvzRows;
  if (!rows.length) return;
  const sel = Math.max(0, Math.min(rows.length - 1, Number(node._dvzSel ?? rows.length - 1)));
  const tgt = sel + dir;
  if (tgt < 0 || tgt >= rows.length) return;
  const t = rows[sel];
  rows[sel] = rows[tgt];
  rows[tgt] = t;
  node._dvzSel = tgt;
  rebuildPanel(node);
  syncConfig(node);
}

// ── 节点尺寸（只增不减守卫）──────────────────────────────────
function resizeNode(node) {
  try {
    const cs = node.computeSize();
    const minH = (node._dvzHeight ?? 60) + 80;
    node.setSize([
      Math.max(cs[0], node.size?.[0] ?? 0),
      Math.max(cs[1], minH),
    ]);
    node.setDirtyCanvas(true, true);
  } catch (e) { /* 布局层早于画布就绪时忽略 */ }
}

// ── 面板初始化 ────────────────────────────────────────────────
function setupPanel(node) {
  // 隐藏兜底 widget（LoRA文件/模型强度：扩展未加载时仍可单 LoRA 用）；LoRA配置=面板 JSON 载体
  for (const name of ["LoRA文件", "模型强度", "LoRA配置"]) {
    const w = node.widgets?.find((x) => x.name === name);
    if (!w) continue;
    w.hidden = true;
    w.computeSize = () => [0, 0];
    w.draw = () => {};
    w.mouse = () => {};
  }
  // 序列化兜底：提交 prompt / 保存工作流时都吐最新面板 JSON
  const cfg = node.widgets?.find((w) => w.name === "LoRA配置");
  if (cfg) {
    // 2026-10-01: 序列化吐预设分组结构（丢组=丢配置），不再吐裸行数组
    cfg.serializeValue = () => JSON.stringify(_packPresets(node));
  }

  restoreRows(node);
  node._dvzHeight = 90;
  node._dvzSel = node._dvzRows.length - 1;

  const wrap = document.createElement("div");
  wrap.className = "dvz-wrap";
  wrap.addEventListener("mousedown", (e) => e.stopPropagation());
  wrap.addEventListener("keydown", (e) => e.stopPropagation());

  node._dvzWrap = wrap;
  node._dvzDomW = node.addDOMWidget("lora面板", "lora面板", wrap, {
    serialize: false,
    getMinHeight: () => node._dvzHeight,
    getMaxHeight: () => node._dvzHeight,
    getHeight: () => node._dvzHeight,
  });

  rebuildPanel(node);
  syncConfig(node);
  node.size[0] = Math.max(node.size[0], 360);
  resizeNode(node);
  ensureLoraList(node);
}

// ── 注册扩展 ──────────────────────────────────────────────────
app.registerExtension({
  name: "deciia.vramsafe.lora.stack",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated ? onCreated.apply(this, arguments) : undefined;
      setupPanel(this);
      return r;
    };

    // 加载已保存工作流：从 LoRA配置 JSON 恢复面板
    const onConfigure = nodeType.prototype.configure;
    nodeType.prototype.configure = function (info) {
      const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
      // 值灌入时机不定 — 轮询直到读到非空 LoRA配置 或超时（最多 ~6s）
      const lateRestore = (n, tries = 0) => setTimeout(() => {
        try {
          const cfg = n.widgets?.find((w) => w.name === "LoRA配置");
          let obj = null;
          try { obj = JSON.parse(cfg?.value ?? "null"); } catch (e) {}
          const empty = obj == null || (Array.isArray(obj) && !obj.length);
          if (!empty) {
            restoreRows(n);
            if (!n._dvzRestoredOk) { if (tries < 12) lateRestore(n, tries + 1); return; }
            n._dvzSel = n._dvzRows.length - 1;
            rebuildPanel(n);
            syncConfig(n);
            console.log("[Deciia VramSafe LoRA] lateRestore 完成: 行数", n._dvzRows.length);
            return; // 值已灌入并恢复，停止轮询
          }
          if (tries < 12) lateRestore(n, tries + 1);
        } catch (e) { console.warn("[Deciia VramSafe LoRA] late restore:", e); }
      }, 500);
      try {
        restoreRows(this);
        if (!this._dvzSel) this._dvzSel = this._dvzRows.length - 1;
        rebuildPanel(this);
        ensureLoraList(this);
        lateRestore(this);
      } catch (e) {
        console.warn("[Deciia VramSafe LoRA] configure:", e);
      }
      return r;
    };
  },
});

// —— 内联输入/消息弹层（浏览器 prompt/alert/confirm 会被页面拦截，改用自定义弹层）——
function _deiiaModal(tag, html, onMount) {
  const mask = document.createElement("div");
  mask.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99998;";
  const box = document.createElement("div");
  box.dataset.deiiaModal = tag;
  box.style.cssText = "position:fixed;left:50%;top:40%;transform:translate(-50%,-50%);"
    + "background:#22222a;color:#ddd;border:1px solid #4a4a55;border-radius:8px;"
    + "padding:12px 14px;z-index:99999;min-width:280px;box-shadow:0 6px 24px rgba(0,0,0,.5);font-size:12px;";
  box.innerHTML = html;
  mask.appendChild(box);
  document.body.appendChild(mask);
  const close = () => mask.remove();
  mask.addEventListener("click", (e) => { if (e.target === mask) close(); });
  onMount(box, close);
}

function _deiiaAsk(tag, title, initial, onOk) {
  _deiiaModal(tag, `<div style="margin-bottom:8px;">${title}</div>`, (box, close) => {
    const input = document.createElement("input");
    input.value = initial || "";
    input.style.cssText = "width:100%;box-sizing:border-box;background:#16161c;color:#eee;"
      + "border:1px solid #4a4a55;border-radius:4px;padding:4px 8px;margin-bottom:10px;";
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;";
    const ok = document.createElement("button");
    ok.textContent = "确定";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#2f6f3f;color:#fff;border:none;border-radius:4px;";
    const cancel = document.createElement("button");
    cancel.textContent = "取消";
    cancel.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    row.append(cancel, ok);
    box.append(input, row);
    const submit = () => { const v = input.value.trim(); close(); if (v) onOk(v); };
    ok.onclick = submit;
    input.onkeydown = (e) => {
      if (e.key === "Enter") submit();
      if (e.key === "Escape") close();
    };
    setTimeout(() => { input.focus(); input.select(); }, 30);
  });
}

function _deiiaMsg(tag, msg) {
  _deiiaModal(tag, `<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const ok = document.createElement("button");
    ok.textContent = "知道了";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = close;
    box.append(ok);
  });
}

function _deiiaConfirm(tag, msg, onOk) {
  _deiiaModal(tag, `<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;";
    const ok = document.createElement("button");
    ok.textContent = "确定";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#8a3030;color:#fff;border:none;border-radius:4px;";
    const cancel = document.createElement("button");
    cancel.textContent = "取消";
    cancel.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = () => { close(); onOk(); };
    cancel.onclick = close;
    row.append(cancel, ok);
    box.append(row);
  });
}
