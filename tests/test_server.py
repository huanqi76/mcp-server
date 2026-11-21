import http.client
import json
import threading
import unittest

from mcp_server.__main__ import make_server

VERSION = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": VERSION}


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0, allowed_origins=["example.test"])
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, body, headers=None, path="/mcp", raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = body if raw else json.dumps(body)
        conn.request("POST", path, payload, {"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        data = response.read().decode()
        conn.close()
        return response.status, data

    def rpc(self, method, params=None, headers=None, request_id=1, **extra):
        body = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        base = {"MCP-Protocol-Version": VERSION, "Mcp-Method": method}
        status, data = self.post(body, {**base, **(headers or {})}, **extra)
        return status, json.loads(data)

    def call(self, name, arguments=None):
        params = {"name": name, "arguments": arguments or {}, "_meta": META}
        return self.rpc("tools/call", params, {"Mcp-Name": name})

    def text(self, response):
        return response["result"]["content"][0]["text"]

    # -- discovery and listing ------------------------------------------------

    def test_discover_needs_no_version_headers(self):
        status, data = self.post({"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["result"]["supportedVersions"], [VERSION])

    def test_tools_list(self):
        status, response = self.rpc("tools/list", {"_meta": META})
        self.assertEqual(status, 200)
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(names, ["today", "weekday", "timer", "calculator"])

    # -- tools ----------------------------------------------------------------

    def test_weekday(self):
        _, response = self.call("weekday", {"date": "2026-10-24"})
        self.assertEqual(self.text(response), "Saturday")
        self.assertFalse(response["result"]["isError"])

    def test_weekday_rejects_bad_date(self):
        _, response = self.call("weekday", {"date": "not a date"})
        self.assertTrue(response["result"]["isError"])

    def test_today_formats_year(self):
        _, response = self.call("today", {"format": "%Y"})
        self.assertRegex(self.text(response), r"^\d{4}$")

    def test_calculator(self):
        _, response = self.call("calculator", {"expression": "(2+3)*4"})
        self.assertEqual(self.text(response), "20")

    def test_calculator_rejects_garbage(self):
        _, response = self.call("calculator", {"expression": "2 +* 3"})
        self.assertTrue(response["result"]["isError"])

    def test_timer_rejects_out_of_range(self):
        for bad in (0, 3601, True, "5"):
            _, response = self.call("timer", {"alarm": bad})
            self.assertTrue(response["result"]["isError"], bad)

    def test_timer_streams_final_result(self):
        params = {"name": "timer", "arguments": {"alarm": 1}, "_meta": META}
        body = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": params}
        headers = {"MCP-Protocol-Version": VERSION, "Mcp-Method": "tools/call", "Mcp-Name": "timer"}
        status, data = self.post(body, headers)
        self.assertEqual(status, 200)
        events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["id"], 7)
        self.assertIn("Alarm! 1 seconds are up", events[-1]["result"]["content"][0]["text"])

    def test_unknown_tool(self):
        status, response = self.call("nope")
        self.assertEqual(status, 404)
        self.assertEqual(response["error"]["code"], -32602)

    # -- protocol checks ------------------------------------------------------

    def test_missing_version_header(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
        status, data = self.post(body, {"Mcp-Method": "tools/list"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data)["error"]["code"], -32020)

    def test_unsupported_version(self):
        status, response = self.rpc(
            "tools/list", {"_meta": {"io.modelcontextprotocol/protocolVersion": "1999-01-01"}},
            {"MCP-Protocol-Version": "1999-01-01"},
        )
        self.assertEqual((status, response["error"]["code"]), (400, -32022))

    def test_name_header_must_match_body(self):
        params = {"name": "today", "arguments": {}, "_meta": META}
        status, response = self.rpc("tools/call", params, {"Mcp-Name": "weekday"})
        self.assertEqual((status, response["error"]["code"]), (400, -32020))

    def test_base64_name_header(self):
        import base64
        encoded = "=?base64?" + base64.b64encode(b"today").decode() + "?="
        params = {"name": "today", "arguments": {}, "_meta": META}
        status, _ = self.rpc("tools/call", params, {"Mcp-Name": encoded})
        self.assertEqual(status, 200)

    def test_notification_gets_202(self):
        status, data = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, data), (202, ""))

    def test_unknown_method(self):
        status, response = self.rpc("resources/list", {"_meta": META})
        self.assertEqual((status, response["error"]["code"]), (404, -32601))

    def test_invalid_json(self):
        status, data = self.post("{nope", raw=True)
        self.assertEqual((status, json.loads(data)["error"]["code"]), (400, -32700))

    def test_wrong_path(self):
        status, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "x"}, path="/other")
        self.assertEqual(status, 404)

    def test_get_not_allowed(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/mcp")
        response = conn.getresponse()
        self.assertEqual((response.status, response.getheader("Allow")), (405, "POST"))
        conn.close()

    def test_origin_allowlist(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover"}
        self.assertEqual(self.post(body, {"Origin": "http://localhost:3000"})[0], 200)
        self.assertEqual(self.post(body, {"Origin": "https://example.test"})[0], 200)
        self.assertEqual(self.post(body, {"Origin": "https://evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
