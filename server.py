import json
import base64
import subprocess

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from tools import *

SUPPORTED_VERSIONS = ["2026-07-28"]
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"

def decode_header_value(value):
    # Mcp-Name can arrive as =?base64?...?= when it isn't plain ASCII
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    return value

class MCPHandler(BaseHTTPRequestHandler):
    def send_json(self, status, response):
        body = json.dumps(response).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_rpc_error(self, status, request_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data

        self.send_json(status, {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error
        })

    def send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.flush()

    def send_sse_event(self, message):
        # message is a JSON string: either a notification or the final response
        self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
        self.wfile.flush()

    def send_method_not_allowed(self):
        # 2026-07-28 has no GET stream and no sessions, only POST
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.send_method_not_allowed()

    do_DELETE = do_PUT = do_PATCH = do_GET

    def check_headers(self, request):
        method = request.get("method")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}

        strict = method != "server/discover"

        header_version = self.headers.get("MCP-Protocol-Version")
        body_version = meta.get(VERSION_KEY)

        problem = None
        if strict and header_version is None:
            problem = "MCP-Protocol-Version header is missing"
        elif strict and body_version is None:
            problem = f"_meta['{VERSION_KEY}'] is missing from the body"
        elif header_version is not None and body_version is not None and header_version != body_version:
            problem = f"MCP-Protocol-Version '{header_version}' does not match body value '{body_version}'"

        if problem is None:
            version = header_version or body_version
            if version is not None and version not in SUPPORTED_VERSIONS:
                self.send_rpc_error(400, request.get("id"), -32022,       # -32022: double check against the schema
                                    f"Unsupported protocol version: {version}",
                                    {"supported": SUPPORTED_VERSIONS})
                return False

        header_method = self.headers.get("Mcp-Method")
        if problem is None:
            if header_method is None and strict:
                problem = "Mcp-Method header is missing"
            elif header_method is not None and header_method != method:
                problem = f"Mcp-Method '{header_method}' does not match body method '{method}'"

        if problem is None and method == "tools/call":
            header_name = self.headers.get("Mcp-Name")
            if header_name is None:
                problem = "Mcp-Name header is missing"
            elif decode_header_value(header_name) != params.get("name"):
                problem = f"Mcp-Name '{header_name}' does not match body name '{params.get('name')}'"

        if problem is not None:
            self.send_rpc_error(400, request.get("id"), -32020, "Header mismatch: " + problem)
            return False

        return True

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin is not None and urlparse(origin).hostname not in ("localhost", "127.0.0.1", "::1", "compute09.cs.columbia.edu", "compute24.cs.columbia.edu"):
            self.send_rpc_error(403, None, -32600, "Origin not allowed")
            return

        if urlparse(self.path).path not in ("/", "/mcp"):
            self.send_rpc_error(404, None, -32600, "Unknown endpoint, use /mcp")
            return

        try:
            content_length = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            content_length = 0

        if content_length <= 0 or content_length > 1000000:
            self.send_rpc_error(400, None, -32700, "Missing, empty or oversized request body")
            return

        request_body = self.rfile.read(content_length)  # read() expects number of bytes, not a string

        try:
            request = json.loads(request_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_rpc_error(400, None, -32700, "Invalid JSON")
            return

        print("Received request:", request)

        if isinstance(request, dict) and request.get("jsonrpc") == "2.0" and isinstance(request.get("method"), str):
            if "id" not in request:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if not self.check_headers(request):
                return

            if request.get("method") == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "resultType": "complete",
                        "tools": [
                            {
                                "name": "today",
                                "description": "Returns today's date. Default 2026-10-24 via '%Y-%m-%d'",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "format": {
                                            "type": "string",
                                            "description": "Defaults to %Y-%m-%d, %A, %B %d, %Y, ...",
                                            "default": "%Y-%m-%d",
                                            "examples": ["%Y-%m-%d", "%A, %B %d, %Y", "%d/%m/%y"]
                                        }
                                    }
                                }
                            },
                            {
                                "name": "weekday",
                                "description": "Returns the day of the week a date. e.g. 2026-10-24 returns Saturday",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "date": {
                                            "type": "string",
                                            "description": "Date as YYYY-MM-DD, e.g. 2026-07-28",
                                            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                                            "examples": ["2026-07-28", "2000-01-01"]
                                        }
                                    },
                                "required": ["date"]
                                }
                            },
                            {
                                "name": "timer",
                                "description": "Streams a progress update every 10 seconds until alarm",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "alarm": {
                                            "type": "integer",
                                            "description": "Whole number of seconds for alarm",
                                            "minimum": 1,
                                            "maximum": 3600,
                                            "examples": [25]
                                        }
                                    },
                                "required": ["alarm"]
                                }
                            },
                            {
                                "name": "calculator",
                                "description": "Evaluates an arithmetic expression",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "expression": {
                                            "type": "string",
                                            "description": "An expression as plain text, e.g. (2+3)*4",
                                            "examples": ["2+3*4", "(2+3)*4", "2^10", "10/3", "sqrt(2)"]
                                        }
                                    },
                                "required": ["expression"]
                                }
                            }
                        ],
                        "ttlMs": 0,
                        "cacheScope": "private"
                    }
                }
                self.send_json(200, response)
                return

            elif request.get("method") == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                args = params.get("arguments") or {}

                if not isinstance(args, dict):
                    self.send_rpc_error(400, request.get("id"), -32602, "arguments must be an object")
                    return

                if name == "today":
                    format = args.get("format", "%Y-%m-%d")

                    if not isinstance(format, str) or not format:
                        formatted_date = "Format must be a non-empty string"
                        is_error = True
                    else:
                        formatted_date = today(format)
                        is_error = False

                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "resultType": "complete",
                            "content": [
                                {
                                    "type": "text",
                                    "text": formatted_date
                                }
                            ],
                            "isError": is_error
                        }
                    }
                    self.send_json(200, response)

                elif name == "weekday":
                    date_string = args.get("date")
                    if not isinstance(date_string, str):
                        weekday_result = "Date is required and must be a string (YYYY-MM-DD)"
                        is_error = True

                    else:
                        try:
                            weekday_result = weekday(date_string)
                            is_error = False
                        except ValueError:
                            weekday_result = "Invalid date, use YYYY-MM-DD"
                            is_error = True

                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "resultType": "complete",
                            "content": [
                                {
                                    "type": "text",
                                    "text": weekday_result
                                }
                            ],
                            "isError": is_error
                        }
                    }
                    self.send_json(200, response)   # two kinds of error: HTTP error and MCP tool

                elif name == "timer":
                    alarm = args.get("alarm")

                    # type() rather than isinstance(), because True is an int in Python
                    if type(alarm) is not int or alarm < 1 or alarm > 3600:
                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {
                                "resultType": "complete",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Alarm must be an integer between 1 and 3600"
                                    }
                                ],
                                "isError": True
                            }
                        }
                        self.send_json(200, response)
                        return

                    else:
                        # progress notifications are only allowed if the client sent a progressToken
                        progress_token = (params.get("_meta") or {}).get("progressToken")

                        updates = []

                        def send_update(elapsed):
                            text = f"{elapsed} seconds elapsed"
                            updates.append(text)

                            if progress_token is not None:
                                notification = {
                                    "jsonrpc": "2.0",
                                    "method": "notifications/progress",
                                    "params": {
                                        "progressToken": progress_token,
                                        "progress": elapsed,
                                        "total": alarm,
                                        "message": text
                                    }
                                }
                            else:
                                notification = {
                                    "jsonrpc": "2.0",
                                    "method": "notifications/message",
                                    "params": {
                                        "level": "info",
                                        "logger": "timer",
                                        "data": text
                                    }
                                }
                            self.send_sse_event(json.dumps(notification))

                        self.close_connection = True
                        self.send_sse_headers()
                        try:
                            run_timer(alarm, send_update)

                            # the last event on the stream is the actual response, with the request's id
                            response = {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "result": {
                                    "resultType": "complete",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "\n".join(updates + [f"Alarm! {alarm} seconds are up"])
                                        }
                                    ],
                                    "isError": False
                                }
                            }
                            self.send_sse_event(json.dumps(response))
                        except (BrokenPipeError, ConnectionResetError):
                            # closing the stream means the client cancelled the request
                            print("Client closed the stream, timer cancelled")
                        return

                elif name == "calculator":
                    expression = args.get("expression")

                    if not isinstance(expression, str) or not expression.strip():
                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {
                                "resultType": "complete",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Expression must be non-empty string"
                                    }
                                ],
                                "isError": True
                            }
                        }
                        self.send_json(200, response)
                        return

                    try:
                        answer = calculator(expression)
                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {
                                "resultType": "complete",
                                "content": [
                                    {
                                        "type": "text",      # not necessarily integer, so keep it a string
                                        "text": answer
                                    }
                                ],
                                "isError": False
                            }
                        }
                        self.send_json(200, response)

                    except (ValueError, subprocess.SubprocessError, OSError) as e:
                        if isinstance(e, subprocess.TimeoutExpired):
                            error_text = "Calculation timed out"
                        else:
                            error_text = str(e)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {
                                "resultType": "complete",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": error_text
                                    }
                                ],
                                "isError": True
                            }
                        }
                        self.send_json(200, response)

                else:
                    # unknown tool: HTTP 404 plus a JSON-RPC error (-32602 invalid params)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32602,
                            "message": f"Unknown tool: {name}"
                        }
                    }
                    self.send_json(404, response)
                    return

            elif request.get("method") == "server/discover":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "resultType": "complete",
                        "supportedVersions": SUPPORTED_VERSIONS,
                        "capabilities": {
                            "tools": {},
                            "logging": {}
                        },
                        "_meta": {
                            "io.modelcontextprotocol/serverInfo": {
                                "name": "my-mcp-server",
                                "version": "1.0.0"
                            }
                        }
                    }
                }

                self.send_json(200, response)
                return

            else:
                # any method we don't implement
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),    # same id for request and response
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {request.get('method')}"
                    }
                }
                self.send_json(404, response)
                return

        else:
            rid = request.get("id") if isinstance(request, dict) else None
            self.send_rpc_error(400, rid, -32600, "Invalid Request")

server = ThreadingHTTPServer(("0.0.0.0", 8124), MCPHandler)
server.serve_forever()