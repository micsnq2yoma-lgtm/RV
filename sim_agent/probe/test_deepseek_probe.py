import contextlib
import io
import json
import unittest

import httpx
import deepseek_probe as probe


class ProbeTests(unittest.TestCase):
    def run_mock(self, handler):
        self.output = io.StringIO()
        with httpx.Client(base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)) as client:
            with contextlib.redirect_stdout(self.output):
                return probe.run(client, "test-secret-not-real", probe.MODEL, "pc")

    def test_budget_and_success(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path == "/models":
                return httpx.Response(200, json={"data": [{"id": probe.MODEL}]})
            payload = json.loads(request.content)
            message = {"content": "PROBE_OK"}
            if "tools" in payload:
                message = {"tool_calls": [{"function": {"name": "pick", "arguments": '{"color":"red"}'}}]}
            elif "response_format" in payload:
                message = {"content": '{"color":"red","target":"left"}'}
            elif isinstance(payload["messages"][0]["content"], list):
                message = {"content": "red"}
            return httpx.Response(200, json={"choices": [{"message": message}], "usage": {"total_tokens": 25}})
        self.assertEqual(self.run_mock(handler), 0)
        self.assertEqual(len(requests), 10)
        self.assertEqual(json.loads(self.output.getvalue().splitlines()[-1])["successful_samples"], 5)

    def test_auth_stops_and_redacts(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(401, json={"error": "test-secret-not-real"})
        with self.assertRaisesRegex(RuntimeError, "authentication"):
            self.run_mock(handler)
        self.assertEqual(len(seen), 1)
        self.assertNotIn("test-secret-not-real", self.output.getvalue())

    def test_missing_model_no_substitution(self):
        with self.assertRaisesRegex(RuntimeError, "absent"):
            self.run_mock(lambda _: httpx.Response(200, json={"data": [{"id": "different-model"}]}))

    def test_invalid_arguments_rejected(self):
        self.assertFalse(probe.tool_result({"choices": [{"message": {"tool_calls": [
            {"function": {"name": "place", "arguments": '{"target":"left"}'}}]}}]})["correct_first_action"])


if __name__ == "__main__":
    unittest.main()
