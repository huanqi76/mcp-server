# mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server in plain Python. No SDK, no dependencies.

It speaks the stateless `2026-07-28` HTTP revision: POST only, no sessions, and the protocol version, method, and tool name in the headers must match the body.

| Tool | Does |
| --- | --- |
| `today` | Today's date in any `strftime` format |
| `weekday` | Day of the week for a `YYYY-MM-DD` date |
| `timer` | Streams a progress event every 10 seconds over SSE |
| `calculator` | Evaluates arithmetic with `bc` |

## Run

```sh
python -m mcp_server            # http://127.0.0.1:10037/mcp
python -m mcp_server --help     # host, port, --allow-origin
```

```sh
curl -s localhost:10037/mcp \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: tools/list' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
```

Binds to loopback by default. Needs Python 3.9+ and `bc`.

## Test

```sh
python -m unittest discover -s tests -t .
```
