from datetime import date

from calendar_app import add_months


def test_thirty_day_month():
    assert add_months(date(2026, 4, 1), 1) == date(2026, 5, 1)
    assert add_months(date(2026, 4, 1), 0) == date(2026, 4, 1)


def test_installed_metadata_and_package_resource():
    import json
    from importlib.metadata import version
    from importlib.resources import files
    assert version('i2p-calendar-example') == '0.1.0'
    assert json.loads(files('calendar_app').joinpath('settings.json').read_text())['calendar'] == 'gregorian'
