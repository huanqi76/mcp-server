import json

from http.server import HTTPServer, SimpleHTTPRequestHandler

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

        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),    # same id for request and response
            "result": {
                "message": "Hello World!"
            }
        }

        self.send_json(200, response)

server = HTTPServer(("localhost", 8000), MCPHandler)
server.serve_forever()