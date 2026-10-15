/**
 * Deciia 模型加载枢纽 前端 rev2（2026-10-03，固定 6 出口版）。
 *
 * v2 变更：出口固定（当前组/UNet/文本编码/VAE·视频/VAE·音频/模型补丁/机动），
 * 不再按组条目数动态增删 —— 连线一次接好，切组不动。
 * 面板按固定 6 槽渲染：文件 + （文本编码的 type 下拉/双击选）+ （机动的子类别）。
 * 预设结构 v2: {presets:[{name, files:{槽:{file,type,device,cat}}}], current}
 * 旧 v1（slots）由后端 _migrate 自动迁移；前端读到 slots 也现场转一份展示。
 */
import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_NAME = "DeciiaModelHub";
const W_TABLE = "预设表";

const SLOTS = ["UNet", "文本编码", "VAE·视频", "VAE·音频", "模型补丁", "机动"];
const FREE_CATS = ["不用", "CLIPVision", "放大模型"];

function parseTable(text) {
  try {
    const o = JSON.parse(text || "{}");
    if (o && Array.isArray(o.presets)) return migrate(o);
  } catch (e) {}
  return { presets: [] };
}
function migrate(t) {
  // 前端兜底迁移（后端 _migrate 是权威，这里只为画布显示）
  (t.presets || []).forEach((p) => {
    if (!p || Array.isArray(p.slots) === false || p.files) return;
    if (!Array.isArray(p.slots)) { p.files = p.files || {}; return; }
    const files = {};
    let vaeI = 0;
    p.slots.forEach((s) => {
      if (!s) return;
      if (s.cat === "UNet") files["UNet"] = { file: s.file || "", device: s.device || "default" };
      else if (s.cat === "文本编码") files["文本编码"] = { file: s.file || "", type: s.type || "", device: s.device || "default" };
      else if (s.cat === "VAE") { files[vaeI === 0 ? "VAE·视频" : "VAE·音频"] = { file: s.file || "" }; vaeI++; }
      else if (s.cat === "模型补丁") files["模型补丁"] = { file: s.file || "" };
    });
    SLOTS.forEach((k) => { if (!files[k]) files[k] = k === "机动" ? { cat: "不用", file: "" } : { file: "" }; });
    p.files = files;
    delete p.slots;
  });
  return t;
}
function widget(node, name) { return (node.widgets || []).find((w) => w?.name === name); }

let _panelSeq = 0;

function buildPanel(node) {
  if (node._hubPanel) return node._hubPanel;
  const root = document.createElement("div");
  root.className = "deciia-hub-panel";
  root.style.cssText = "background:#1c1c22;border:1px solid #3a3a44;border-radius:6px;padding:6px;margin:4px 0;font-size:11px;color:#ccc;max-width:440px;";
  node._hubPanel = root;

  const body = document.createElement("div");

  // 组切换下拉
  const groupBar = document.createElement("div");
  groupBar.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:4px;";
  const gLabel = document.createElement("span");
  gLabel.textContent = "当前组：";
  gLabel.style.cssText = "color:#8ab4ff;font-weight:600;";
  const gSel = document.createElement("select");
  gSel.style.cssText = "background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:4px;font-size:11px;min-width:120px;";
  gSel.onchange = () => {
    node._hubGroup = gSel.value;
    writeTable(node, readTable(node));
  };
  node._hubGroupSel = gSel;
  groupBar.appendChild(gLabel);
  groupBar.appendChild(gSel);
  root.appendChild(groupBar);

  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px;";
  const mkBtn = (txt, fn) => {
    const b = document.createElement("button");
    b.textContent = txt; b.style.cssText = "cursor:pointer;padding:2px 8px;background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:4px;font-size:11px;";
    b.onclick = fn; return b;
  };
  bar.appendChild(mkBtn("＋组", () => {
    const t = readTable(node);
    _deiiaAsk("hub-new", "新组名（与合并台模型选择同名匹配，如 qwen2.1 / krea2 / h3）", `组${t.presets.length + 1}`, (name) => {
      if (t.presets.some((p) => p.name === name)) {
        _deiiaMsg("hub-new-dup", `组「${name}」已存在`);
        return;
      }
      const files = {};
      SLOTS.forEach((k) => { files[k] = k === "机动" ? { cat: "不用", file: "" } : { file: "" }; });
      t.presets.push({ name, files });
      node._hubGroup = name;
      writeTable(node, t);
    });
  }));
  bar.appendChild(mkBtn("改名", () => {
    const t = readTable(node); const g = currentGroup(t, node);
    if (!g) return;
    _deiiaAsk("hub-rename", "把当前组改名为", g.name, (name) => {
      if (!name || name === g.name) return;
      if (t.presets.some((p) => p.name === name)) {
        _deiiaMsg("hub-rename-dup", `组「${name}」已存在`);
        return;
      }
      g.name = name;
      node._hubGroup = name;
      writeTable(node, t);
    });
  }));
  bar.appendChild(mkBtn("复制组", () => {
    const t = readTable(node); const g = currentGroup(t, node);
    if (!g) return;
    _deiiaAsk("hub-copy", "复制当前组为新组名", g.name + "-copy", (name) => {
      if (!name) return;
      if (t.presets.some((p) => p.name === name)) {
        _deiiaMsg("hub-copy-dup", `组「${name}」已存在`);
        return;
      }
      t.presets.push({ name, files: JSON.parse(JSON.stringify(g.files || {})) });
      node._hubGroup = name;
      writeTable(node, t);
    });
  }));
  bar.appendChild(mkBtn("删组", () => {
    const t = readTable(node); const name = node._hubGroup || "";
    _deiiaConfirm("hub-del", `删除组「${name}」？`, () => {
      t.presets = t.presets.filter((p) => p.name !== name);
      writeTable(node, t);
    });
  }));
  root.appendChild(bar);
  root.appendChild(body);
  node._hubBody = body;
  node.addDOMWidget("枢纽面板", "deciia.hub.panel", root, { getValue: () => "", setValue: () => {} });
  return root;
}

