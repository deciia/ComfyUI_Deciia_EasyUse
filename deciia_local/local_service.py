"""ServiceBridge — 代理外部服务并按配置自动拉起。

配置文件（不入 git，放用户目录）：
    <user_dir>/DeciiaEasyUse/service_bridge.json
    结构见包内 service_bridge.example.json；字段：
      autostart: bool          是否在 ComfyUI 启动期拉起服务
      public_url: str          前端 FileManagerDock 使用的公开入口（可为空）
      services: [
        {name, prefix, upstream, root_path, map: "passthrough"|"nexus_bta",
         cwd, command:[...], port, timeout}
      ]
    command 里的 "{python}" 会替换为当前解释器路径。
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from aiohttp import ClientSession, ClientTimeout, web

LOGGER = logging.getLogger("ServiceBridge")

_PLUGIN_ROOT = Path(__file__).resolve().parent


def _user_config_path() -> Path:
    try:
        import folder_paths
        base = folder_paths.get_user_directory()
    except Exception:
        base = os.path.join(os.path.dirname(_PLUGIN_ROOT), "..", "user")
    return Path(base) / "DeciiaEasyUse" / "service_bridge.json"


def _passthrough_map(tail: str, root_path: str) -> str:
    return f"{root_path}/{tail}" if tail else (root_path if root_path.endswith("/") else f"{root_path}/")


def _nexus_bta_map(tail: str, root_path: str) -> str:
    if not tail:
        return root_path if root_path.endswith("/") else f"{root_path}/"
    for direct in ("ui/", "api/", "outputs/"):
        if tail.startswith(direct) or tail.rstrip("/") == direct.rstrip("/"):
            return f"/{tail}"
    if tail.startswith("static/") or tail.rstrip("/") == "static":
        return f"/app/{tail}"
    if tail.startswith("app/") or tail.rstrip("/") == "app":
        return f"/{tail}"
    return f"{root_path}/{tail}"


MAPS: dict[str, Callable[[str, str], str]] = {
    "passthrough": _passthrough_map,
    "nexus_bta": _nexus_bta_map,
}

_HOP_BY_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
})

SERVICE_ROUTES: list[tuple[str, str, str, str, Callable]] = []
SERVICE_LAUNCHERS: list[tuple[str, str, list, int, int]] = []
PUBLIC_URL = ""
_AUTOSTART = True

_subprocesses: dict[str, subprocess.Popen] = {}
_subprocess_status: dict[str, str] = {}
_routes_registered = False


def _load_config() -> None:
    global SERVICE_ROUTES, SERVICE_LAUNCHERS, PUBLIC_URL, _AUTOSTART
    path = _user_config_path()
    if not path.is_file():
        LOGGER.warning(
            "ServiceBridge: 未找到配置 %s —— 服务桥保持未配置状态。"
            "复制包内 service_bridge.example.json 到该路径并按需修改。", path)
        return
    cfg = json.loads(path.read_text(encoding="utf-8"))
    PUBLIC_URL = str(cfg.get("public_url", "") or "")
    _AUTOSTART = bool(cfg.get("autostart", True)) and os.environ.get(
        "DEBRIDGE_AUTOSTART", "1").strip().lower() not in ("0", "false", "no", "off")
    for svc in cfg.get("services", []):
        cmd = [str(c).replace("{python}", sys.executable) for c in svc.get("command", [])]
        SERVICE_ROUTES.append((
            svc["prefix"], svc["upstream"], svc["name"],
            svc.get("root_path", svc["prefix"]), MAPS.get(svc.get("map", "passthrough"), _passthrough_map),
        ))
        SERVICE_LAUNCHERS.append((
            svc["name"], svc.get("cwd", ""), cmd,
            int(svc.get("port", 0)), int(svc.get("timeout", 30)),
        ))
    LOGGER.info("ServiceBridge: loaded %d services from %s", len(SERVICE_ROUTES), path)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def _start_service(name: str, cwd: str, cmd: list, port: int, timeout: int) -> None:
    if not cmd:
        return
    if port and _port_open(port):
        _subprocess_status[name] = "already-running"
        LOGGER.info("ServiceBridge: %s 已在 %s 端口监听（外部实例），不再拉起第二个", name, port)
        return
    _subprocess_status[name] = "starting"
    LOGGER.info("ServiceBridge: starting %s in %s", name, cwd)
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        _subprocesses[name] = proc
    except Exception as exc:
        _subprocess_status[name] = f"failed: {exc}"
        LOGGER.error("ServiceBridge: failed to start %s: %s", name, exc)
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            _subprocess_status[name] = f"exited: {proc.returncode}"
            LOGGER.error("ServiceBridge: %s exited early with code %s", name, proc.returncode)
            return
        if port and _port_open(port):
            _subprocess_status[name] = "ready"
            LOGGER.info("ServiceBridge: %s is ready on port %s", name, port)
            return
        time.sleep(1)
    _subprocess_status[name] = "timeout"
    LOGGER.warning("ServiceBridge: %s did not start within %ss", name, timeout)


def _start_all_services() -> None:
    for name, cwd, cmd, port, timeout in SERVICE_LAUNCHERS:
        t = threading.Thread(
            target=_start_service, args=(name, cwd, cmd, port, timeout),
            name=f"servicebridge-{name.lower().replace(' ', '-')}", daemon=True)
        t.start()


def _shutdown_services() -> None:
    for name, proc in _subprocesses.items():
        if proc.poll() is None:
            LOGGER.info("ServiceBridge: stopping %s", name)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


async def _get_proxy_session() -> ClientSession:
    global _proxy_session, _proxy_session_lock
    if _proxy_session_lock is None:
        _proxy_session_lock = threading.Lock()
    if _proxy_session is None or _proxy_session.closed:
        with _proxy_session_lock:
            if _proxy_session is None or _proxy_session.closed:
                _proxy_session = ClientSession(timeout=ClientTimeout(total=None), auto_decompress=False)
    return _proxy_session


async def _on_comfy_shutdown(_app: web.Application) -> None:
    global _proxy_session
    _shutdown_services()
    if _proxy_session is not None and not _proxy_session.closed:
        await _proxy_session.close()
    _proxy_session = None


def _find_service(path: str):
    for prefix, upstream, label, root_path, path_map in SERVICE_ROUTES:
        if path.startswith(prefix):
            return (prefix, upstream, label, root_path, path_map)
    return None


def _register_routes() -> None:
    global _routes_registered
    if _routes_registered:
        LOGGER.warning("ServiceBridge: routes already registered, skip")
        return
    import server as comfy_server
    prompt_server = comfy_server.PromptServer.instance
    prompt_server.app.on_shutdown.append(_on_comfy_shutdown)
    routes = prompt_server.routes

    @routes.get("/servicebridge/status")
    async def _status(_request: web.Request) -> web.Response:
        services = {}
        for prefix, upstream, label, root_path, _pm in SERVICE_ROUTES:
            proc_status = _subprocess_status.get(label, "unknown")
            try:
                session = await _get_proxy_session()
                async with session.get(f"{upstream}/", timeout=ClientTimeout(total=3)) as resp:
                    services[label] = {"reachable": True, "status": resp.status,
                                       "prefix": prefix, "process": proc_status}
            except Exception as exc:
                services[label] = {"reachable": False, "error": str(exc),
                                   "prefix": prefix, "process": proc_status}
        return web.json_response({"services": services, "public_url": PUBLIC_URL})

    @routes.get("/servicebridge/config")
    async def _config(_request: web.Request) -> web.Response:
        return web.json_response({"public_url": PUBLIC_URL})

    for prefix, upstream, label, root_path, path_map in SERVICE_ROUTES:
        prefix_clean = prefix.rstrip("/")

        @routes.get(prefix_clean)
        async def _redirect(request: web.Request, _p=prefix_clean) -> web.Response:
            raise web.HTTPFound(f"{_p}/")

        @routes.route("*", f"{prefix_clean}/{{tail:.*}}")
        async def _proxy(request: web.Request) -> web.StreamResponse:
            tail = request.match_info["tail"]
            svc = _find_service(request.path)
            if svc is None:
                return web.json_response({"error": "unknown_service"}, status=404)
            _prefix, matched_upstream, _label, _root_path, _path_map = svc
            path = _path_map(tail, _root_path)
            target = f"{matched_upstream}{path}"
            if request.query_string:
                target = f"{target}?{request.query_string}"
            session = await _get_proxy_session()
            headers = {n: v for n, v in request.headers.items()
                       if n.lower() not in _HOP_BY_HOP_HEADERS
                       and n.lower() not in {"host", "content-length"}}
            try:
                upstream_resp = await session.request(
                    request.method, target, headers=headers,
                    data=request.content if request.can_read_body else None,
                    allow_redirects=True)
            except OSError as exc:
                return web.json_response({"error": "service_unreachable", "detail": str(exc)}, status=502)
            resp_headers = {n: v for n, v in upstream_resp.headers.items()
                            if n.lower() not in _HOP_BY_HOP_HEADERS and n.lower() not in {"content-length"}}
            downstream = web.StreamResponse(status=upstream_resp.status,
                                            reason=upstream_resp.reason, headers=resp_headers)
            await downstream.prepare(request)
            try:
                async for chunk in upstream_resp.content.iter_any():
                    await downstream.write(chunk)
            finally:
                upstream_resp.release()
            await downstream.write_eof()
            return downstream


try:
    _load_config()
    if _AUTOSTART and SERVICE_LAUNCHERS:
        _start_all_services()
    else:
        LOGGER.info("ServiceBridge: 自动启动关闭或无服务配置，仅注册反代路由")
    _register_routes()
    _routes_registered = True
    atexit.register(_shutdown_services)
    LOGGER.info("ServiceBridge: registered %d proxy routes", len(SERVICE_ROUTES))
except BaseException:
    LOGGER.exception("ServiceBridge plugin initialization failed")
