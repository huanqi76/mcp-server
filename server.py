import json

from http.server import HTTPServer, SimpleHTTPRequestHandler

class MCPHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        response = {
            "message": "Hello World!"
        }

        body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def do_POST(self):
        content_length = self.headers.get("Content-Length")

        request_body = self.rfile.read(content_length)

        try:

        response = {
            "message": "POST received"
        }

        body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("localhost", 8000), MCPHandler)
server.serve_forever()