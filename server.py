import json

from http.server import HTTPServer, SimpleHTTPRequestHandler

from tools import *

class MCPHandler(SimpleHTTPRequestHandler):
    def send_json(self, status, response):
        body = json.dumps(response).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        response = {
            "message": "Hello World!"
        }

        self.send_json(200, response)
    
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length"))
        request_body = self.rfile.read(content_length)  # read() expects number of bytes, not a string

        try:
            request = json.loads(request_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        print("Received request:", request)

        if request.get("jsonrpc") == "2.0":
            if request.get("method") == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "protocolVersion": "2026-07-28",
                        "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                        },
                        "serverInfo": {
                        "name": "my-mcp-server",
                        "version": "1.0.0"
                        }
                    }
                    }
                self.send_json(200, response)
                return

            elif request.get("method") == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "today",
                                "description": "Return today's date",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "format": {
                                        "type": "string",
                                        "description": "strftime() string"
                                        }
                                    },
                                "required": ["format"]
                                }
                            }
                        ]
                    }
                }
                self.send_json(200, response)
                return

            elif request.get("method") == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})

                if name == "today":
                    format = args.get("format")
                    formatted_date = today(format)

                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                                "content": [
                            {
                                "type": "text",
                                "text": formatted_date
                            }
                        ],
                        "isError": False
                        }
                    }
                    self.send_json(200, response)

                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32601,
                            "message": "Tool not found"
                        }
                    }
                    self.send_json(404, response)
                    return

            elif request.get("method") == "unknown_method":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32601,
                        "message": "Method not found"
                    }
                    }
                self.send_json(404, response)
                return

            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),    # same id for request and response
                    "result": {
                        "message": "Hello World!"
                    }
                }

                self.send_json(200, response)

        else:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request"
                }
            }
            self.send_json(400, response)

server = HTTPServer(("localhost", 8000), MCPHandler)
server.serve_forever()