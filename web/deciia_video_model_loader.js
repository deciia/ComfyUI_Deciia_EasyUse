// Deiia 视频模型加载器 · 四合一预设 — 整面板单 DOM 组件（LoRA 串同款交互）。
// 隐藏的原生 combo 仅作数据持有层；显示与位置由本面板全权负责。
// 弹层使用页面内自定义实现（浏览器 prompt/alert/confirm 会被拦截）。
import { app } from "../../../scripts/app.js";

function _vmlModal(html, onMount) {
  const mask = document.createElement("div");
  mask.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99998;";
  const box = document.createElement("div");
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

function _vmlAsk(title, initial, onOk) {
  _vmlModal(`<div style="margin-bottom:8px;">${title}</div>`, (box, close) => {
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
    cancel.onclick = close;
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

function _vmlMsg(msg) {
  _vmlModal(`<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const ok = document.createElement("button");
    ok.textContent = "知道了";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = close;
    box.append(ok);
  });
}

function _vmlConfirm(msg, onOk) {
  _vmlModal(`<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;";
    const ok = document.createElement("button");
    ok.textContent = "确定";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#8a3030;color:#fff;border:none;border-radius:4px;";
    const cancel = document.createElement("button");
    cancel.textContent = "取消";
    cancel.onclick = close;
    cancel.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = () => { close(); onOk(); };
    row.append(cancel, ok);
    box.append(row);
  });
}

const VML_KEYS = ["unet_name", "clip_name", "video_vae_name", "audio_vae_name"];
const VML_LABELS = { unet_name: "UNet", clip_name: "CLIP", video_vae_name: "视频VAE", audio_vae_name: "音频VAE" };

function _vmlCombo(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

function _vmlComboValue(node, name) {
  return _vmlCombo(node, name)?.value ?? "";
}

function _vmlComboOptions(node, name) {
  const o = _vmlCombo(node, name)?.options;
  return o?.options ?? o?.values ?? [];
}

function _vmlSetCombo(node, name, value) {
  const w = _vmlCombo(node, name);
  if (w) {
    w.value = value;
    if (w.callback) w.callback(w.value);
    app.graph.setDirtyCanvas(true, true);
  }
}

function _vmlData(node) {
  const w = _vmlWidget(node, "presets_json");
  try {
    const d = JSON.parse(w.value || "{}");
    if (Array.isArray(d.presets) && d.presets.length) {
      if (!d.presets.some((p) => p.name === d.current)) d.current = d.presets[0].name;
      return d;
    }
  } catch (e) {}
  return null;
}

function _vmlWrite(node, data) {
  const w = _vmlWidget(node, "presets_json");
  if (w) w.value = JSON.stringify(data);
}

function _vmlCur(node) {
  const d = _vmlData(node);
  return d ? d.current : "";
}

function _vmlApply(node, p) {
  for (const k of VML_KEYS) {
    if (p[k] != null) _vmlSetCombo(node, k, p[k]);
  }
}

// —— 面板 ——

function _vmlBuildPanel(node, root, data) {
  root.innerHTML = "";

  // 组行
  const grow = document.createElement("div");
  grow.style.cssText = "display:flex;gap:6px;align-items:center;margin:2px 0;";
  const glabel = document.createElement("span");
  glabel.textContent = "组:";
  glabel.style.cssText = "color:#aaa;font-size:11px;";
  const gbtn = document.createElement("button");
  gbtn.style.cssText = "cursor:pointer;padding:3px 12px;background:#2b2b33;color:#ddd;"
    + "border:1px solid #4a4a55;border-radius:4px;font-size:11px;text-align:left;flex:1;";
  const refreshGroup = () => { gbtn.textContent = "组: " + (_vmlCur(node) || "?"); };
  refreshGroup();
  gbtn.onclick = (ev) => {
    ev.stopPropagation();
    _vmlMenu(node, gbtn, () => { _vmlBuildPanel(node, root, _vmlData(node) || data); });
  };
  grow.append(glabel, gbtn);
  root.appendChild(grow);

  // 4 个文件行
  for (const k of VML_KEYS) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;align-items:center;margin:2px 0;";
    const label = document.createElement("span");
    label.textContent = VML_LABELS[k];
    label.style.cssText = "color:#aaa;font-size:11px;min-width:52px;";
    const sel = document.createElement("select");
    sel.style.cssText = "flex:1;min-width:0;background:#16161c;color:#eee;"
      + "border:1px solid #4a4a55;border-radius:4px;padding:2px 4px;font-size:11px;";
    const refreshSel = () => {
      const cur = _vmlComboValue(node, k);
      sel.innerHTML = "";
      for (const o of _vmlComboOptions(node, k)) {
        const op = document.createElement("option");
        op.value = o; op.textContent = o;
        if (o === cur) op.selected = true;
        sel.appendChild(op);
      }
      if (cur) sel.value = cur;
    };
    refreshSel();
    sel.onchange = () => {
      _vmlSetCombo(node, k, sel.value);
      const d = _vmlData(node);
      const p = d && d.presets.find((x) => x.name === d.current);
      if (p) { p[k] = sel.value; _vmlWrite(node, d); }
    };
    row.append(label, sel);
    root.appendChild(row);
    // 记录刷新函数，供菜单操作后刷新
    (node._vmlRefreshers ||= []).push(refreshSel);
  }

  const tip = document.createElement("div");
  tip.textContent = "点击「组」切换/管理预设";
  tip.style.cssText = "color:#666;font-size:10px;margin:2px 0;";
  root.appendChild(tip);
}

function _vmlRefreshPanel(node) {
  if (node._vmlPanelRoot) {
    node._vmlRefreshers = [];
    _vmlBuildPanel(node, node._vmlPanelRoot, _vmlData(node));
  }
}

// ⚙/组 菜单：预设列表 + 新组（复制当前）/改名/删除
function _vmlMenu(node, anchor) {
  const data = _vmlData(node) || { current: "", presets: [] };

  const menu = document.createElement("div");
  menu.style.cssText = "position:fixed;background:#1b1b22;color:#ddd;border:1px solid #4a4a55;"
    + "border-radius:8px;padding:6px 4px;z-index:99999;min-width:240px;"
    + "box-shadow:0 6px 24px rgba(0,0,0,.5);font-size:12px;";
  const close = () => menu.remove();

  const addItem = (label, hint, isCur, fn) => {
    const it = document.createElement("div");
    it.style.cssText = "display:flex;justify-content:space-between;align-items:center;"
      + "padding:6px 12px;cursor:pointer;border-radius:5px;";
    it.onmouseenter = () => { it.style.background = "#2f2f3a"; };
    it.onmouseleave = () => { it.style.background = "transparent"; };
    const l = document.createElement("span");
    l.textContent = label;
    const h = document.createElement("span");
    h.style.cssText = "color:#888;font-size:11px;";
    h.textContent = hint || "";
    if (isCur) h.textContent = "✓ " + (hint || "");
    it.append(l, h);
    it.onclick = (e) => { e.stopPropagation(); close(); fn(); };
    menu.appendChild(it);
  };
  const addSep = () => {
    const sep = document.createElement("div");
    sep.style.cssText = "height:1px;background:#3a3a44;margin:4px 8px;";
    menu.appendChild(sep);
  };

  data.presets.forEach((p) => {
    addItem(p.name, "", p.name === data.current, () => {
      data.current = p.name;
      _vmlWrite(node, data);
      _vmlApply(node, p);
      _vmlRefreshPanel(node);
    });
  });
  addSep();
  addItem("＋ 新预设（复制当前）", "", false, () => {
    const src = data.presets.find((x) => x.name === data.current);
    _vmlAsk("新预设名", (src ? src.name : "预设") + "-copy", (name) => {
      if (data.presets.some((x) => x.name === name)) {
        _vmlMsg(`预设「${name}」已存在`);
        return;
      }
      data.presets.push(JSON.parse(JSON.stringify({ ...(src || {}), name })));
      data.current = name;
      _vmlWrite(node, data);
      _vmlApply(node, data.presets.find((x) => x.name === name));
      _vmlRefreshPanel(node);
    });
  });
  addItem("✎ 改名", "", false, () => {
    const p = data.presets.find((x) => x.name === data.current);
    if (!p) return;
    _vmlAsk("重命名预设", data.current, (name) => {
      if (!name || name === data.current) return;
      if (data.presets.some((x) => x.name === name)) {
        _vmlMsg(`预设「${name}」已存在`);
        return;
      }
      p.name = name; data.current = name;
      _vmlWrite(node, data);
      _vmlRefreshPanel(node);
    });
  });
  addItem("✕ 删除当前预设", "", false, () => {
    if (data.presets.length <= 1) {
      _vmlMsg("至少保留一个预设");
      return;
    }
    _vmlConfirm(`删除预设「${data.current}」？`, () => {
      data.presets = data.presets.filter((x) => x.name !== data.current);
      data.current = data.presets[0].name;
      _vmlWrite(node, data);
      const p = data.presets.find((x) => x.name === data.current);
      if (p) _vmlApply(node, p);
      _vmlRefreshPanel(node);
    });
  });

  document.body.appendChild(menu);
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - 8) + "px";
    menu.style.left = Math.min(r.left, window.innerWidth - 260) + "px";
  }
  setTimeout(() => {
    document.addEventListener("click", function _once() {
      close();
      document.removeEventListener("click", _once);
    });
  }, 0);
}

app.registerExtension({
  name: "DeciiaVideoModelLoader",
  nodeCreated(node) {
    if (node.comfyClass !== "DeciiaVideoModelLoader") return;

    // 隐藏原生 combo 与 presets_json（仅作数据持有层；UI 由 DOM 面板全权负责）
    for (const name of [...VML_KEYS, "presets_json"]) {
      const w = _vmlCombo(node, name);
      if (w) { w.computeSize = () => [0, -4]; w.hidden = true; }
    }

    node._vmlRefreshers = [];
    const root = document.createElement("div");
    root.style.cssText = "display:flex;flex-direction:column;gap:2px;width:100%;";
    node._vmlPanelRoot = root;

    node.addDOMWidget("预设", "deciia.vml.panel", root, { getValue: () => "", setValue: () => {} });

    _vmlBuildPanel(node, root, _vmlData(node));
  },
});
