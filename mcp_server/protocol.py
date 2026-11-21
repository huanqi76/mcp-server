"""Protocol constants and request validation for the 2026-07-28 MCP revision.

That revision has no sessions and no GET stream: every request is a POST, and
the protocol version, method, and tool name are repeated in HTTP headers.
"""

import base64
from typing import Optional

SUPPORTED_VERSIONS = ["2026-07-28"]
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"

INVALID_REQUEST = -32600
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
PARSE_ERROR = -32700

MAX_BODY_BYTES = 1_000_000
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class RpcError(Exception):
    def __init__(self, status, code, message, data=None):
        super().__init__(message)
        self.status, self.code, self.message, self.data = status, code, message, data


def decode_header_value(value: str) -> Optional[str]:
    """Mcp-Name arrives as =?base64?...?= when it is not plain ASCII."""
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    return value


def check_headers(headers, request: dict) -> None:
    """Raise RpcError unless the headers agree with the request body."""
    method = request.get("method")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}

    strict = method != "server/discover"
    header_version = headers.get("MCP-Protocol-Version")
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
            raise RpcError(
                400, UNSUPPORTED_VERSION, f"Unsupported protocol version: {version}",
                {"supported": SUPPORTED_VERSIONS},
            )

    header_method = headers.get("Mcp-Method")
    if problem is None:
        if header_method is None and strict:
            problem = "Mcp-Method header is missing"
        elif header_method is not None and header_method != method:
            problem = f"Mcp-Method '{header_method}' does not match body method '{method}'"

    if problem is None and method == "tools/call":
        header_name = headers.get("Mcp-Name")
        if header_name is None:
            problem = "Mcp-Name header is missing"
        elif decode_header_value(header_name) != params.get("name"):
            problem = f"Mcp-Name '{header_name}' does not match body name '{params.get('name')}'"

    if problem is not None:
        raise RpcError(400, HEADER_MISMATCH, "Header mismatch: " + problem)
