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

    def send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def send_sse_event(self, message):
        self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
        self.wfile.flush()

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
                            },
                            {
                                "name": "weekday",
                                "description": "Return the weekday for given date",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "date": {
                                            "type": "string",
                                            "description": "Date"
                                        }
                                    },
                                "required": ["date"]
                                }
                            },
                            {
                                "name": "timer",
                                "description": "Sends an update every ten seconds until alarm",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "alarm": {
                                            "type": "integer",
                                            "description": "number of seconds before timer"
                                        }
                                    },
                                "required": ["alarm"]
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
                
                elif name == "weekday":
                    date_string = args.get("date")
                    if not isinstance(date_string, str):   
                        # TODO
                        # technically will say "date must be string"
                        # when data field is not included

                        weekday_result = "Date must be a string"
                        is_error = True

                    else:
                        try: 
                            weekday_result = weekday(date_string)
                            is_error = False
                        except ValueError:
                            weekday_result = "Invalid date"
                            is_error = True

                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
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

                    if not isinstance(alarm, int) or alarm < 1:
                        response = {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Alarm must be a positive integer"
                                    }
                                ],
                                "isError": True
                            }
                        }
                        self.send_json(200, response)
                        return

                    else:
                        self.send_sse_headers()
                        run_timer(alarm, self.send_sse_event)
                        self.wfile.flush()
                        self.close_connection = True
                        return


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