import time
import subprocess
from datetime import datetime, date

def today(format):
    return date.today().strftime(format)

def weekday(formatted_date):
    weekday_result = datetime.strptime(formatted_date, "%Y-%m-%d")
    return weekday_result.strftime("%A")

def run_timer(alarm, send_event):
    start = time.time()
    while (elapsed := time.time() - start) < alarm:
        time.sleep(min(10, alarm - elapsed))
        elapsed = time.time() - start
        if elapsed < alarm:
            send_event(f"{int(elapsed)} seconds elapsed")

    send_event("Timer done")
    return

def calculator(expression):
    result = subprocess.run(
        ["bc"],
        input=expression + "\n",    # space is to return expression
        capture_output=True,
        text=True
    )

    if result.returncode != 0 or result.stderr:
        raise ValueError("Invalid expression")

    return result.stdout.strip()