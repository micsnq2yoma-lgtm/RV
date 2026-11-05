"""Protocol tests with a simulated serial transport; no board commands are run."""

import io
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import serial_console as console


class FakeSerial:
    def __init__(self, response, chunk_size=1):
        self.response = bytearray(response)
        self.chunk_size = chunk_size
        self.sent = []

    @property
    def in_waiting(self):
        return min(len(self.response), self.chunk_size)

    def read(self, count):
        data = bytes(self.response[:count])
        del self.response[:count]
        return data

    def write(self, data):
        self.sent.append(data)
        return len(data)


class SerialConsoleTests(unittest.TestCase):
    def test_capture_split_utf8_and_prompt_without_transmitting(self):
        port = FakeSerial("Linux 正常\r\nroot@board:~# ".encode())
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "boot.log"
            with console.TimestampLog(path) as log:
                console.capture(port, log, re.compile(r"# $"), 1, output.write)
            self.assertEqual(port.sent, [])
            self.assertIn("正常", path.read_text(encoding="utf-8"))
            self.assertEqual(output.getvalue(), "Linux 正常\r\nroot@board:~# ")

    def test_capture_empty_is_timeout(self):
        with self.assertRaises(console.ConsoleTimeout):
            console.capture(FakeSerial(b""), io.BytesIO(), re.compile("login:"),
                            0.005, lambda value: None)

    def test_exec_ignores_echo_old_markers_and_returns_nonzero(self):
        response = (b"old output\r\n__RC=0__old\r\n"
                    b"# printf '__RV_BEGIN_test__'; echo __RC=$?__test\r\n"
                    b"\r\n__RV_BEGIN_test__\r\nactual output\r\n"
                    b"\r\n__RC=7__test\r\nroot@board:~# ")
        port = FakeSerial(response, chunk_size=3)
        output = io.StringIO()
        status = console.execute(port, io.BytesIO(), "printf 'actual output\\n'; exit 7",
                                 re.compile(console.DEFAULT_PROMPT), 1, output.write,
                                 token="test")
        self.assertEqual(status, 7)
        self.assertEqual(output.getvalue(), "actual output\r\n")
        self.assertEqual(len(port.sent), 1)
        self.assertNotIn(b"\x03", port.sent[0])

    def test_exec_without_output_newline(self):
        response = b"__RV_BEGIN_test__\nx\n__RC=0__test\n# "
        output = io.StringIO()
        result = console.execute(FakeSerial(response), io.BytesIO(), "printf x",
                                 re.compile(console.DEFAULT_PROMPT), 1, output.write,
                                 token="test")
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "x")

    def test_exec_marker_without_prompt_times_out(self):
        response = b"__RV_BEGIN_test__\n\n__RC=0__test\n"
        with self.assertRaisesRegex(console.ConsoleTimeout, "shell prompt"):
            console.execute(FakeSerial(response), io.BytesIO(), "true",
                            re.compile(console.DEFAULT_PROMPT), 0.005,
                            lambda value: None, token="test")

    def test_exec_echo_alone_is_not_success(self):
        response = b"printf '__RV_BEGIN_test__'; echo __RC=0__test\n# "
        with self.assertRaisesRegex(console.ConsoleTimeout, "return-code marker"):
            console.execute(FakeSerial(response), io.BytesIO(), "true",
                            re.compile(console.DEFAULT_PROMPT), 0.005,
                            lambda value: None, token="test")

    @unittest.skipUnless(shutil.which("sh"), "requires a local POSIX sh")
    def test_wire_runs_in_real_posix_shell(self):
        class ShellSerial(FakeSerial):
            def write(self, data):
                result = subprocess.run([shutil.which("sh"), "-s"], input=data,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=5, check=True)
                self.response.extend(result.stdout + b"root@host:~# ")
                return super().write(data)

        cases = [("printf x", "x", 0),
                 ("printf '%s\\n' \"a'b\"\nprintf second", "a'b\nsecond", 0),
                 ("printf 'before exit\\n'; exit 9", "before exit\n", 9)]
        for command, expected, status in cases:
            with self.subTest(command=command):
                output = io.StringIO()
                result = console.execute(ShellSerial(b"", chunk_size=5), io.BytesIO(),
                                         command, re.compile(console.DEFAULT_PROMPT),
                                         5, output.write)
                self.assertEqual(result, status)
                self.assertEqual(output.getvalue(), expected)

    def test_log_appends_and_preserves_partial_lines_and_invalid_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.log"
            for data in (b"first\npartial", b"second\n\xff"):
                with console.TimestampLog(path) as log:
                    log.write(data)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            for line in lines:
                self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2}T.*[+-]\d\d:\d\d\] ")
            self.assertTrue(lines[0].endswith("first"))
            self.assertTrue(lines[1].endswith("partial"))
            self.assertTrue(lines[2].endswith("second"))
            self.assertTrue(lines[3].endswith(r"\xff"))


if __name__ == "__main__":
    unittest.main()
