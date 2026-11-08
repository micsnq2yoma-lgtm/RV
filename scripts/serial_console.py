#!/usr/bin/env python3
"""Timestamped serial capture and framed POSIX-shell commands (requires pyserial).

Examples (place connection options before the mode):
  python scripts/serial_console.py --port COM3 --log logs/boot.log \
      --timeout 180 capture --until 'login:|# $|=> $'
  python scripts/serial_console.py --port COM3 --log logs/info.log exec 'uname -a'

Capture never transmits. Exec requires an already logged-in POSIX shell; it does
not log in, interrupt a command, or send a break on timeout. Shell commands run
in a child shell, so working-directory/environment changes do not persist.
"""

import argparse
import codecs
from datetime import datetime
from pathlib import Path
import re
import secrets
import shlex
import sys
import time


DEFAULT_PROMPT = r"(?m)^[^\r\n]*[#$] ?\r?$"
MAX_BUFFER = 16 * 1024 * 1024


class ConsoleTimeout(Exception):
    """No requested serial response before the deadline."""


class TimestampLog:
    """Append received text with a host timestamp on every line, including tails."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a", encoding="utf-8", newline="")
        self.decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
        self.line_start = True
        # A previous interrupted process may have left an unterminated line.
        if path.stat().st_size:
            with path.open("rb") as previous:
                previous.seek(-1, 2)
                if previous.read(1) != b"\n":
                    self.file.write("\n")

    def _write_text(self, text):
        for part in text.splitlines(keepends=True):
            if self.line_start:
                stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                self.file.write(f"[{stamp}] ")
            self.file.write(part)
            self.line_start = part.endswith("\n")
        self.file.flush()

    def write(self, data):
        self._write_text(self.decoder.decode(data))

    def close(self):
        self._write_text(self.decoder.decode(b"", final=True))
        if not self.line_start:
            self.file.write("\n")
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_chunk(connection, log):
    data = connection.read(min(max(connection.in_waiting, 1), 65536))
    if data:
        log.write(data)
    return data


def capture(connection, log, until, timeout, emit):
    """Receive only; return after a regex match or raise on timeout."""
    decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
    deadline = time.monotonic() + timeout
    received = ""
    while time.monotonic() < deadline:
        data = read_chunk(connection, log)
        if not data:
            continue
        text = decoder.decode(data)
        emit(text)
        received = (received + text)[-MAX_BUFFER:]
        if until.search(received):
            return
    emit(decoder.decode(b"", final=True))
    raise ConsoleTimeout("capture timed out before the requested pattern appeared")


def execute(connection, log, command, prompt, timeout, emit, token=None):
    """Return remote status after both a unique full-line marker and a prompt."""
    token = token or secrets.token_hex(12)
    begin = f"__RV_BEGIN_{token}__"
    begin_pattern = re.compile(r"(?m)^" + re.escape(begin) + r"\r?$\n")
    end_pattern = re.compile(r"(?m)^__RC=([0-9]{1,3})__" + token + r"\r?$\n")
    # Quoting keeps multiline commands and embedded quotes inside the child shell.
    # Full-line markers cannot be mistaken for the terminal's command echo.
    wire = (f"printf '\\n{begin}\\n'; sh -c {shlex.quote(command)}; "
            f"__rv_rc=$?; printf '\\n'; echo __RC=${{__rv_rc}}__{token}\n").encode("utf-8")
    written = connection.write(wire)
    if written != len(wire):
        raise OSError("incomplete serial command write; remote execution is uncertain")
    # Do not flush/reset the input buffer: pending board output belongs in the log.
    decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
    deadline = time.monotonic() + timeout
    received = ""
    output_start = None
    end_match = None
    while time.monotonic() < deadline:
        data = read_chunk(connection, log)
        if not data:
            continue
        received += decoder.decode(data)
        if len(received) > MAX_BUFFER:
            raise OSError("command response exceeded 16 MiB; full received data is in the log")
        if output_start is None:
            match = begin_pattern.search(received)
            if match:
                output_start = match.end()
        if output_start is not None and end_match is None:
            end_match = end_pattern.search(received, output_start)
        if end_match is not None and prompt.search(received[end_match.end():]):
            output = received[output_start:end_match.start()]
            # Remove exactly the separator added by printf, even if the command
            # itself did not end its output with a newline.
            output = output[:-2] if output.endswith("\r\n") else output[:-1]
            emit(output)
            return int(end_match.group(1))
    state = "return-code marker" if end_match is None else "shell prompt after return code"
    raise ConsoleTimeout(f"exec timed out waiting for {state}; see received data in --log")


def positive_number(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def regex(value):
    try:
        return re.compile(value)
    except re.error as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def configure_output(stream):
    """Keep received Unicode printable even under legacy Windows pipe encodings."""
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace", newline="")


def main(argv=None):
    configure_output(sys.stdout)
    configure_output(sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True, help="COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--log", required=True, help="append-only received-text log")
    parser.add_argument("--timeout", type=positive_number, default=30)
    modes = parser.add_subparsers(dest="mode", required=True)
    capture_parser = modes.add_parser("capture", help="read only, without sending any bytes")
    capture_parser.add_argument("--until", type=regex, default=regex(r"login:|# $|=> $"))
    exec_parser = modes.add_parser("exec", help="execute in an already logged-in POSIX shell")
    exec_parser.add_argument("command")
    exec_parser.add_argument("--prompt", type=regex, default=regex(DEFAULT_PROMPT))
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.mode == "exec" and "\x00" in args.command:
        parser.error("command cannot contain NUL")
    try:
        import serial
    except ImportError:
        print("pyserial is required: python -m pip install pyserial", file=sys.stderr)
        return 2
    connection = serial.Serial(port=None, baudrate=args.baud, timeout=0.1,
                               write_timeout=2, xonxoff=False, rtscts=False, dsrdtr=False)
    # Set these before open. Some USB drivers can still pulse control lines on open.
    connection.dtr = False
    connection.rts = False
    connection.port = args.port
    try:
        with connection:
            with TimestampLog(args.log) as log:
                def emit(text):
                    sys.stdout.write(text)
                    sys.stdout.flush()

                print(f"serial ready: {args.port} {args.baud} 8N1; mode={args.mode}",
                      file=sys.stderr, flush=True)
                if args.mode == "capture":
                    capture(connection, log, args.until, args.timeout, emit)
                    return 0
                result = execute(connection, log, args.command, args.prompt, args.timeout, emit)
                print(f"remote exit status: {result}", file=sys.stderr)
                return result
    except ConsoleTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        print("host interrupted; no interrupt was sent to the board", file=sys.stderr)
        return 130
    except (serial.SerialException, OSError) as exc:
        print(f"serial error: {exc}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main())
