from werkzeug.security import safe_join

def test_ordinary_path():
    assert safe_join('trusted', 'report.txt') == 'trusted/report.txt'
    assert safe_join('trusted', '../outside') is None


def test_native_linux_device_string_is_ordinary():
    assert safe_join('trusted', 'CON') == 'trusted/CON'
