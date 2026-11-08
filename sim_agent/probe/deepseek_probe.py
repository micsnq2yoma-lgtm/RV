"""Bounded DeepSeek capability probe; never logs headers or credentials."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import statistics
import struct
import time
import zlib

import httpx

MODEL = "DeepSeek-V4.1-Flash-1017"
TOOLS = [{"type": "function", "function": {"name": name, "description": desc,
          "parameters": {"type": "object", "properties": {arg: {"type": "string"}},
                         "required": [arg], "additionalProperties": False}}}
         for name, arg, desc in [("pick", "color", "Pick a block by color"),
                                ("place", "target", "Place the held block in a tray")]]


def red_png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", 64, 64, 8, 2, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 64) * 64)) + chunk(b"IEND", b"")


def tool_result(body):
    try:
        calls = body["choices"][0]["message"].get("tool_calls", [])
        valid = bool(calls) and calls[0]["function"]["name"] == "pick" and json.loads(
            calls[0]["function"]["arguments"]) == {"color": "red"}
        return {"tool_calls": calls, "correct_first_action": valid}
    except (KeyError, TypeError, ValueError, IndexError):
        return {"correct_first_action": False}


def run(client, key, model, location):
    count = 0

    def emit(value):
        # Defense in depth: even an API echo cannot disclose the key.
        print(json.dumps(value, ensure_ascii=False).replace(key, "<REDACTED>"), flush=True)

    def request(label, path, payload=None):
        nonlocal count
        if count >= 20:
            raise RuntimeError("request budget exhausted")
        count += 1
        start = time.perf_counter()
        try:
            response = client.request("GET" if payload is None else "POST", path, json=payload)
        except httpx.HTTPError as error:
            emit({"test": label, "seconds": time.perf_counter()-start,
                  "error_type": type(error).__name__, "conclusion": "transport_failed"})
            raise RuntimeError("transport failed; no automatic retries") from None
        elapsed = time.perf_counter()-start
        try:
            body = response.json()
        except ValueError:
            body = {"error": "non-JSON response (body omitted)"}
        emit({"test": label, "location": location, "http_status": response.status_code,
              "seconds": elapsed, "usage": body.get("usage") if isinstance(body, dict) else None,
              "response": body})
        if response.status_code in (401, 403):
            raise RuntimeError("authentication rejected; stopped without retry")
        return response.status_code, body, elapsed

    status, body, _ = request("models", "/models")
    if status != 200:
        raise RuntimeError("model discovery failed")
    ids = [item["id"] for item in body.get("data", [])]
    emit({"model_ids": ids, "requested_model": model})
    if model not in ids:
        raise RuntimeError("requested model absent; ask maintainer, do not substitute")

    def chat(label, content, **extra):
        return request(label, "/chat/completions", {"model": model, "max_tokens": 512,
                       "messages": [{"role": "user", "content": content}], **extra})

    status, body, _ = chat("chat", "Reply with exactly PROBE_OK.")
    try:
        correct = body["choices"][0]["message"]["content"].strip() == "PROBE_OK"
    except (KeyError, TypeError, IndexError, AttributeError):
        correct = False
    emit({"test": "chat_check", "http_ok": status == 200, "correct": correct, "expected": "PROBE_OK"})
    scene = ("Scene: red, green, blue blocks on the table. Left and right trays are empty. "
             "Gripper is empty. Put the red block in the left tray. "
             "Call ONLY the next single tool; use English lowercase argument values.")
    times, usages, good = [], [], 0
    # One initial tool probe plus five consecutive timing samples (10 total API requests).
    status, body, _ = chat("tools", scene, tools=TOOLS, tool_choice="auto")
    emit({"test": "tools_check", **tool_result(body), "http_ok": status == 200})
    status, body, _ = chat("json", 'Return a JSON object: {"color":"red","target":"left"}.',
                           response_format={"type": "json_object"})
    try:
        parsed = json.loads(body["choices"][0]["message"]["content"])
    except (KeyError, TypeError, ValueError, IndexError):
        parsed = None
    emit({"test": "json_check", "correct": status == 200 and parsed == {"color": "red", "target": "left"}})
    image = "data:image/png;base64," + base64.b64encode(red_png()).decode()
    status, body, _ = chat("image", [{"type": "text", "text": "What color is this image? Answer with one English color word."},
                                  {"type": "image_url", "image_url": {"url": image}}])
    answer = str(body.get("choices", [{}])[0].get("message", {}).get("content", "")) if isinstance(body, dict) else ""
    emit({"test": "image_check", "red_answer": status == 200 and answer.strip().lower().strip(".") == "red",
          "limitation": "single red-image probe does not establish general vision accuracy"})
    for i in range(5):
        status, body, elapsed = chat("tools_timing_%d" % (i+1), scene, tools=TOOLS, tool_choice="auto")
        valid = status == 200 and tool_result(body)["correct_first_action"]
        emit({"test": "tools_timing_check_%d" % (i+1), "correct": valid})
        if valid:
            good += 1
            times.append(elapsed)
            usages.append(body.get("usage"))
    emit({"summary": "tool_latency_successes_only", "requests": count, "successful_samples": good,
          "mean_s": statistics.mean(times) if times else None,
          "p95_s": sorted(times)[math.ceil(.95*len(times))-1] if times else None,
          "percentile_method": "nearest rank; 5 samples only", "usage": usages})
    return 0 if good == 5 else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", default="/root/.config/rv-agent/deepseek.key")
    parser.add_argument("--key-env", action="store_true", help="PC comparison only: DEEPSEEK_API_KEY")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--location", choices=["board", "pc"], default="board")
    args = parser.parse_args()
    try:
        path = Path(args.key_file)
        if not args.key_env and os.name == "posix" and path.stat().st_mode & 0o077:
            raise RuntimeError("key file must have mode 600")
        key = os.environ.get("DEEPSEEK_API_KEY", "") if args.key_env else path.read_text().strip()
        if not key or any(c.isspace() for c in key):
            raise RuntimeError("missing or invalid key")
        proxy = os.environ.get("HTTPS_PROXY")
        # httpx 0.26 (Ubuntu) and newer releases both support singular proxy.
        with httpx.Client(base_url="https://api.deepseek.com", proxy=proxy,
                          trust_env=False, timeout=90, follow_redirects=False,
                          headers={"Authorization": "Bearer " + key}) as client:
            return run(client, key, args.model, args.location)
    except (OSError, RuntimeError) as error:
        print(json.dumps({"stopped": type(error).__name__, "reason": str(error) if isinstance(error, RuntimeError) else "key file unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
