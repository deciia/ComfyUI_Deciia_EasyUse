// FileManagerDock（Deiia Easy Use）— 在 DirectorDeck「工作台」dock（.workflow-dock）中注入「文件管理器」入口。
// 公开入口 URL 来自服务端配置（/servicebridge/config 的 public_url，配置在用户目录 service_bridge.json）。
import { app } from "../../../scripts/app.js";

let _publicUrl = null;
let _configLoaded = false;

async function _loadConfig() {
  if (_configLoaded) return _publicUrl;
  _configLoaded = true;
  try {
    const resp = await fetch("/servicebridge/config");
    if (resp.ok) {
      const data = await resp.json();
      _publicUrl = (data.public_url || "").trim();
    }
  } catch (e) {
    console.warn("[FileManagerDock] config fetch failed", e);
  }
  return _publicUrl;
}

app.registerExtension({
  name: "FileManagerDock",
  async setup() {
    const publicUrl = await _loadConfig();

    const ensureButton = (dock) => {
      if (dock.dataset.fmInjected === "1") return;
      dock.dataset.fmInjected = "1";
      if (!publicUrl) return;  // 未配置公开入口时不注入
      const btn = document.createElement("button");
      btn.className = "dock-open-pan";
      btn.innerHTML =
        '🗂️  <span class="dock-label">打开文件管理器</span>' +
        `<span class="dock-hint">${publicUrl.replace(/^https?:\/\//, "")}</span>`;
      btn.title = "打开 OpenList 文件管理器";
      btn.addEventListener("click", () => {
        window.open(publicUrl, "_blank", "noopener");
      });
      dock.appendChild(btn);
    };

    const observer = new MutationObserver(() => {
      document.querySelectorAll(".workflow-dock").forEach(ensureButton);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll(".workflow-dock").forEach(ensureButton);
  },
});
