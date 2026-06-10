"""Console entry: ``python -m gametime.api`` or ``gametime-api``."""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("GAMETIME_API_HOST", "127.0.0.1")
    port = int(os.environ.get("GAMETIME_API_PORT", "8000"))
    reload = os.environ.get("GAMETIME_API_RELOAD", "").lower() in {"1", "true", "yes"}
    uvicorn.run("gametime.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
