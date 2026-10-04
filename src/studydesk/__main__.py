"""Start the server. It only ever listens on 127.0.0.1."""

from __future__ import annotations

import uvicorn

from studydesk.config import load_config
from studydesk.server import create_app

HOST = "127.0.0.1"


def main() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host=HOST, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
