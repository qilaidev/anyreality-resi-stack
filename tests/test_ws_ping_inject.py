"""Frame-boundary parsing for the CDN keepalive injector.

The injector writes a WebSocket ping into the stream flowing back to the CDN.
That is only safe on a frame boundary: a ping written into the middle of a
partially-forwarded frame corrupts the stream, and the resulting failure looks
exactly like the idle-timeout disconnect the injector exists to prevent — which
would make the fix indistinguishable from the bug.

So the only thing that has to be exactly right is "which prefix of this buffer
is a whole number of frames", and that is what these tests pin down.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ws_ping_inject_under_test", REPO_ROOT / "scripts" / "ws_ping_inject.py"
)
assert spec is not None and spec.loader is not None
injector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(injector)

take = injector.take_ws_frames


def text_frame(payload: bytes) -> bytes:
    """FIN + opcode 1, unmasked, 7-bit length (payload < 126 bytes)."""
    assert len(payload) < 126
    return bytes([0x81, len(payload)]) + payload


class FrameBoundaryTest(unittest.TestCase):
    def test_returns_whole_frames_and_keeps_the_remainder(self) -> None:
        buf = bytearray(text_frame(b"abc") + text_frame(b"de")[:1])
        self.assertEqual(take(buf), text_frame(b"abc"))
        self.assertEqual(bytes(buf), b"\x81")

    def test_returns_nothing_while_a_frame_is_incomplete(self) -> None:
        buf = bytearray(b"\x81\x05par")  # header says 5 bytes, only 3 arrived
        self.assertEqual(take(buf), b"")
        self.assertEqual(bytes(buf), b"\x81\x05par")

    def test_handles_the_16_bit_length_form(self) -> None:
        payload = b"x" * 300
        frame = b"\x81\x7e" + len(payload).to_bytes(2, "big") + payload
        buf = bytearray(frame)
        self.assertEqual(take(buf), frame)
        self.assertEqual(bytes(buf), b"")

    def test_handles_the_64_bit_length_form(self) -> None:
        payload = b"y" * 70000
        frame = b"\x81\x7f" + len(payload).to_bytes(8, "big") + payload
        buf = bytearray(frame + text_frame(b"z"))
        self.assertEqual(take(buf), frame + text_frame(b"z"))

    def test_accounts_for_the_masking_key(self) -> None:
        """Client-to-server frames are masked, adding 4 bytes after the length.
        Ignoring them would make the parser cut frames 4 bytes short and desync
        the stream permanently."""
        masked = b"\x81\x83" + b"\x00\x00\x00\x00" + b"abc"
        buf = bytearray(masked)
        self.assertEqual(take(buf), masked)
        self.assertEqual(bytes(buf), b"")

    def test_refuses_an_absurd_declared_length(self) -> None:
        """A corrupt or hostile length field must not make the injector buffer
        without bound."""
        buf = bytearray(b"\x81\x7f" + (2**40).to_bytes(8, "big") + b"partial")
        self.assertEqual(take(buf), b"")
        self.assertTrue(injector.has_oversized_frame(buf))
        self.assertFalse(injector.has_oversized_frame(bytearray(text_frame(b"ok"))))

    def test_a_ping_can_be_appended_after_the_returned_prefix(self) -> None:
        stream = text_frame(b"one") + text_frame(b"two") + b"\x81\x09incomple"
        buf = bytearray(stream)
        whole = take(buf)
        rebuilt = whole + injector.WS_PING + bytes(buf)
        # Re-parsing the rebuilt stream must find the ping as its own frame,
        # i.e. the injection point really was a boundary.
        reparse = bytearray(rebuilt)
        self.assertEqual(
            take(reparse), text_frame(b"one") + text_frame(b"two") + injector.WS_PING
        )


if __name__ == "__main__":
    unittest.main()
