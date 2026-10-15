import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const BASE = "/minimax_h3_t8_deciia/director";
let overlay;
function openDirector(node) {
    if (overlay) { overlay.close(); overlay.remove(); overlay = null; }
    const dialog = document.createElement("dialog");
    dialog.style.cssText = "position:fixed;inset:1vh 1vw;width:98vw;height:98vh;max-width:none;max-height:none;padding:0;border:1px solid #62523c;border-radius:14px;background:#101314;color:#fff;z-index:10000";
    const bar = document.createElement("div");
    bar.style.cssText = "height:42px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;font-size:14px";
    const label = document.createElement("span"); label.textContent = "曜石导演台 · D2a–D2c 真实生成";
    const close = document.createElement("button"); close.textContent = "返回画布";
    close.onclick = () => { dialog.close(); dialog.remove(); overlay = null; };
    bar.append(label, close);
    const frame = document.createElement("iframe");
    frame.title = "曜石导演台"; frame.src = api.apiURL(BASE + "/ui");
    frame.style.cssText = "width:100%;height:calc(100% - 42px);border:0;display:block";
    frame.addEventListener("load", () => { label.textContent = "曜石导演台 · 已连接当前 Core"; });
    frame.addEventListener("error", () => { label.textContent = "曜石导演台 · 页面加载失败，返回画布后可重试"; });
    dialog.append(bar, frame); document.body.append(dialog); dialog.showModal(); overlay = dialog;
    const receive = (event) => {
        if (event.origin !== location.origin || event.source !== frame.contentWindow || !node) return;
        const project = node.widgets?.find(w => w.name === "project_json");
        if (event.data?.type === "t8-director:ready") {
            if (project?.value) {
                try { frame.contentWindow.postMessage({ type: "t8-director:init", project: JSON.parse(project.value) }, location.origin); }
                catch { label.textContent = "节点项目JSON无效，原内容保留，请用项目备份恢复"; }
            }
            return;
        }
        if (event.data?.type !== "t8-director:saved") return;
        const shot = node.widgets?.find(w => w.name === "shot_id");
        if (project) project.value = JSON.stringify(event.data.project);
        if (shot) shot.value = event.data.project.current;
        app.graph?.setDirtyCanvas(true, true);
    };
    window.addEventListener("message", receive);
    dialog.addEventListener("close", () => window.removeEventListener("message", receive), { once: true });
}

function renderDirectorSidebar(el) {
    el.replaceChildren();
    el.dataset.t8DirectorSidebar = "true";
    el.style.cssText = "height:100%;overflow:auto;box-sizing:border-box;padding:16px;color:inherit;font-family:inherit";

    const card = document.createElement("section");
    card.style.cssText = "display:grid;gap:14px;padding:16px;border:1px solid color-mix(in srgb,currentColor 18%,transparent);border-radius:12px;background:color-mix(in srgb,currentColor 5%,transparent)";

    const heading = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = "曜石导演台";
    title.style.cssText = "margin:0 0 6px;font-size:16px;line-height:1.3";
    const summary = document.createElement("p");
    summary.textContent = "统一管理素材、镜头、画幅、声音与生成路线。";
    summary.style.cssText = "margin:0;opacity:.72;font-size:12px;line-height:1.6";
    heading.append(title, summary);

    const open = document.createElement("button");
    open.type = "button";
    open.dataset.action = "open-t8-director";
    open.textContent = "打开导演台";
    open.title = "在宽屏工作区打开曜石导演台";
    open.style.cssText = "width:100%;padding:10px 12px;border:1px solid #7d6848;border-radius:9px;background:#2a241c;color:#f0cf98;font:600 13px/1.2 inherit;cursor:pointer";
    open.addEventListener("click", () => openDirector());

    const hint = document.createElement("p");
    hint.textContent = "需要把项目同步到工作流时，请使用“曜石导演台 / Obsidian Director”节点上的打开按钮。";
    hint.style.cssText = "margin:0;opacity:.58;font-size:11px;line-height:1.55";
    card.append(heading, open, hint);
    el.append(card);
}

app.registerExtension({
    name: "T8.ObsidianDirector.D1",
    nodeCreated(node) {
        if (node.comfyClass !== "MiniMaxH3DirectorProjectDeciia") return;
        node.addWidget("button", "打开曜石导演台", null, () => openDirector(node), { serialize: false });
    },
    setup() {
        // No sidebar tab: the Deciia director is opened from the 工作台
        // (Apps) entry `曜石导演台`, which points at this package's routes.
        // The node-level "打开曜石导演台" button above stays as the fallback.
    }
});