function readTable(node) { return parseTable(widget(node, W_TABLE)?.value ?? ""); }
function writeTable(node, t) {
  t.current = node._hubGroup || t.current || "";
  const w = widget(node, W_TABLE);
  if (w) { w.value = JSON.stringify(t); }
  node._hubSeq = (_panelSeq += 1);
  refreshPanel(node);
  node.setDirtyCanvas?.(true, true);
}
function currentGroup(t, node) {
  const name = node._hubGroup || (t.presets[0] && t.presets[0].name) || "";
  return t.presets.find((p) => p.name === name) || null;
}

function refreshPanel(node) {
  const body = node._hubBody; if (!body) return;
  body.innerHTML = "";
  const t = readTable(node);
  const g = currentGroup(t, node);
  const gSel = node._hubGroupSel;
  if (gSel) {
    const names = t.presets.map((p) => p.name);
    if (gSel.options.length !== names.length || Array.from(gSel.options).some((o, i) => o.value !== names[i])) {
      gSel.innerHTML = "";
      names.forEach((n) => { const o = document.createElement("option"); o.value = n; o.textContent = n; gSel.appendChild(o); });
    }
    if (node._hubGroup && names.includes(node._hubGroup)) gSel.value = node._hubGroup;
  }
  if (!g) { body.textContent = "（无组 — 点「＋组」创建）"; return; }
  if (!g.files) g.files = {};

  const title = document.createElement("div");
  title.textContent = `组「${g.name}」 · 固定6槽（出口不随组变）`;
  title.style.cssText = "font-weight:600;margin:2px 0;color:#8ab4ff;";
  body.appendChild(title);

  const rowIdx = {};
  SLOTS.forEach((k) => {
    rowIdx[k] = (rowIdx[k] === undefined ? 0 : rowIdx[k]);
    const ent = g.files[k] || (g.files[k] = k === "机动" ? { cat: "不用", file: "" } : { file: "" });
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:4px;margin:2px 0;align-items:center;";

    const nameEl = document.createElement("span");
    nameEl.textContent = k;
    nameEl.style.cssText = "color:#9aa;font-weight:600;flex:0 0 64px;";
    row.appendChild(nameEl);

    // 文件（datalist 候选）
    const listId = `hub2-files-${node.id ?? 0}-${_panelSeq}-${k}`;
    const dl = document.createElement("datalist");
    dl.id = listId;
    fetchFileList(k, ent.cat).then((files) => files.forEach((f) => {
      const op = document.createElement("option"); op.value = f; dl.appendChild(op);
    }));
    row.appendChild(dl);
    const file = mkInput(ent.file || "", (v) => { ent.file = v.trim(); writeTable(node, t); });
    file.setAttribute("list", listId);
    file.placeholder = "(空=该槽输出None)";
    row.appendChild(file);

    // 文本编码：type 下拉（双击文件框？不——直接一个小按钮弹选）
    if (k === "文本编码") {
      const typeBtn = mkBtn(`type:${ent.type || "未设"}`, async () => {
        const items = await fetchClipTypes();
        if (!items.length) { _deiiaMsg("hub-clip-empty", "拉不到 CLIPLoader 的 type 候选"); return; }
        const v = await pickFromList("文本编码 type（CLIPLoader 分类）", items, ent.type || "");
        if (v != null) { ent.type = v; writeTable(node, t); }
      });
      typeBtn.style.flex = "0 0 110px";
      row.appendChild(typeBtn);
    }

    // 机动槽：子类别下拉
    if (k === "机动") {
      const catSel = mkSel(FREE_CATS, ent.cat || "不用", (v) => { ent.cat = v; writeTable(node, t); });
      row.appendChild(catSel);
    }

    body.appendChild(row);
  });
}

