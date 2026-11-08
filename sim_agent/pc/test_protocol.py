import math
import struct
import unittest
from protocol import STATE, COMMAND, command_values


class ProtocolTests(unittest.TestCase):
    def test_wire_offsets(self):
        raw = STATE.pack(b'RVS1', 123, 1.5, *range(15), 3, 456)
        self.assertEqual(len(raw), 144)
        self.assertEqual(struct.unpack_from('<d', raw, 128)[0], 14)
        self.assertEqual(struct.unpack_from('<II', raw, 136), (3, 456))
        command = COMMAND.pack(b'RVC1', 9, 123, 1, *range(8))
        self.assertEqual(len(command), 80)
        self.assertEqual(command_values(command), (9, 123, 1, list(range(8))))

    def test_reject_bad_wire_data(self):
        for magic, mode, value in [(b'FAIL', 1, 0), (b'RVC1', 2, 0),
                                    (b'RVC1', 1, math.nan), (b'RVC1', 1, math.inf)]:
            with self.assertRaises(ValueError):
                command_values(COMMAND.pack(magic, 0, 0, mode, value, *([0]*7)))
        for size in (0, 79, 81, 144):
            with self.assertRaises(ValueError):
                command_values(bytes(size))


if __name__ == '__main__':
    unittest.main()
