from studydesk import __main__ as entry


def test_server_only_listens_on_localhost(home, monkeypatch):
    calls = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    entry.main()
    assert calls["host"] == "127.0.0.1"
    assert isinstance(calls["port"], int)
