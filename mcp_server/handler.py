"""HTTP handler: parses a JSON-RPC request and dispatches it."""

import json
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from . import __version__
from .protocol import (
    INVALID_PARAMS, INVALID_REQUEST, LOCAL_HOSTS, MAX_BODY_BYTES, METHOD_NOT_FOUND,
    PARSE_ERROR, SUPPORTED_VERSIONS, RpcError, check_headers,
)
from .tools import TOOLS, ToolError

log = logging.getLogger("mcp_server")


def tool_result(text, is_error=False):
    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


class MCPHandler(BaseHTTPRequestHandler):
    # Hostnames besides localhost allowed in the Origin header. Set by serve().
    allowed_origins: tuple = ()

    # -- low-level output ---------------------------------------------------

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_result(self, request_id, result, status=200):
        self.send_json(status, {"jsonrpc": "2.0", "id": request_id, "result": result})

    def send_rpc_error(self, error: RpcError, request_id=None):
        body = {"code": error.code, "message": error.message}
        if error.data is not None:
            body["data"] = error.data
        self.send_json(error.status, {"jsonrpc": "2.0", "id": request_id, "error": body})

    def send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.flush()

    def send_sse_event(self, message: dict):
        self.wfile.write(f"data: {json.dumps(message)}\n\n".encode("utf-8"))
        self.wfile.flush()

    # -- HTTP verbs ---------------------------------------------------------

    def _method_not_allowed(self):
        # This revision has no GET stream and no sessions, only POST.
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_DELETE = do_PUT = do_PATCH = _method_not_allowed

    def do_POST(self):
        try:
            request = self._read_request()
            self._dispatch(request)
        except RpcError as error:
            self.send_rpc_error(error, getattr(error, "request_id", None))

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    # -- request pipeline ---------------------------------------------------

    def _read_request(self) -> dict:
        origin = self.headers.get("Origin")
        if origin is not None and urlparse(origin).hostname not in (*LOCAL_HOSTS, *self.allowed_origins):
            raise RpcError(403, INVALID_REQUEST, "Origin not allowed")

        if urlparse(self.path).path not in ("/", "/mcp"):
            raise RpcError(404, INVALID_REQUEST, "Unknown endpoint, use /mcp")

        try:
            length = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            raise RpcError(400, PARSE_ERROR, "Missing, empty or oversized request body")

        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RpcError(400, PARSE_ERROR, "Invalid JSON") from None

        if not (isinstance(request, dict) and request.get("jsonrpc") == "2.0"
                and isinstance(request.get("method"), str)):
            error = RpcError(400, INVALID_REQUEST, "Invalid Request")
            error.request_id = request.get("id") if isinstance(request, dict) else None
            raise error
        return request

    def _dispatch(self, request: dict):
        if "id" not in request:  # a notification: acknowledge, no response body
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        request_id = request["id"]
        try:
            check_headers(self.headers, request)
            method = request["method"]
            if method == "server/discover":
                self._discover(request_id)
            elif method == "tools/list":
                self._list_tools(request_id)
            elif method == "tools/call":
                self._call_tool(request_id, request.get("params") or {})
            else:
                raise RpcError(404, METHOD_NOT_FOUND, f"Method not found: {method}")
        except RpcError as error:
            error.request_id = request_id
            raise

    # -- methods ------------------------------------------------------------

    def _discover(self, request_id):
        self.send_result(request_id, {
            "resultType": "complete",
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {}, "logging": {}},
            "_meta": {"io.modelcontextprotocol/serverInfo": {
                "name": "mcp-server", "version": __version__,
            }},
        })

    def _list_tools(self, request_id):
        self.send_result(request_id, {
            "resultType": "complete",
            "tools": [tool.listing() for tool in TOOLS.values()],
            "ttlMs": 0,
            "cacheScope": "private",
        })

    def _call_tool(self, request_id, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise RpcError(400, INVALID_PARAMS, "arguments must be an object")
        tool = TOOLS.get(name)
        if tool is None:
            raise RpcError(404, INVALID_PARAMS, f"Unknown tool: {name}")

        # Two kinds of error: an HTTP/JSON-RPC error (above) and a tool error
        # (below), which is a normal result with isError set.
        try:
            args = tool.parse(args)
            if tool.streaming:
                self._stream_tool(request_id, tool, args, params)
            else:
                self.send_result(request_id, tool_result(tool.run(args, None)))
        except ToolError as error:
            self.send_result(request_id, tool_result(str(error), is_error=True))

    def _stream_tool(self, request_id, tool, args, params):
        # Progress notifications are only allowed if the client sent a progressToken.
        token = (params.get("_meta") or {}).get("progressToken")
        updates = []

        def emit(elapsed):
            text = f"{elapsed} seconds elapsed"
            updates.append(text)
            if token is not None:
                note = {"method": "notifications/progress", "params": {
                    "progressToken": token, "progress": elapsed,
                    "total": args["alarm"], "message": text}}
            else:
                note = {"method": "notifications/message", "params": {
                    "level": "info", "logger": tool.name, "data": text}}
            self.send_sse_event({"jsonrpc": "2.0", **note})

        self.close_connection = True
        self.send_sse_headers()
        try:
            final = tool.run(args, emit)
            # The last event on the stream is the response, carrying the request id.
            text = "\n".join(updates + [final])
            self.send_sse_event({"jsonrpc": "2.0", "id": request_id, "result": tool_result(text)})
        except (BrokenPipeError, ConnectionResetError):
            # Closing the stream means the client cancelled the request.
            log.info("Client closed the stream, %s cancelled", tool.name)
