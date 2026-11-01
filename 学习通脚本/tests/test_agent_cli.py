import json
import unittest
from types import SimpleNamespace
from unittest import mock

import agent_cli


class FakeConnection:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.commands = []
        self.closed = False

    def command(self, method, params=None, timeout=agent_cli.CDP_TIMEOUT):
        params = params or {}
        self.commands.append((method, params))
        if method == "Page.getFrameTree":
            page_url = (
                self.snapshot.get("url")
                if isinstance(self.snapshot, dict)
                else "https://mooc1.chaoxing.com/work"
            )
            return {
                "frameTree": {
                    "frame": {"id": "frame-1", "url": page_url}
                }
            }
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 7}
        if method == "Runtime.evaluate":
            if params.get("expression") == "document.readyState":
                return {"result": {"value": "complete"}}
            if self.snapshot is None:
                return {"exceptionDetails": {"text": "side effect detected"}}
            return {"result": {"value": self.snapshot}}
        return {}

    def close(self):
        self.closed = True


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.received = []

    def send(self, message):
        self.sent.append(json.loads(message))
        command_id = self.sent[-1]["id"]
        self.received = [
            json.dumps({"method": "Page.loadEventFired", "params": {}}),
            json.dumps({"id": command_id, "result": {"frameId": "frame-1"}}),
        ]

    def recv(self):
        return self.received.pop(0)

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        pass


