import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from agentforce.server import ws as ws_module
from agentforce.server.handler import DashboardHandler


class TestDashboardWebSocketHandler(unittest.TestCase):
    def setUp(self):
        with ws_module._LOCK:
            ws_module._SUBSCRIBERS.clear()

    def _make_handler(self, *, path="/", headers=None):
        handler = object.__new__(DashboardHandler)
        handler.path = path
        handler.headers = headers or {}
        handler.connection = object()
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._html = MagicMock()
        handler._err = MagicMock()
        return handler

    def test_do_get_routes_websocket_upgrade_before_other_handlers(self):
        handler = self._make_handler(
            headers={
                "Upgrade": "websocket",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            }
        )
        fake_conn = MagicMock()
        fake_conn.recv_text.return_value = None

        with patch.object(ws_module, "WsConnection", return_value=fake_conn) as ws_conn:
            handler.do_GET()

        ws_conn.assert_called_once_with(handler.connection)

        handler._html.assert_not_called()
        handler._err.assert_not_called()
        handler.send_response.assert_called_with(101)
        handler.send_header.assert_any_call("Upgrade", "websocket")
        handler.send_header.assert_any_call("Connection", "Upgrade")
        handler.end_headers.assert_called_once()
        fake_conn.close.assert_called_once()

    def test_handle_websocket_subscribe_ping_and_cleanup(self):
        handler = self._make_handler(
            headers={"Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}
        )
        fake_conn = MagicMock()
        fake_conn.recv_text.side_effect = [
            json.dumps({"type": "subscribe", "mission_id": "mission-123"}),
            json.dumps({"type": "ping"}),
            json.dumps({"type": "subscribe_all"}),
            None,
        ]

        with patch.object(ws_module, "WsConnection", return_value=fake_conn) as ws_conn, \
                patch.object(ws_module, "register", wraps=ws_module.register) as register, \
                patch.object(ws_module, "unregister", wraps=ws_module.unregister) as unregister:
            handler._handle_websocket()

        ws_conn.assert_called_once_with(handler.connection)
        handler.send_response.assert_called_with(101)
        handler.send_header.assert_any_call("Upgrade", "websocket")
        handler.send_header.assert_any_call("Connection", "Upgrade")
        handler.end_headers.assert_called_once()

        self.assertEqual(fake_conn.send_text.call_args_list, [
            unittest.mock.call(json.dumps({"type": "pong"}))
        ])
        fake_conn.close.assert_called_once()

        self.assertGreaterEqual(register.call_count, 3)
        self.assertEqual(register.call_args_list[0], unittest.mock.call(fake_conn, "*"))
        self.assertIn(unittest.mock.call(fake_conn, "mission-123"), register.call_args_list)
        self.assertIn(unittest.mock.call(fake_conn, "*"), register.call_args_list[1:])
        self.assertGreaterEqual(unregister.call_count, 2)

        with ws_module._LOCK:
            self.assertEqual(ws_module._SUBSCRIBERS, {})
