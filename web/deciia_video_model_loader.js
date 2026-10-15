// Deiia 视频模型加载器 · 四合一预设 — 预设管理（LoRA 串同款弹层菜单交互）
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

function _vmlWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

function _vmlData(node) {
  const w = _vmlWidget(node, "presets_json");
  try {
    const d = JSON.parse(w.value || "{}");
    if (Array.isArray(d.presets) && d.presets.length) {
      if (!d.current) d.current = d.presets[0].name;
      return d;
    }
  } catch (e) {}
  return null;
}

function _vmlWrite(node, data) {
  const w = _vmlWidget(node, "presets_json");
  if (w) w.value = JSON.stringify(data);
}

function _vmlCombos(node) {
  return {
    unet_name: _vmlWidget(node, "unet_name"),
    clip_name: _vmlWidget(node, "clip_name"),
    video_vae_name: _vmlWidget(node, "video_vae_name"),
    audio_vae_name: _vmlWidget(node, "audio_vae_name"),
  };
}

function _vmlApply(node, p) {
  const c = _vmlCombos(node);
  for (const [k, w] of Object.entries(c)) {
    if (w && p[k] != null) w.value = p[k];
  }
  app.graph.setDirtyCanvas(true, true);
}

// 弹层菜单（LoRA 串同款）：预设列表 + 新组/改名/复制/删除
function _vmlMenu(node, anchorBtn) {
  const data = _vmlData(node);
  if (!data) return;

  const menu = document.createElement("div");
  menu.style.cssText = "position:fixed;background:#1b1b22;color:#ddd;border:1px solid #4a4a55;"
    + "border-radius:8px;padding:6px 4px;z-index:99999;min-width:220px;"
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
      refreshCurBtn(node);
    });
  });
  addSep();
  addItem("＋ 新组", "", false, () => {
    _vmlAsk("新预设名（如 H3 主力 / H3 备用）", `预设${data.presets.length + 1}`, (name) => {
      if (data.presets.some((p) => p.name === name)) {
        _vmlMsg(`预设「${name}」已存在`);
        return;
      }
      const cur = _vmlCombos(node);
      data.presets.push({
        name,
        unet_name: cur.unet_name?.value || "",
        clip_name: cur.clip_name?.value || "",
        video_vae_name: cur.video_vae_name?.value || "",
        audio_vae_name: cur.audio_vae_name?.value || "",
      });
      data.current = name;
      _vmlWrite(node, data);
      _vmlApply(node, data.presets.find((x) => x.name === name));
      refreshCurBtn(node);
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
      refreshCurBtn(node);
    });
  });
  addItem("⧉ 复制", "", false, () => {
    const src = data.presets.find((x) => x.name === data.current);
    if (!src) return;
    _vmlAsk("复制预设为新名", data.current + "-copy", (name) => {
      if (!name) return;
      if (data.presets.some((x) => x.name === name)) {
        _vmlMsg(`预设「${name}」已存在`);
        return;
      }
      data.presets.push(JSON.parse(JSON.stringify({ ...src, name })));
      data.current = name;
      _vmlWrite(node, data);
      refreshCurBtn(node);
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
      refreshCurBtn(node);
    });
  });

  document.body.appendChild(menu);
  if (anchorBtn) {
    const r = anchorBtn.getBoundingClientRect();
    const top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8);
    const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.top = Math.max(8, top) + "px";
    menu.style.left = Math.max(8, left) + "px";
  }
  setTimeout(() => {
    document.addEventListener("click", function _once() {
      close();
      document.removeEventListener("click", _once);
    });
  }, 0);
}

function refreshCurBtn(node) {
  const btn = node._vmlCurBtn;
  if (btn) {
    const data = _vmlData(node);
    if (data) btn.textContent = "组: " + data.current;
  }
}

app.registerExtension({
  name: "DeciiaVideoModelLoader",
  nodeCreated(node) {
    if (node.comfyClass !== "DeciiaVideoModelLoader") return;

    // 隐藏 presets_json 文本控件（数据由本面板维护）
    const pj = _vmlWidget(node, "presets_json");
    if (pj) { pj.computeSize = () => [0, -4]; pj.hidden = true; }

    const data = _vmlData(node);
    if (!data) return;

    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:6px;align-items:center;margin:2px 0;";
    const cur = document.createElement("button");
    cur.textContent = "组: " + data.current;
    cur.style.cssText = "cursor:pointer;padding:3px 12px;background:#2b2b33;color:#ddd;"
      + "border:1px solid #4a4a55;border-radius:4px;font-size:11px;text-align:left;";
    node._vmlCurBtn = cur;
    cur.onclick = (ev) => {
      ev.stopPropagation();
      _vmlMenu(node, cur);
    };
    bar.appendChild(cur);

    const hint = document.createElement("span");
    hint.textContent = "点击切换 / 管理预设";
    hint.style.cssText = "color:#777;font-size:10px;";
    bar.appendChild(hint);

    node.addDOMWidget("预设", "deciia.vml.bar", bar, { getValue: () => "", setValue: () => {} });

    // 面板挂载后把当前预设应用到 4 个 combo
    setTimeout(() => {
      const p = data.presets.find((x) => x.name === data.current);
      if (p) _vmlApply(node, p);
    }, 50);
  },
});
