// Deiia 视频模型加载器 · 四合一预设 — 预设管理条（新组/改名/复制组/删组）
// 弹层使用页面内自定义实现（浏览器 prompt/alert/confirm 会被拦截）。
import { app } from "../../../scripts/app.js";

function _vmlModal(tag, html, onMount) {
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

function _vmlAsk(tag, title, initial, onOk) {
  _vmlModal(tag, `<div style="margin-bottom:8px;">${title}</div>`, (box, close) => {
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

function _vmlMsg(tag, msg) {
  _vmlModal(tag, `<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
    const ok = document.createElement("button");
    ok.textContent = "知道了";
    ok.style.cssText = "cursor:pointer;padding:3px 14px;background:#3a3a44;color:#ccc;border:none;border-radius:4px;";
    ok.onclick = close;
    box.append(ok);
  });
}

function _vmlConfirm(tag, msg, onOk) {
  _vmlModal(tag, `<div style="margin-bottom:10px;">${msg}</div>`, (box, close) => {
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

function _vmlPresets(node) {
  const w = _vmlWidget(node, "presets_json");
  try {
    const d = JSON.parse(w.value || "{}");
    if (Array.isArray(d.presets) && d.presets.length) return d;
  } catch (e) {}
  return null;
}

function _vmlWritePresets(node, data) {
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

app.registerExtension({
  name: "DeciiaVideoModelLoader",
  nodeCreated(node) {
    if (node.comfyClass !== "DeciiaVideoModelLoader") return;

    // 隐藏 presets_json 文本控件（数据由本面板维护）
    const pj = _vmlWidget(node, "presets_json");
    if (pj) { pj.computeSize = () => [0, -4]; pj.hidden = true; }

    const data = _vmlPresets(node);
    if (!data) return;
    if (!data.current) data.current = data.presets[0].name;

    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:4px;align-items:center;margin:2px 0;flex-wrap:wrap;";
    const sel = document.createElement("select");
    sel.style.cssText = "flex:1;min-width:120px;background:#16161c;color:#eee;border:1px solid #4a4a55;border-radius:4px;padding:2px 4px;font-size:11px;";
    const refreshSel = () => {
      sel.innerHTML = "";
      data.presets.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.name; o.textContent = p.name;
        if (p.name === data.current) o.selected = true;
        sel.appendChild(o);
      });
    };
    refreshSel();
    bar.appendChild(sel);

    const btn = (txt, fn) => {
      const b = document.createElement("button");
      b.textContent = txt;
      b.style.cssText = "cursor:pointer;padding:2px 6px;background:#2b2b33;color:#ddd;border:1px solid #4a4a55;border-radius:4px;font-size:11px;";
      b.onclick = fn;
      return b;
    };

    const applyPreset = (p) => {
      const c = _vmlCombos(node);
      for (const [k, w] of Object.entries(c)) {
        if (w && p[k] != null) {
          w.value = p[k];
        }
      }
      app.graph.setDirtyCanvas(true, true);
    };

    sel.onchange = () => {
      data.current = sel.value;
      _vmlWritePresets(node, data);
      const p = data.presets.find((x) => x.name === sel.value);
      if (p) applyPreset(p);
    };

    bar.appendChild(btn("＋", () => {
      _vmlAsk("vml-new", "新预设名（如 H3 主力 / H3 备用）", `预设${data.presets.length + 1}`, (name) => {
        if (data.presets.some((p) => p.name === name)) {
          _vmlMsg("vml-new-dup", `预设「${name}」已存在`);
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
        _vmlWritePresets(node, data);
        refreshSel();
        sel.value = name;
      });
    }));
    bar.appendChild(btn("✎", () => {
      _vmlAsk("vml-rename", "重命名当前预设", data.current, (name) => {
        const p = data.presets.find((x) => x.name === data.current);
        if (!p) return;
        if (data.presets.some((x) => x.name === name)) {
          _vmlMsg("vml-rename-dup", `预设「${name}」已存在`);
          return;
        }
        p.name = name; data.current = name;
        _vmlWritePresets(node, data); refreshSel();
      });
    }));
    bar.appendChild(btn("⧉", () => {
      const src = data.presets.find((x) => x.name === data.current);
      if (!src) return;
      _vmlAsk("vml-copy", "复制当前预设为新名", data.current + "-copy", (name) => {
        if (data.presets.some((x) => x.name === name)) {
          _vmlMsg("vml-copy-dup", `预设「${name}」已存在`);
          return;
        }
        data.presets.push(JSON.parse(JSON.stringify({ ...src, name })));
        data.current = name;
        _vmlWritePresets(node, data); refreshSel();
      });
    }));
    bar.appendChild(btn("🗑", () => {
      if (data.presets.length <= 1) {
        _vmlMsg("vml-del-min", "至少保留一个预设");
        return;
      }
      _vmlConfirm("vml-del", `删除预设「${data.current}」？`, () => {
        data.presets = data.presets.filter((x) => x.name !== data.current);
        data.current = data.presets[0].name;
        _vmlWritePresets(node, data); refreshSel();
        const p = data.presets.find((x) => x.name === data.current);
        if (p) applyPreset(p);
      });
    }));

    node.addDOMWidget("预设", "deciia.vml.bar", bar, { getValue: () => "", setValue: () => {} });

    // 面板挂载后把当前预设应用到 4 个 combo
    setTimeout(() => {
      const p = data.presets.find((x) => x.name === data.current);
      if (p) applyPreset(p);
    }, 50);
  },
});
