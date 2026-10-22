from datetime import datetime, date

def today(format):
    return date.today().strftime(format)

def weekday(formatted_date):
    weekday_result = datetime.strptime(formatted_date, "%Y-%m-%d")
    return weekday_result.strftime("%A")