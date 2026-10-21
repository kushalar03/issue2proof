from datetime import date

from calendar_app import add_months


def test_month_end_clamping():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 7, 31), 1) == date(2026, 8, 31)
