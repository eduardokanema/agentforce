"""
Test suite for WebSocket module.
"""
import unittest
import json
import threading
import socket
import struct
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add the project root to the path so we can import agentforce modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agentforce.server.ws import (
    _ws_handshake,
    WsConnection,
    _LOCK,
    _SUBSCRIBERS,
    register,
    unregister,
    broadcast_mission_list,
    broadcast_mission,
    broadcast_stream_line,
    broadcast_task_stream_done,
    broadcast_mission_cost_update,
    broadcast_task_cost_update,
    broadcast_task_attempt_start,
)


class TestWsHandshake(unittest.TestCase):
    """Test WebSocket handshake function."""
    
    def test_successful_handshake(self):
        """Test successful WebSocket handshake."""
        # Create a mock handler
        handler = Mock()
        handler.headers = {'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ=='}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        
        # Call the handshake function
        result = _ws_handshake(handler)
        
        # Verify it succeeded
        self.assertTrue(result)
        
        # Verify response headers
        handler.send_response.assert_called_with(101)
        handler.send_header.assert_any_call('Upgrade', 'websocket')
        handler.send_header.assert_any_call('Connection', 'Upgrade')
        # Sec-WebSocket-Accept should be computed correctly
        # Key: dGhlIHNhbXBsZSBub25jZQ==
        # Expected accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
        handler.send_header.assert_any_call('Sec-WebSocket-Accept', 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')
        handler.end_headers.assert_called_once()

    def test_successful_handshake_case_insensitive_header_lookup(self):
        """Handshake should accept a lower-case header key from dict-like headers."""
        handler = Mock()
        handler.headers = {'sec-websocket-key': 'dGhlIHNhbXBsZSBub25jZQ=='}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()

        result = _ws_handshake(handler)

        self.assertTrue(result)
        handler.send_header.assert_any_call('Sec-WebSocket-Accept', 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')

    def test_public_handshake_alias_matches_private_function(self):
        """The module should expose a public handshake alias for handler wiring."""
        from agentforce.server import ws as ws_module

        handler = Mock()
        handler.headers = {'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ=='}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()

        result = ws_module.handshake(handler)

        self.assertTrue(result)
        handler.send_header.assert_any_call('Sec-WebSocket-Accept', 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')

    def test_handshake_missing_key(self):
        """Test handshake with missing Sec-WebSocket-Key."""
        handler = Mock()
        handler.headers = {}  # No Sec-WebSocket-Key
        
        result = _ws_handshake(handler)
        self.assertFalse(result)


class TestWsConnection(unittest.TestCase):
    """Test WsConnection class."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a mock socket
        self.mock_socket = Mock()
        self.connection = WsConnection(self.mock_socket)
    
    def test_send_text_small_payload(self):
        """Test sending small text message (<=125 bytes)."""
        msg = "Hello, World!"
        self.connection.send_text(msg)
        
        # Verify socket.sendall was called
        self.mock_socket.sendall.assert_called_once()
        
        # Check the frame format
        call_args = self.mock_socket.sendall.call_args[0][0]
        # First byte: FIN=1, opcode=1 (text) = 0x81
        self.assertEqual(call_args[0], 0x81)
        # Second byte: MASK=0, payload length=13
        self.assertEqual(call_args[1], 13)
        # Rest should be the UTF-8 encoded message
        self.assertEqual(call_args[2:], msg.encode('utf-8'))
    
    def test_send_text_medium_payload(self):
        """Test sending medium text message (126-65535 bytes)."""
        # Create a message longer than 125 bytes
        msg = "A" * 200
        self.connection.send_text(msg)
        
        self.mock_socket.sendall.assert_called_once()
        call_args = self.mock_socket.sendall.call_args[0][0]
        
        # First byte: FIN=1, opcode=1 = 0x81
        self.assertEqual(call_args[0], 0x81)
        # Second byte: 126 (indicates extended length)
        self.assertEqual(call_args[1], 126)
        # Bytes 2-3: payload length (200) as 16-bit unsigned int
        self.assertEqual(struct.unpack('!H', call_args[2:4])[0], 200)
        # Bytes 4-: the message
        self.assertEqual(call_args[4:], msg.encode('utf-8'))
    
    def test_recv_text_success(self):
        """Test receiving and unmasking a text frame."""
        # Create a masked frame (as sent by a client)
        msg = "Hello"
        payload = msg.encode('utf-8')
        # For testing, we'll create a properly masked frame
        # Frame format: FIN+OPCODE, MASK+LEN, MASKING_KEY, PAYLOAD
        # Since we're testing the unmasking, we need to create a masked payload
        import random
        masking_key = b'abcd'  # 4-byte masking key
        # Apply masking
        masked_payload = bytes(
            payload[i] ^ masking_key[i % 4]
            for i in range(len(payload))
        )
        # Build frame
        frame = bytearray()
        frame.append(0x81)  # FIN=1, opcode=1
        frame.append(0x80 | len(payload))  # MASK=1, payload length
        frame.extend(masking_key)
        frame.extend(masked_payload)
        
        # Configure mock socket to return our frame in chunks
        self.mock_socket.recv.side_effect = [
            bytes(frame[:2]),  # First 2 bytes (header)
            bytes(frame[2:6]), # Next 4 bytes (masking key)
            bytes(frame[6:])   # Remaining payload
        ]
        
        result = self.connection.recv_text()
        self.assertEqual(result, msg)
    
    def test_recv_text_close_frame(self):
        """Test receiving a close frame returns None."""
        # Close frame: FIN=1, opcode=8, no mask, zero length
        close_frame = struct.pack('!BB', 0x88, 0)  # FIN=1, opcode=8, MASK=0, len=0
        
        self.mock_socket.recv.return_value = close_frame
        
        result = self.connection.recv_text()
        self.assertIsNone(result)
    
    def test_recv_text_connection_closed(self):
        """Test receiving when connection is closed returns None."""
        self.mock_socket.recv.return_value = b''  # Connection closed
        
        result = self.connection.recv_text()
        self.assertIsNone(result)
    
    def test_close(self):
        """Test close method sends close frame."""
        self.connection.close()
        # Should have called sendall with close frame
        self.mock_socket.sendall.assert_called_once()
        # Close frame: FIN=1, opcode=8, no mask, zero length
        expected_frame = struct.pack('!BB', 0x88, 0)
        self.mock_socket.sendall.assert_called_with(expected_frame)
        # Socket close should also be called
        self.mock_socket.close.assert_called_once()


class TestSubscriptionFunctions(unittest.TestCase):
    """Test subscription management functions."""
    
    def setUp(self):
        """Clear subscribers before each test."""
        global _SUBSCRIBERS
        with _LOCK:
            _SUBSCRIBERS.clear()
    
    def test_register_and_unregister(self):
        """Test registering and unregistering a connection."""
        conn = Mock(spec=WsConnection)
        
        # Register connection
        register(conn, "mission1")
        with _LOCK:
            self.assertIn("mission1", _SUBSCRIBERS)
            self.assertIn(conn, _SUBSCRIBERS["mission1"])
        
        # Unregister connection
        unregister(conn, "mission1")
        with _LOCK:
            self.assertNotIn("mission1", _SUBSCRIBERS)  # Should be cleaned up
    
    def test_register_all_missions(self):
        """Test registering for all missions (*)."""
        conn = Mock(spec=WsConnection)
        
        register(conn, "*")
        with _LOCK:
            self.assertIn("*", _SUBSCRIBERS)
            self.assertIn(conn, _SUBSCRIBERS["*"])

    def test_unregister_default_removes_connection_everywhere(self):
        """Default unregister should fully purge a connection."""
        conn = Mock(spec=WsConnection)

        register(conn, "mission1")
        register(conn, "mission2")
        register(conn, "*")

        unregister(conn)

        with _LOCK:
            self.assertEqual(_SUBSCRIBERS, {})
    
    def test_broadcast_mission_list(self):
        """Test broadcasting mission list."""
        conn = Mock(spec=WsConnection)
        register(conn, "*")
        
        summaries = [{"id": "1", "name": "Test Mission"}]
        broadcast_mission_list(summaries)
        
        # Verify send_text was called with JSON message
        conn.send_text.assert_called_once()
        call_args = conn.send_text.call_args[0][0]
        message = json.loads(call_args)
        self.assertEqual(message["type"], "mission_list")
        self.assertEqual(message["missions"], summaries)
    
    def test_broadcast_mission(self):
        """Test broadcasting mission state."""
        conn = Mock(spec=WsConnection)
        register(conn, "mission1")
        
        state = {"status": "running", "progress": 50}
        broadcast_mission("mission1", state)
        
        conn.send_text.assert_called_once()
        call_args = conn.send_text.call_args[0][0]
        message = json.loads(call_args)
        self.assertEqual(message["type"], "mission_state")
        self.assertEqual(message["mission_id"], "mission1")
        self.assertEqual(message["state"], state)
    
    def test_broadcast_stream_line(self):
        """Test broadcasting stream line."""
        conn = Mock(spec=WsConnection)
        register(conn, "mission1")
        
        broadcast_stream_line("mission1", "task1", "Log line", 1)
        
        conn.send_text.assert_called_once()
        call_args = conn.send_text.call_args[0][0]
        message = json.loads(call_args)
        self.assertEqual(message["type"], "stream_line")
        self.assertEqual(message["mission_id"], "mission1")
        self.assertEqual(message["task_id"], "task1")
        self.assertEqual(message["line"], "Log line")
        self.assertEqual(message["seq"], 1)

    def test_broadcast_task_stream_done(self):
        """Test broadcasting task stream completion."""
        conn = Mock(spec=WsConnection)
        register(conn, "mission1")

        broadcast_task_stream_done("mission1", "task1")

        conn.send_text.assert_called_once()
        call_args = conn.send_text.call_args[0][0]
        message = json.loads(call_args)
        self.assertEqual(message["type"], "task_stream_done")
        self.assertEqual(message["mission_id"], "mission1")
        self.assertEqual(message["task_id"], "task1")

    def test_broadcast_cost_and_attempt_events(self):
        """Test the new cost and attempt broadcast payloads."""
        conn = Mock(spec=WsConnection)
        register(conn, "mission1")

        broadcast_mission_cost_update("mission1", 10, 20, 0.5)
        broadcast_task_cost_update("mission1", "task1", 3, 4, 0.1)
        broadcast_task_attempt_start("mission1", "task1", 2)

        self.assertEqual(conn.send_text.call_count, 3)
        payloads = [json.loads(call.args[0]) for call in conn.send_text.call_args_list]
        self.assertEqual(payloads[0]["type"], "mission_cost_update")
        self.assertEqual(payloads[1]["type"], "task_cost_update")
        self.assertEqual(payloads[2]["type"], "task_attempt_start")
    
    def test_broadcast_handles_dead_connections(self):
        """Test that broadcast functions handle dead connections."""
        # Create a connection that will raise OSError on send
        conn = Mock(spec=WsConnection)
        conn.send_text.side_effect = OSError("Connection broken")
        
        register(conn, "*")
        
        # This should not raise an exception
        broadcast_mission_list([{"id": "1"}])
        
        # Connection should have been unregistered
        with _LOCK:
            self.assertNotIn("*", _SUBSCRIBERS)
            # Or if the set exists, it should be empty
            if "*" in _SUBSCRIBERS:
                self.assertEqual(len(_SUBSCRIBERS["*"]), 0)

    def test_broadcast_unregisters_dead_real_connection(self):
        """Test dead real connections are removed after socket failure."""
        mock_socket = Mock()
        mock_socket.sendall.side_effect = OSError("Connection broken")
        conn = WsConnection(mock_socket)

        register(conn, "*")

        broadcast_mission_list([{"id": "1"}])

        with _LOCK:
            self.assertNotIn("*", _SUBSCRIBERS)

    def test_broadcast_uses_unregister_for_dead_connections(self):
        """Broadcasting dead sockets should route cleanup through unregister."""
        conn = Mock(spec=WsConnection)
        conn.send_text.side_effect = OSError("Connection broken")

        register(conn, "mission1")

        with patch("agentforce.server.ws.unregister") as unregister_mock:
            broadcast_mission("mission1", {"status": "running"})

        unregister_mock.assert_called_once_with(conn, "mission1")

    def test_dead_connection_removed_from_all_subscriptions(self):
        """Dead connections should be purged from every subscriber set."""
        mock_socket = Mock()
        mock_socket.sendall.side_effect = OSError("Connection broken")
        conn = WsConnection(mock_socket)

        register(conn, "mission1")
        register(conn, "mission2")
        register(conn, "*")

        broadcast_mission("mission1", {"status": "running"})

        with _LOCK:
            self.assertNotIn("mission1", _SUBSCRIBERS)
            self.assertNotIn("mission2", _SUBSCRIBERS)
            self.assertNotIn("*", _SUBSCRIBERS)


if __name__ == '__main__':
    unittest.main()
