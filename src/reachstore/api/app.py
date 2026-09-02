from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from reachstore.api.routes import router

# app.py -> api -> reachstore -> src -> repo root
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def assert_loopback(host: str, *, allow_nonlocal: bool) -> None:
    """Refuse to serve on a non-loopback interface.

    There is no authentication in this slice, so the network boundary is the
    only access control there is. Binding 0.0.0.0 on an untrusted network
    exposes the entire store, including private items, to anyone who can reach
    the port.
    """
    if allow_nonlocal:
        return
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError(
        f"refusing to bind non-loopback host {host!r}: there is no authentication. "
        "Set REACHSTORE_ALLOW_NONLOCAL=1 to override deliberately."
    )


def create_app() -> FastAPI:
    app = FastAPI(title="reachstore", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.include_router(router)
    # Mounted last and only if built, so /api/* always wins the route match and
    # the API is fully usable before any frontend exists.
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    assert_loopback(host, allow_nonlocal=os.environ.get("REACHSTORE_ALLOW_NONLOCAL") == "1")
    uvicorn.run(create_app(), host=host, port=port)
