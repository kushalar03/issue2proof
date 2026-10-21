from datetime import timedelta

from dateutil.relativedelta import relativedelta


def add_months(day, months):
    return day + timedelta(days=30 * months)