function mkBtn(txt, fn) {
  const b = document.createElement("button");
  b.textContent = txt; b.style.cssText = "cursor:pointer;padding:2px 8px;background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:4px;font-size:11px;";
  b.onclick = fn; return b;
}

/** CLIPLoader 的 type 候选（缓存） */
async function fetchClipTypes() {
  if (window._hubClipTypes) return window._hubClipTypes;
  try {
    const oi = await (await api.fetchApi("/object_info/CLIPLoader")).json();
    window._hubClipTypes = (oi?.CLIPLoader?.input?.required?.type?.[0]) || [];
  } catch (e) {
    console.warn("[模型枢纽] CLIP type 候选拉取失败", e);
    window._hubClipTypes = [];
  }
  return window._hubClipTypes;
}

/** 模态选择窗：下拉 + 确定/取消。返回选中值，取消返回 null。 */
function pickFromList(titleText, items, current) {
  return new Promise((resolve) => {
    const mask = document.createElement("div");
    mask.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:100000;display:flex;align-items:center;justify-content:center;";
    const box = document.createElement("div");
    box.style.cssText = "background:#1c1c22;border:1px solid #4a4a55;border-radius:8px;padding:12px;min-width:300px;max-width:80vw;font-size:12px;color:#ddd;box-shadow:0 8px 30px rgba(0,0,0,.6);";
    const h = document.createElement("div");
    h.textContent = titleText;
    h.style.cssText = "font-weight:600;color:#8ab4ff;margin-bottom:8px;";
    const sel = document.createElement("select");
    sel.style.cssText = "width:100%;background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:4px;font-size:12px;padding:4px;";
    const opts = items.slice();
    if (current && !opts.includes(current)) opts.unshift(current + "（不在候选）");
    opts.forEach((o) => {
      const op = document.createElement("option");
      const isStale = o.endsWith("（不在候选）");
      op.value = isStale ? current : o;
      op.textContent = o;
      if (op.value === current) op.selected = true;
      sel.appendChild(op);
    });
    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:10px;";
    const okBtn = mkBtn2("确定", true);
    const noBtn = mkBtn2("取消", false);
    const done = (v) => {
      window.removeEventListener("keydown", onKey, true);
      mask.remove();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); done(null); }
      else if (e.key === "Enter") { e.stopPropagation(); e.preventDefault(); done(sel.value); }
    };
    okBtn.onclick = () => done(sel.value);
    noBtn.onclick = () => done(null);
    mask.addEventListener("click", (e) => { if (e.target === mask) done(null); }, true);
    ["pointerdown", "mousedown", "mouseup", "wheel", "contextmenu"].forEach((ev) =>
      mask.addEventListener(ev, (e) => { if (!box.contains(e.target)) e.stopPropagation(); }, true));
    window.addEventListener("keydown", onKey, true);
    bar.appendChild(noBtn); bar.appendChild(okBtn);
    box.appendChild(h); box.appendChild(sel); box.appendChild(bar);
    mask.appendChild(box);
    document.body.appendChild(mask);
    sel.focus();
  });
}
function mkBtn2(txt, primary) {
  const b = document.createElement("button");
  b.textContent = txt;
  b.style.cssText = "background:" + (primary ? "#3a6ea5" : "#2b2b33") + ";color:#ddd;border:1px solid #4a4a55;border-radius:4px;padding:4px 14px;font-size:12px;cursor:pointer;";
  return b;
}

