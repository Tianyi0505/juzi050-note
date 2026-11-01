#!/usr/bin/env python3
"""只读连接本机 Chrome CDP，供 agent 查看学习通页面。"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

CDP_TIMEOUT = 5
CDP_EVALUATION_TIMEOUT_MS = 3000
PAGE_LOAD_TIMEOUT = 15
MAX_PAGE_TEXT = 20000
MAX_HTTP_RESPONSE = 1_000_000
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PLATFORM_SUFFIXES = ("chaoxing.com", "xuexitong.com")
PAGE_SNAPSHOT_EXPRESSION = (
    "({title: document.title || '', "
    f"text: (document.body ? document.body.innerText : '').slice(0, {MAX_PAGE_TEXT + 1})"
    "})"
)


class AgentCLIError(Exception):
    """面向 CLI 用户的安全错误信息。"""


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_cdp_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise AgentCLIError("CDP 地址格式无效") from exc

    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise AgentCLIError("CDP 只允许连接本机 HTTP 地址，例如 http://127.0.0.1:9222")
    return value.rstrip("/")


def is_learning_platform_url(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False

    hostname = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and any(
            hostname == suffix or hostname.endswith("." + suffix)
            for suffix in PLATFORM_SUFFIXES
        )
    )


def sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _request_json(url: str, method: str = "GET") -> Any:
    request = Request(url, method=method, headers={"Accept": "application/json"})
    try:
        opener = build_opener(ProxyHandler({}), _RejectRedirectHandler())
        with opener.open(request, timeout=CDP_TIMEOUT) as response:
            payload = response.read(MAX_HTTP_RESPONSE + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise AgentCLIError("本机 Chrome CDP 不允许 HTTP 重定向") from exc
        raise AgentCLIError("无法访问本机 Chrome CDP；请检查调试端口") from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise AgentCLIError("无法访问本机 Chrome CDP；请检查调试端口") from exc

    if len(payload) > MAX_HTTP_RESPONSE:
        raise AgentCLIError("Chrome CDP 响应过大")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentCLIError("Chrome CDP 返回了无效 JSON") from exc


def _get_targets(cdp_url: str) -> List[Dict[str, Any]]:
    targets = _request_json(cdp_url + "/json/list")
    if not isinstance(targets, list):
        raise AgentCLIError("Chrome CDP 标签列表格式无效")
    return [target for target in targets if isinstance(target, dict)]


def list_tabs(cdp_url: str) -> List[Dict[str, str]]:
    cdp_url = validate_cdp_url(cdp_url)
    result = []
    for target in _get_targets(cdp_url):
        page_url = target.get("url", "")
        if (
            target.get("type") != "page"
            or not isinstance(page_url, str)
            or not is_learning_platform_url(page_url)
        ):
            continue
        target_id = target.get("id")
        if not isinstance(target_id, str) or not target_id:
            continue
        result.append(
            {
                "target_id": target_id,
                "title": str(target.get("title") or ""),
                "url": sanitize_url(page_url),
            }
        )
    return result


def _validate_websocket_url(value: str, cdp_url: str) -> str:
    try:
        parsed = urlsplit(value)
        websocket_port = parsed.port
        cdp_port = urlsplit(cdp_url).port or 80
    except ValueError as exc:
        raise AgentCLIError("Chrome CDP WebSocket 地址无效") from exc

    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "ws"
        or hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or websocket_port != cdp_port
    ):
        raise AgentCLIError("Chrome CDP WebSocket 必须指向相同的本机调试端口")
    return value


class CDPConnection:
    def __init__(self, websocket):
        self.websocket = websocket
        self.next_id = 0
        self.events = []

    def command(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = CDP_TIMEOUT,
    ) -> Dict[str, Any]:
        self.next_id += 1
        command_id = self.next_id
        message = {"id": command_id, "method": method, "params": params or {}}
        deadline = time.monotonic() + timeout
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentCLIError("Chrome CDP 命令超时：" + method)
            self.websocket.settimeout(remaining)
            self.websocket.send(json.dumps(message))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentCLIError("Chrome CDP 命令超时：" + method)
                self.websocket.settimeout(remaining)
                response = json.loads(self.websocket.recv())
                if response.get("method") == "Page.loadEventFired":
                    self.events.append(response)
                    continue
                if response.get("id") != command_id:
                    continue
                if "error" in response:
                    raise AgentCLIError("Chrome 页面命令失败：" + method)
                result = response.get("result", {})
                if not isinstance(result, dict):
                    raise AgentCLIError("Chrome 页面命令返回格式无效")
                return result
        except AgentCLIError:
            raise
        except Exception as exc:
            raise AgentCLIError("Chrome CDP WebSocket 通信失败") from exc
        finally:
            try:
                self.websocket.settimeout(CDP_TIMEOUT)
            except Exception:
                pass

    def wait_for_event(self, method: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            for index, event in enumerate(self.events):
                if event.get("method") == method:
                    del self.events[index]
                    return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentCLIError("等待页面加载超时")
            try:
                self.websocket.settimeout(remaining)
                message = json.loads(self.websocket.recv())
            except Exception as exc:
                raise AgentCLIError("等待页面加载超时") from exc
            finally:
                try:
                    self.websocket.settimeout(CDP_TIMEOUT)
                except Exception:
                    pass
            if message.get("method") == method:
                return
            if message.get("method") == "Page.loadEventFired":
                self.events.append(message)

    def close(self) -> None:
        try:
            self.websocket.close()
        except Exception:
            pass


def _connect_target(cdp_url: str, target: Dict[str, Any]) -> CDPConnection:
    websocket_url = _validate_websocket_url(
        str(target.get("webSocketDebuggerUrl") or ""), cdp_url
    )
    try:
        import websocket
    except ImportError as exc:
        raise AgentCLIError(
            "缺少 websocket-client；请运行 python3 -m pip install -r "
            "学习通脚本/requirements-agent.txt"
        ) from exc

    try:
        socket = websocket.create_connection(
            websocket_url,
            timeout=CDP_TIMEOUT,
            http_no_proxy=["127.0.0.1", "localhost", "::1"],
            redirect_limit=0,
            suppress_origin=True,
        )
    except Exception as exc:
        raise AgentCLIError("无法连接 Chrome 页面调试通道") from exc

    handshake = getattr(socket, "handshake_response", None)
    status = getattr(handshake, "status", getattr(socket, "status", None))
    if status != 101:
        try:
            socket.close()
        except Exception:
            pass
        raise AgentCLIError("Chrome CDP WebSocket 握手状态无效")
    return CDPConnection(socket)


def open_page(cdp_url: str, page_url: str) -> Dict[str, Any]:
    cdp_url = validate_cdp_url(cdp_url)
    if not is_learning_platform_url(page_url):
        raise AgentCLIError("只允许打开 HTTPS 的 chaoxing.com 或 xuexitong.com 页面")

    target = _request_json(cdp_url + "/json/new?about:blank", method="PUT")
    if not isinstance(target, dict) or target.get("type") != "page":
        raise AgentCLIError("Chrome 未能创建新页面")
    target_id = target.get("id")
    if not isinstance(target_id, str) or not target_id:
        raise AgentCLIError("Chrome 新页面缺少 target id")

    connection = _connect_target(cdp_url, target)
    try:
        connection.command("Page.enable")
        result = connection.command("Page.navigate", {"url": page_url})
        if result.get("errorText"):
            raise AgentCLIError("Chrome 无法打开目标页面")
        if result.get("loaderId"):
            connection.wait_for_event("Page.loadEventFired", PAGE_LOAD_TIMEOUT)
        snapshot = _read_snapshot(connection)
    finally:
        connection.close()

    return {"target_id": target_id, **snapshot}


def _remote_value(result: Dict[str, Any]) -> Any:
    if result.get("exceptionDetails"):
        raise AgentCLIError("页面文本读取失败")
    remote = result.get("result")
    if not isinstance(remote, dict):
        raise AgentCLIError("页面读取结果格式无效")
    return remote.get("value")


def _create_isolated_context(connection: CDPConnection) -> Tuple[int, str]:
    connection.command("Page.enable")
    frame_result = connection.command("Page.getFrameTree")
    frame_tree = frame_result.get("frameTree", {})
    frame = frame_tree.get("frame", {}) if isinstance(frame_tree, dict) else {}
    frame_id = frame.get("id") if isinstance(frame, dict) else None
    frame_url = frame.get("url") if isinstance(frame, dict) else None
    if not isinstance(frame_id, str) or not frame_id:
        raise AgentCLIError("无法取得页面主框架")
    if not isinstance(frame_url, str) or not frame_url:
        raise AgentCLIError("无法取得页面地址")

    context = connection.command(
        "Page.createIsolatedWorld",
        {"frameId": frame_id, "worldName": "agent-read-only"},
    )
    context_id = context.get("executionContextId")
    if not isinstance(context_id, int):
        raise AgentCLIError("无法创建页面隔离读取上下文")
    return context_id, frame_url


def _read_snapshot(connection: CDPConnection) -> Dict[str, Any]:
    context_id, page_url = _create_isolated_context(connection)
    if not is_learning_platform_url(page_url):
        raise AgentCLIError("页面跳转到了不允许读取的域名")
    eval_params = {
        "contextId": context_id,
        "returnByValue": True,
        "throwOnSideEffect": True,
        "timeout": CDP_EVALUATION_TIMEOUT_MS,
    }
    command_timeout = CDP_EVALUATION_TIMEOUT_MS / 1000 + 1
    deadline = time.monotonic() + PAGE_LOAD_TIMEOUT
    while True:
        ready_params = dict(eval_params)
        ready_params["expression"] = "document.readyState"
        ready_result = connection.command(
            "Runtime.evaluate", ready_params, timeout=command_timeout
        )
        ready_state = _remote_value(ready_result)
        if ready_state in ("interactive", "complete"):
            break
        if time.monotonic() >= deadline:
            raise AgentCLIError("等待页面加载超时")
        time.sleep(0.1)

    snapshot_params = dict(eval_params)
    snapshot_params.update(
        {"expression": PAGE_SNAPSHOT_EXPRESSION, "awaitPromise": False}
    )
    result = connection.command(
        "Runtime.evaluate", snapshot_params, timeout=command_timeout
    )
    snapshot = _remote_value(result)
    if not isinstance(snapshot, dict):
        raise AgentCLIError("页面未返回可读取文本")

    raw_text = str(snapshot.get("text") or "")
    return {
        "url": sanitize_url(page_url),
        "title": str(snapshot.get("title") or ""),
        "text": raw_text[:MAX_PAGE_TEXT],
        "truncated": len(raw_text) > MAX_PAGE_TEXT,
    }


def read_page(cdp_url: str, target_id: str) -> Dict[str, Any]:
    cdp_url = validate_cdp_url(cdp_url)
    target = next(
        (
            item
            for item in _get_targets(cdp_url)
            if item.get("id") == target_id
            and item.get("type") == "page"
            and is_learning_platform_url(item.get("url", ""))
        ),
        None,
    )
    if target is None:
        raise AgentCLIError("找不到该学习通标签，或页面域名不在允许范围内")

    connection = _connect_target(cdp_url, target)
    try:
        snapshot = _read_snapshot(connection)
    finally:
        connection.close()

    return {"target_id": target_id, **snapshot}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="读取本机 Chrome 学习通页面；open 仅导航，不提供点击、填写或提交命令。"
    )
    parser.add_argument(
        "--cdp-url", default="http://127.0.0.1:9222", help="本机 Chrome CDP 地址"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tabs", help="列出学习通标签（隐藏 URL 查询参数）")
    open_command = commands.add_parser("open", help="在新标签中打开学习通页面")
    open_command.add_argument("url", help="HTTPS 学习通页面 URL")
    read_command = commands.add_parser("read", help="读取标签中的可见页面文本")
    read_command.add_argument("target_id", help="由 tabs 或 open 返回的标签 ID")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cdp_url = validate_cdp_url(args.cdp_url)
        if args.command == "tabs":
            result = {"tabs": list_tabs(cdp_url)}
        elif args.command == "open":
            result = open_page(cdp_url, args.url)
        else:
            result = read_page(cdp_url, args.target_id)
    except AgentCLIError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