class AgentCliTests(unittest.TestCase):
    def test_http_redirects_are_disabled_for_cdp_requests(self):
        request = agent_cli.Request("http://127.0.0.1:9222/json/list")
        handler = agent_cli._RejectRedirectHandler()
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "http://example.invalid/"))

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit):
                return b"[]"

        opener = mock.Mock()
        opener.open.return_value = FakeResponse()
        with mock.patch.object(agent_cli, "build_opener", return_value=opener) as builder:
            self.assertEqual(
                agent_cli._request_json("http://127.0.0.1:9222/json/list"), []
            )
        handlers = builder.call_args.args
        self.assertIsInstance(handlers[1], agent_cli._RejectRedirectHandler)

    def test_cdp_and_platform_urls_are_restricted(self):
        self.assertEqual(
            agent_cli.validate_cdp_url("http://127.0.0.1:9222"),
            "http://127.0.0.1:9222",
        )
        for url in ("http://192.168.1.10:9222", "https://127.0.0.1:9222"):
            with self.subTest(url=url):
                with self.assertRaises(agent_cli.AgentCLIError):
                    agent_cli.validate_cdp_url(url)

        self.assertTrue(
            agent_cli.is_learning_platform_url(
                "https://mooc1.chaoxing.com/work?id=synthetic"
            )
        )
        self.assertFalse(
            agent_cli.is_learning_platform_url("https://chaoxing.com.example.invalid/")
        )
        self.assertFalse(agent_cli.is_learning_platform_url("http://mooc1.chaoxing.com/"))

    def test_tabs_filter_domains_and_hide_query_parameters(self):
        targets = [
            {
                "id": "course-1",
                "type": "page",
                "title": "课程",
                "url": "https://mooc1.chaoxing.com/course?id=private",
            },
            {
                "id": "other-1",
                "type": "page",
                "title": "Other",
                "url": "https://example.invalid/",
            },
            {
                "id": "not-page",
                "type": "service_worker",
                "title": "Worker",
                "url": "https://mooc1.chaoxing.com/",
            },
        ]
        with mock.patch.object(agent_cli, "_get_targets", return_value=targets):
            result = agent_cli.list_tabs("http://127.0.0.1:9222")

        self.assertEqual(
            result,
            [
                {
                    "target_id": "course-1",
                    "title": "课程",
                    "url": "https://mooc1.chaoxing.com/course",
                }
            ],
        )

    def test_open_navigates_only_to_validated_platform_url(self):
        target = {
            "id": "page-1",
            "type": "page",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/page-1",
        }
        snapshot = {
            "url": "https://mooc1.chaoxing.com/work?id=private",
            "title": "作业",
            "text": "题目内容",
        }
        connection = FakeConnection(snapshot)
        with mock.patch.object(agent_cli, "_request_json", return_value=target) as request:
            with mock.patch.object(agent_cli, "_connect_target", return_value=connection):
                result = agent_cli.open_page(
                    "http://127.0.0.1:9222",
                    "https://mooc1.chaoxing.com/work?id=private",
                )

        request.assert_called_once_with(
            "http://127.0.0.1:9222/json/new?about:blank", method="PUT"
        )
        navigate = [params for method, params in connection.commands if method == "Page.navigate"]
        self.assertEqual(
            navigate,
            [{"url": "https://mooc1.chaoxing.com/work?id=private"}],
        )
        self.assertEqual(result["url"], "https://mooc1.chaoxing.com/work")
        self.assertNotIn("private", json.dumps(result))
        self.assertTrue(connection.closed)

    def test_websocket_endpoint_must_match_local_cdp_port(self):
        self.assertEqual(
            agent_cli._validate_websocket_url(
                "ws://localhost:9222/devtools/page/1", "http://127.0.0.1:9222"
            ),
            "ws://localhost:9222/devtools/page/1",
        )
        for url in (
            "ws://example.invalid:9222/devtools/page/1",
            "ws://127.0.0.1:9223/devtools/page/1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(agent_cli.AgentCLIError):
                    agent_cli._validate_websocket_url(url, "http://127.0.0.1:9222")

    def test_read_rejects_redirect_outside_learning_platform(self):
        target = {
            "id": "page-3",
            "type": "page",
            "url": "https://mooc1.chaoxing.com/work",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/page-3",
        }
        connection = FakeConnection(
            {
                "url": "https://example.invalid/redirect",
                "title": "Unexpected",
                "text": "must not be returned",
            }
        )
        with mock.patch.object(agent_cli, "_get_targets", return_value=[target]):
            with mock.patch.object(agent_cli, "_connect_target", return_value=connection):
                with self.assertRaises(agent_cli.AgentCLIError):
                    agent_cli.read_page("http://127.0.0.1:9222", "page-3")
        self.assertTrue(connection.closed)

    def test_read_returns_bounded_visible_text_without_url_query(self):
        target = {
            "id": "page-2",
            "type": "page",
            "url": "https://mooc1.chaoxing.com/work?id=private",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/page-2",
        }
        connection = FakeConnection(
            {
                "url": target["url"],
                "title": "作业页",
                "text": "Q" * (agent_cli.MAX_PAGE_TEXT + 1),
            }
        )
        with mock.patch.object(agent_cli, "_get_targets", return_value=[target]):
            with mock.patch.object(agent_cli, "_connect_target", return_value=connection):
                result = agent_cli.read_page("http://127.0.0.1:9222", "page-2")

        self.assertEqual(len(result["text"]), agent_cli.MAX_PAGE_TEXT)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["url"], "https://mooc1.chaoxing.com/work")
        self.assertNotIn("private", json.dumps(result))
        expressions = [
            params["expression"]
            for method, params in connection.commands
            if method == "Runtime.evaluate"
        ]
        self.assertEqual(expressions[-1], agent_cli.PAGE_SNAPSHOT_EXPRESSION)
        evaluations = [
            params
            for method, params in connection.commands
            if method == "Runtime.evaluate"
        ]
        self.assertTrue(all(params["throwOnSideEffect"] for params in evaluations))
        self.assertTrue(all(params["contextId"] == 7 for params in evaluations))
        self.assertTrue(all("timeout" in params for params in evaluations))
        self.assertTrue(connection.closed)

    def test_command_has_total_deadline_with_continuous_events(self):
        class EventFloodWebSocket:
            def send(self, message):
                pass

            def recv(self):
                return json.dumps({"method": "Page.frameNavigated", "params": {}})

            def settimeout(self, timeout):
                pass

            def close(self):
                pass

        connection = agent_cli.CDPConnection(EventFloodWebSocket())
        with mock.patch.object(
            agent_cli.time, "monotonic", side_effect=[0.0, 0.0, 0.6, 1.1]
        ):
            with self.assertRaisesRegex(agent_cli.AgentCLIError, "命令超时"):
                connection.command("Page.enable", timeout=1.0)

    def test_runtime_read_uses_isolated_side_effect_guard_and_fails_closed(self):
        connection = FakeConnection(None)
        with self.assertRaises(agent_cli.AgentCLIError):
            agent_cli._read_snapshot(connection)

        evaluations = [
            params
            for method, params in connection.commands
            if method == "Runtime.evaluate"
        ]
        self.assertEqual(len(evaluations), 2)
        for params in evaluations:
            self.assertEqual(params["contextId"], 7)
            self.assertTrue(params["throwOnSideEffect"])
            self.assertEqual(params["timeout"], agent_cli.CDP_EVALUATION_TIMEOUT_MS)

    def test_connect_target_suppresses_origin_and_rejects_redirects(self):
        cdp_url = "http://127.0.0.1:9222"
        target = {
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/id"
        }
        socket = mock.Mock()
        socket.handshake_response = SimpleNamespace(status=101)
        websocket_module = mock.Mock()
        websocket_module.create_connection.return_value = socket
        with mock.patch.dict("sys.modules", {"websocket": websocket_module}):
            connection = agent_cli._connect_target(cdp_url, target)
        kwargs = websocket_module.create_connection.call_args.kwargs
        self.assertTrue(kwargs["suppress_origin"])
        self.assertEqual(kwargs["redirect_limit"], 0)
        self.assertEqual(socket.handshake_response.status, 101)
        connection.close()
        socket.close.reset_mock()

        socket.handshake_response = SimpleNamespace(status=302)
        websocket_module.create_connection.return_value = socket
        with mock.patch.dict("sys.modules", {"websocket": websocket_module}):
            with self.assertRaises(agent_cli.AgentCLIError):
                agent_cli._connect_target(cdp_url, target)
        socket.close.assert_called_once()

    def test_cdp_connection_matches_response_id_and_skips_events(self):
        websocket = FakeWebSocket()
        connection = agent_cli.CDPConnection(websocket)
        result = connection.command("Page.enable")
        self.assertEqual(result, {"frameId": "frame-1"})
        connection.wait_for_event("Page.loadEventFired", 1)
        self.assertEqual(connection.events, [])
        self.assertEqual(websocket.sent[0]["method"], "Page.enable")


if __name__ == "__main__":
    unittest.main()
