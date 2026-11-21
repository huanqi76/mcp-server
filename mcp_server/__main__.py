"""Run with: python -m mcp_server [--host HOST] [--port PORT]"""

import argparse
import logging
import os
from http.server import ThreadingHTTPServer

from .handler import MCPHandler


def make_server(host="127.0.0.1", port=10037, allowed_origins=()):
    handler = type("Handler", (MCPHandler,), {"allowed_origins": tuple(allowed_origins)})
    return ThreadingHTTPServer((host, port), handler)


def main():
    parser = argparse.ArgumentParser(prog="mcp_server", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: loopback only)")
    parser.add_argument("--port", type=int, default=10037)
    parser.add_argument(
        "--allow-origin", action="append", default=[], metavar="HOSTNAME",
        help="extra hostname allowed in the Origin header; repeatable",
    )
    args = parser.parse_args()

    origins = args.allow_origin + [o for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = make_server(args.host, args.port, origins)
    logging.info("Listening on http://%s:%d/mcp", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