function mkSel(opts, val, onch) {
  const s = document.createElement("select");
  s.style.cssText = "background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:3px;font-size:11px;max-width:86px;";
  opts.forEach((o) => { const op = document.createElement("option"); op.value = o; op.textContent = o; if (o === val) op.selected = true; s.appendChild(op); });
  s.onchange = () => onch(s.value);
  return s;
}
async function fetchFileList(slotKey, freeCat) {
  // 固定槽 → 各自 loader 的 object_info；机动槽按子类别
  const map = {
    "UNet": ["UNETLoader", "unet_name"],
    "文本编码": ["CLIPLoader", "clip_name"],
    "VAE·视频": ["VAELoader", "vae_name"],
    "VAE·音频": ["VAELoader", "vae_name"],
    "模型补丁": ["ModelPatchLoader", "name"],
  };
  let endpoint, key;
  if (slotKey === "机动") {
    const m = { CLIPVision: ["CLIPVisionLoader", "clip_name"], 放大模型: ["UpscaleModelLoader", "model_name"] }[freeCat] || [null, null];
    [endpoint, key] = m;
  } else {
    [endpoint, key] = map[slotKey] || [null, null];
  }
  if (!endpoint) return [];
  const cacheKey = endpoint + "/" + String(key);
  if (window._hubFiles && window._hubFiles[cacheKey]) return window._hubFiles[cacheKey];
  try {
    const oi = await (await api.fetchApi(`/object_info/${endpoint}`)).json();
    const list = (oi?.[endpoint]?.input?.required?.[key]?.[0]) || [];
    window._hubFiles = window._hubFiles || {};
    window._hubFiles[cacheKey] = list;
    return list;
  } catch (e) { console.warn("[模型枢纽] 候选拉取失败", slotKey, e); return []; }
}

function mkInput(val, onch) {
  const i = document.createElement("input");
  i.value = val; i.placeholder = val;
  i.style.cssText = "background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:3px;font-size:11px;min-width:60px;flex:1;";
  i.onchange = () => onch(i.value);
  return i;
}

/** v2：出口固定 —— 不再动态增删。只在出口缺失（旧图升级）时补齐标准 7 口。 */
function syncOutputs(node) {
  const WANT = [
    ["当前组", "STRING"],
    ["UNet", "*"], ["文本编码", "*"], ["VAE·视频", "*"], ["VAE·音频", "*"],
    ["模型补丁", "*"], ["机动", "*"],
  ];
  // 后端声明类型是权威（MODEL/CLIP/VAE/…），前端用 "*" 通配以免类型墙拦旧线
  while ((node.outputs || []).length < WANT.length) node.addOutput(WANT[node.outputs.length][0], "*");
  while ((node.outputs || []).length > WANT.length) node.removeOutput(node.outputs.length - 1);
  WANT.forEach(([name], i) => {
    if ((node.outputs[i]?.name || "") !== name) node.outputs[i].name = name;
  });
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "deciia_local.model_hub",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;

    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = origCreated?.apply(this, arguments);
      try {
        setTimeout(() => {
          for (const w of this.widgets || []) {
            if (!w) continue;
            if (w.name === W_TABLE || w.name === "当前组") {
              w.hidden = true;
              w.type = "hidden";
            }
          }
          this.computeSize?.();
          this.setDirtyCanvas?.(true, true);
        }, 50);
        buildPanel(this);
        const t = readTable(this);
        this._hubGroup = t.current || t.presets[0]?.name || "";
        refreshPanel(this);
        syncOutputs(this);
      } catch (e) { console.error("[模型枢纽]", e); }
      return r;
    };

    const origSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (o) {
      const r = origSerialize?.apply(this, arguments);
      try {
        const t = readTable(this);
        if (t && typeof t === "object") t.current = this._hubGroup || t.current || "";
        const json = JSON.stringify(t);
        const w = widget(this, W_TABLE);
        if (w) { w.hidden = false; w.value = json; }
        if (Array.isArray(o.widgets_values) && o.widgets_values.length) {
          o.widgets_values[0] = json;
        }
        if (w) queueMicrotask(() => { w.hidden = true; });
      } catch (e) { console.error("[模型枢纽] serialize", e); }
      return r;
    };
    const origConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (o) {
      const r = origConfigure?.apply(this, arguments);
      try {
        const t = readTable(this);
        this._hubGroup = t.current || t.presets[0]?.name || "";
        refreshPanel(this);
        syncOutputs(this);
      } catch (e) { console.error("[模型枢纽] configure", e); }
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
