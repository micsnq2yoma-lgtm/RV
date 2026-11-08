"""Protocol error replies remain usable after malformed client requests."""
import unittest

import mujoco
from sim_server import Simulator


class RequestReplies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = Simulator('127.0.0.1')
        cls.snapshot = mujoco.MjData(cls.sim.model)

    def reply(self, line):
        return self.sim.request_reply(line, None, self.snapshot)

    def test_bad_json_then_ping(self):
        for raw in (b'{', b'\xff', b'[]', b'null'):
            with self.subTest(raw=raw):
                reply = self.reply(raw)
                self.assertIsNone(reply['id'])
                self.assertTrue(reply['error'])
                self.assertIn('t', self.reply(b'{"id":3,"op":"ping"}'))

    def test_unknown_operation_preserves_id(self):
        self.assertEqual(self.reply(b'{"id":7,"op":"unsupported"}'),
                         {'id': 7, 'error': 'unknown op'})

    def test_invalid_reset_preserves_id(self):
        reply = self.reply(b'{"id":"reset-check","op":"reset","seed":-1}')
        self.assertEqual(reply['id'], 'reset-check')
        self.assertIn('nonnegative', reply['error'])


if __name__ == '__main__':
    unittest.main()
