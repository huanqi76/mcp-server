import os
import time
import subprocess
from datetime import datetime, date

def today(format):
    return date.today().strftime(format)

def weekday(formatted_date):
    weekday_result = datetime.strptime(formatted_date, "%Y-%m-%d")
    return weekday_result.strftime("%A")

def run_timer(alarm, send_event):
    start = time.monotonic()
    while (elapsed := time.monotonic() - start) < alarm:
        time.sleep(min(10, alarm - elapsed))
        elapsed = time.monotonic() - start
        if elapsed < alarm:
            send_event(int(elapsed))
    return

def calculator(expression):
    result = subprocess.run(
        ["bc", "-l"],              
        input=expression + "\n",
        capture_output=True,
        text=True,
        timeout=5
        )
 
    if result.returncode != 0 or result.stderr:
        raise ValueError("Invalid expression")
 
    answer = result.stdout.strip()
    if not answer:
        raise ValueError("Expression produced no output")
 
    return answer