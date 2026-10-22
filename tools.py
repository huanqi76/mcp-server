from datetime import date

def today(format):
    return date.today().strftime(format)