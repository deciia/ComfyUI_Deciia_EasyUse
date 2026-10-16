// Deiia 采样预设 · 采样器+调度器 — ⚙ 菜单管理预设（与加载器同款交互）。
// 预设数据经 DOM 控件 getValue/setValue 序列化（可靠路径，不依赖隐藏控件）。
// 弹层使用页面内自定义实现（浏览器 prompt/alert/confirm 会被拦截）。
import { app } from "../../../scripts/app.js";

function _spModal(html, onMount) {
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

function _spAsk(title, initial, onOk) {
  _spModal(`<div style="margin-bottom:8px;">${title}</div>`, (box, close) => {
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

function _spMsg(msg) {
  _spModal(`<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const ok = document.createElement("button");
    ok.textContent = "知道了";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = close;
    box.append(ok);
  });
}

function _spConfirm(msg, onOk) {
  _spModal(`<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
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

const SP_KEYS = ["sampler_name", "scheduler", "steps", "denoise"];

function _spWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

// 预设数据存在 node.properties（永远随节点保存/恢复，可靠路径）
function _spData(node) {
  try {
    const d = JSON.parse(node.properties?.deiia_sp_data || "{}");
    if (Array.isArray(d.presets) && d.presets.length) {
      if (!d.current || !d.presets.some((p) => _spKey(p) === d.current)) {
        d.current = _spKey(d.presets[0]);
      }
      return d;
    }
  } catch (e) {}
  return null;
}

function _spWrite(node, data) {
  node.properties.deiia_sp_data = JSON.stringify(data);
  if (app.graph) app.graph.setDirtyCanvas(true, true);
}

function _spKey(p) { return (p.group || "通用") + "::" + p.name; }

function _spApply(node, p) {
  for (const k of SP_KEYS) {
    const w = _spWidget(node, k);
    if (w && p[k] != null) {
      w.value = p[k];
      if (w.callback) w.callback(w.value);
    }
  }
  app.graph.setDirtyCanvas(true, true);
}

function _spMenu(node, anchor) {
  const data = _spData(node) || { current: "", presets: [] };

  const menu = document.createElement("div");
  menu.style.cssText = "position:fixed;background:#1b1b22;color:#ddd;border:1px solid #4a4a55;"
    + "border-radius:8px;padding:6px 4px;z-index:99999;min-width:260px;max-height:70vh;overflow:auto;"
    + "box-shadow:0 6px 24px rgba(0,0,0,.5);font-size:12px;";
  const close = () => menu.remove();

  const addItem = (label, hint, isCur, fn) => {
    const it = document.createElement("div");
    it.style.cssText = "display:flex;justify-content:space-between;align-items:center;"
      + "padding:5px 12px;cursor:pointer;border-radius:5px;";
    it.onmouseenter = () => { it.style.background = "#2f2f3a"; };
    it.onmouseleave = () => { it.style.background = "transparent"; };
    const l = document.createElement("span");
    l.textContent = label;
    const h = document.createElement("span");
    h.style.cssText = "color:#888;font-size:11px;";
    h.textContent = hint || "";
    if (isCur) h.textContent = "✓";
    it.append(l, h);
    it.onclick = (e) => { e.stopPropagation(); close(); fn(); };
    menu.appendChild(it);
  };
  const addSep = () => {
    const sep = document.createElement("div");
    sep.style.cssText = "height:1px;background:#3a3a44;margin:4px 8px;";
    menu.appendChild(sep);
  };

  const groups = {};
  data.presets.forEach((p) => {
    const g = p.group || "通用";
    (groups[g] ||= []).push(p);
  });
  Object.entries(groups).forEach(([g, ps]) => {
    ps.forEach((p) => {
      addItem(`${g} / ${p.name}`, "", _spKey(p) === data.current, () => {
        data.current = _spKey(p);
        _spWrite(node, data);
        _spApply(node, p);
        refreshGear(node);
      });
    });
  });
  addSep();
  addItem("＋ 新预设（复制当前）", "", false, () => {
    const src = data.presets.find((x) => _spKey(x) === data.current);
    _spAsk("新预设名", (src ? src.name : "预设") + "-copy", (name) => {
      if (data.presets.some((x) => _spKey(x) === name)) {
        _spMsg(`预设「${name}」已存在`);
        return;
      }
      data.presets.push(JSON.parse(JSON.stringify({ ...(src || {}), name })));
      data.current = _spKey(data.presets[data.presets.length - 1]);
      _spWrite(node, data);
      const p = data.presets.find((x) => _spKey(x) === data.current);
      if (p) _spApply(node, p);
      refreshGear(node);
    });
  });
  addItem("✎ 改名", "", false, () => {
    const p = data.presets.find((x) => _spKey(x) === data.current);
    if (!p) return;
    _spAsk("重命名预设", p.name, (name) => {
      if (!name || name === p.name) return;
      if (data.presets.some((x) => x.name === name && x.group === p.group)) {
        _spMsg(`预设「${name}」已存在`);
        return;
      }
      p.name = name;
      _spWrite(node, data);
      refreshGear(node);
    });
  });
  addItem("✕ 删除当前预设", "", false, () => {
    if (data.presets.length <= 1) {
      _spMsg("至少保留一个预设");
      return;
    }
    const cur = data.presets.find((x) => _spKey(x) === data.current);
    _spConfirm(`删除预设「${cur ? cur.name : data.current}」？`, () => {
      data.presets = data.presets.filter((x) => _spKey(x) !== data.current);
      data.current = _spKey(data.presets[0]);
      _spWrite(node, data);
      const p = data.presets.find((x) => _spKey(x) === data.current);
      if (p) _spApply(node, p);
      refreshGear(node);
    });
  });

  document.body.appendChild(menu);
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - 8) + "px";
    menu.style.left = Math.min(r.left, window.innerWidth - 280) + "px";
  }
  setTimeout(() => {
    document.addEventListener("click", function _once() {
      close();
      document.removeEventListener("click", _once);
    });
  }, 0);
}

function refreshGear(node) {
  const btn = node._spGearBtn;
  if (!btn) return;
  const d = _spData(node);
  if (!d) { btn.textContent = "⚙ 预设"; return; }
  const p = d.presets.find((x) => _spKey(x) === d.current);
  btn.textContent = p ? `⚙ ${p.name}` : "⚙ 预设";
}

app.registerExtension({
  name: "DeciiaSamplerPreset",
  nodeCreated(node) {
    if (node.comfyClass !== "DeciiaSamplerPreset") return;

    if (!node._spData) node._spData = { current: "通用", presets: [{
      name: "通用", group: "通用",
      sampler_name: "euler", scheduler: "beta", steps: 4, denoise: 1.0,
    }] };

    // ⚙ 菜单按钮（挪到节点最上方）
    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:6px;align-items:center;margin:2px 0;";
    const gear = document.createElement("button");
    gear.textContent = "⚙ 预设";
    gear.style.cssText = "cursor:pointer;padding:3px 12px;background:#2b2b33;color:#ddd;"
      + "border:1px solid #4a4a55;border-radius:4px;font-size:11px;";
    node._spGearBtn = gear;
    gear.onclick = (ev) => {
      ev.stopPropagation();
      _spMenu(node, gear);
    };
    bar.appendChild(gear);

    const domW = node.addDOMWidget("预设管理", "deciia.sp.bar", bar, { getValue: () => "", setValue: () => {} });
    node._spDomWidget = domW;
    // 挪到节点最上方（加载下拉之前）
    try {
      const idx = node.widgets.indexOf(domW);
      if (idx > 0) {
        node.widgets.splice(0, 0, node.widgets.splice(idx, 1)[0]);
        if (domW.element?.parentElement) {
          domW.element.parentElement.prepend(domW.element);
        }
      }
    } catch (e) {}

    // scheduler=custom 时 steps/denoise 置灰禁用（不参与执行；序列化不受影响）
    function spxSyncCustomVis() {
      const sch = _spWidget(node, "scheduler");
      const isCustom = !!sch && sch.value === "custom";
      for (const k of ["steps", "denoise"]) {
        const w = _spWidget(node, k);
        if (!w) continue;
        w.disabled = isCustom;
      }
      const cs = _spWidget(node, "custom_sigmas");
      if (cs) cs.disabled = false;
      if (app.graph) app.graph.setDirtyCanvas(true, true);
    }
    const schW = _spWidget(node, "scheduler");
    if (schW) {
      const origSch = schW.callback;
      schW.callback = function (v) {
        spxSyncCustomVis();
        if (origSch) return origSch.call(this, v);
      };
    }

    // 工作流数据灌入后刷新按钮
    node.onConfigure = () => {
      refreshGear(node);
      spxSyncCustomVis();
    };
    refreshGear(node);
    spxSyncCustomVis();
  },
});
