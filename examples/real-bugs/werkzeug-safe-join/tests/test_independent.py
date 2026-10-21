from types import SimpleNamespace
import posixpath
import werkzeug.security as security

def test_reserved_windows_names(monkeypatch):
    monkeypatch.setattr(security, 'os', SimpleNamespace(name='nt',path=posixpath))
    for name in ['CON', 'NUL', 'AUX', 'COM1']:
        assert security.safe_join('trusted', name) is None
    assert security.safe_join('trusted', 'document.txt') == 'trusted/document.txt'
