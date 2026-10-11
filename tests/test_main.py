from studydesk import __main__ as entry


class FakeServer:
    """Stands in for uvicorn.Server: the first run asks for a restart (as the setup page does), the second just ends."""

    configs = []

    def __init__(self, config):
        self.config = config
        self.should_exit = False
        FakeServer.configs.append(config)

    def run(self):
        app = self.config.app
        if len(FakeServer.configs) == 1:
            app.state.restart_requested = True
            app.state.on_restart()
            assert self.should_exit


def test_server_only_listens_on_localhost_and_restarts_on_request(home, monkeypatch):
    FakeServer.configs = []
    monkeypatch.setattr(entry.uvicorn, "Server", FakeServer)
    entry.main([])
    assert len(FakeServer.configs) == 2  # started again once after the restart request
    assert {c.host for c in FakeServer.configs} == {"127.0.0.1"}
    assert all(isinstance(c.port, int) for c in FakeServer.configs)
