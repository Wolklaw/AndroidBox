import io
import struct
import unittest
from unittest import mock

from androidbox import instances, mirror
from androidbox.proto import emulator_controller_pb2 as pb


class Encoding(unittest.TestCase):
    def test_keycode(self):
        message = mirror.keycode_message(mirror.ACTION_DOWN, 66, meta=0x41)
        self.assertEqual(len(message), 14)
        self.assertEqual(struct.unpack(">BBiii", message), (0, 0, 66, 0, 0x41))

    def test_touch_is_32_bytes(self):
        message = mirror.touch_message(mirror.ACTION_MOVE, 3, 10.4, 20.6, 1080, 1920, 1.0)
        self.assertEqual(len(message), 32)
        kind, action, pointer, x, y, width, height, pressure, button, buttons = struct.unpack(">BBqiiHHHii", message)
        self.assertEqual((kind, action, pointer, x, y, width, height, pressure), (2, 2, 3, 10, 21, 1080, 1920, 0xffff))

    def test_text_split_without_breaking_characters(self):
        messages = mirror.text_messages("é" * 200)
        joined = b""
        for message in messages:
            kind, size = struct.unpack(">BI", message[:5])
            self.assertEqual(kind, mirror.INJECT_TEXT)
            self.assertLessEqual(size, mirror.TEXT_LIMIT)
            self.assertEqual(size, len(message) - 5)
            message[5:].decode("utf-8")
            joined += message[5:]
        self.assertEqual(joined.decode("utf-8"), "é" * 200)

    def test_clipboard(self):
        message = mirror.set_clipboard_message("hi")
        self.assertEqual(message, struct.pack(">BqBI", 9, 0, 0, 2) + b"hi")


class Reading(unittest.TestCase):
    def test_device_clipboard(self):
        stream = io.BytesIO(bytes([0]) + struct.pack(">i", 5) + b"hello" + bytes([1]) + struct.pack(">q", 7))
        self.assertEqual(mirror.read_device_message(stream), (0, "hello"))
        self.assertEqual(mirror.read_device_message(stream), (1, 7))
        self.assertIsNone(mirror.read_device_message(stream))

    def test_padding_left_off_rows(self):
        padded = bytes([1] * 6 + [0] * 2 + [2] * 6 + [0] * 2)
        self.assertEqual(mirror.packed_rows(padded, 8, 2, 2), bytes([1] * 6 + [2] * 6))
        self.assertEqual(mirror.packed_rows(bytes(12), 6, 2, 2), bytes(12))

    def test_fit(self):
        self.assertEqual(mirror.fit(1080, 2400, 500, 500), (225, 500))
        self.assertEqual(mirror.fit(2400, 1080, 1000, 2000), (1000, 450))


def bridge(width=1080, height=2400):
    phone = instances.Instance(id="phone", name="Pixel", slot=0, width=width, height=height, device="ABC123")
    with mock.patch("threading.Thread"):
        return mirror.PhoneBridge(phone)


class Translating(unittest.TestCase):
    def test_instance(self):
        phone = instances.Instance(id="phone", name="Pixel", slot=0, device="10.0.0.2:5555")
        self.assertTrue(phone.real)
        self.assertEqual(phone.serial, "10.0.0.2:5555")
        self.assertFalse(instances.Instance(id="box", name="A", slot=0).real)

    def test_touch_down_move_up_in_stream_size(self):
        phone = bridge()
        phone.frame_size = (864, 1920)

        def touch(x, y, pressure):
            event = pb.InputEvent(touch_event=pb.TouchEvent(
                touches=[pb.Touch(x=x, y=y, identifier=1, pressure=pressure)]))
            return [struct.unpack(">BBqiiHHHii", message) for message in phone.translate(event)]

        down = touch(540, 1200, 1)
        self.assertEqual(down[0][1:7], (mirror.ACTION_DOWN, 1, 432, 960, 864, 1920))
        self.assertEqual(touch(1080, 2400, 1)[0][1:5], (mirror.ACTION_MOVE, 1, 863, 1919))
        up = touch(0, 0, 0)
        self.assertEqual(up[0][1:5], (mirror.ACTION_UP, 1, 863, 1919))
        self.assertEqual(touch(0, 0, 0), [])

    def test_keys(self):
        phone = bridge()

        def key(name, kind):
            event = pb.InputEvent(key_event=pb.KeyboardEvent(key=name, eventType=kind))
            return phone.translate(event)

        press = key("GoBack", pb.KeyboardEvent.keypress)
        self.assertEqual([struct.unpack(">BBiii", m)[1:3] for m in press], [(0, 4), (1, 4)])
        key("Shift", pb.KeyboardEvent.keydown)
        held = key("a", pb.KeyboardEvent.keydown)
        self.assertEqual(struct.unpack(">BBiii", held[0])[2:], (29, 0, 0x41))
        key("Shift", pb.KeyboardEvent.keyup)
        self.assertEqual(phone.meta, 0)
        typed = phone.translate(pb.InputEvent(key_event=pb.KeyboardEvent(text="ok")))
        self.assertEqual(typed, mirror.text_messages("ok"))

    def test_devices_leave_emulators_out(self):
        listing = ("List of devices attached\n"
                   "emulator-5580 device product:sdk model:sdk_gphone64 device:emu64x transport_id:1\n"
                   "2A281FDH300ABC device usb:1-2 product:husky model:Pixel_8_Pro device:husky transport_id:2\n"
                   "192.168.1.20:41235 unauthorized transport_id:3\n")
        with mock.patch.object(mirror.emulator, "run", return_value=(0, listing)):
            self.assertEqual(mirror.devices(), [("2A281FDH300ABC", "device", "Pixel 8 Pro"),
                                                ("192.168.1.20:41235", "unauthorized", "192.168.1.20:41235")])

    def test_screen_size_uses_override(self):
        output = "Physical size: 1344x2992\nOverride size: 1008x2244\nPhysical density: 480\nOverride density: 360"
        with mock.patch.object(mirror.emulator, "run", return_value=(0, output)):
            self.assertEqual(mirror.screen_size("x"), (1008, 2244, 360))


if __name__ == "__main__":
    unittest.main()
