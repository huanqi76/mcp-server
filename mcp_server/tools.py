"""Tool implementations and the registry the server dispatches from."""

import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

MAX_ALARM_SECONDS = 3600
PROGRESS_INTERVAL_SECONDS = 10


class ToolError(Exception):
    """A failure the model should see, returned as an MCP result with isError set."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[dict, Optional[Callable[[int], None]]], str]
    streaming: bool = False
    # Validates arguments before anything runs, so a streaming tool can still
    # fail with a plain JSON error before the event stream opens.
    parse: Callable[[dict], dict] = field(default=lambda args: args)

    def listing(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _today(args, _emit=None):
    fmt = args["format"]
    try:
        return date.today().strftime(fmt)
    except ValueError as exc:
        raise ToolError(f"Invalid format: {exc}") from exc


def _parse_today(args):
    fmt = args.get("format", "%Y-%m-%d")
    if not isinstance(fmt, str) or not fmt:
        raise ToolError("Format must be a non-empty string")
    return {"format": fmt}


def _weekday(args, _emit=None):
    try:
        return datetime.strptime(args["date"], "%Y-%m-%d").strftime("%A")
    except ValueError as exc:
        raise ToolError("Invalid date, use YYYY-MM-DD") from exc


def _parse_weekday(args):
    value = args.get("date")
    if not isinstance(value, str):
        raise ToolError("Date is required and must be a string (YYYY-MM-DD)")
    return {"date": value}


def run_timer(alarm, send_event):
    """Block for `alarm` seconds, calling send_event(elapsed) every ten seconds."""
    start = time.monotonic()
    while (elapsed := time.monotonic() - start) < alarm:
        time.sleep(min(PROGRESS_INTERVAL_SECONDS, alarm - elapsed))
        elapsed = time.monotonic() - start
        if elapsed < alarm:
            send_event(int(elapsed))


def _parse_timer(args):
    alarm = args.get("alarm")
    # type() rather than isinstance(): True is an int in Python
    if type(alarm) is not int or not 1 <= alarm <= MAX_ALARM_SECONDS:
        raise ToolError(f"Alarm must be an integer between 1 and {MAX_ALARM_SECONDS}")
    return {"alarm": alarm}


def _timer(args, emit):
    run_timer(args["alarm"], emit or (lambda _elapsed: None))
    return f"Alarm! {args['alarm']} seconds are up"


def _parse_calculator(args):
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise ToolError("Expression must be non-empty string")
    return {"expression": expression}


def _calculator(args, _emit=None):
    try:
        result = subprocess.run(
            ["bc", "-l"],
            input=args["expression"] + "\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError("Calculation timed out") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise ToolError(str(exc)) from exc

    if result.returncode != 0 or result.stderr:
        raise ToolError("Invalid expression")
    answer = result.stdout.strip()
    if not answer:
        raise ToolError("Expression produced no output")
    return answer


TOOLS = {
    tool.name: tool
    for tool in (
        Tool(
            name="today",
            description="Returns today's date, formatted with strftime.",
            input_schema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "strftime format, e.g. %Y-%m-%d",
                        "default": "%Y-%m-%d",
                        "examples": ["%Y-%m-%d", "%A, %B %d, %Y", "%d/%m/%y"],
                    }
                },
            },
            run=_today,
            parse=_parse_today,
        ),
        Tool(
            name="weekday",
            description="Returns the day of the week for a date, e.g. 2026-10-24 is Saturday.",
            input_schema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date as YYYY-MM-DD",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        "examples": ["2026-07-28", "2000-01-01"],
                    }
                },
                "required": ["date"],
            },
            run=_weekday,
            parse=_parse_weekday,
        ),
        Tool(
            name="timer",
            description="Streams a progress update every 10 seconds until the alarm.",
            input_schema={
                "type": "object",
                "properties": {
                    "alarm": {
                        "type": "integer",
                        "description": "Whole number of seconds",
                        "minimum": 1,
                        "maximum": MAX_ALARM_SECONDS,
                        "examples": [25],
                    }
                },
                "required": ["alarm"],
            },
            run=_timer,
            parse=_parse_timer,
            streaming=True,
        ),
        Tool(
            name="calculator",
            description="Evaluates an arithmetic expression.",
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "An expression as plain text, e.g. (2+3)*4",
                        "examples": ["2+3*4", "(2+3)*4", "2^10", "10/3", "sqrt(2)"],
                    }
                },
                "required": ["expression"],
            },
            run=_calculator,
            parse=_parse_calculator,
        ),
    )
}
