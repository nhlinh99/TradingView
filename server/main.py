"""Server cục bộ. Chạy: python -m uvicorn server.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import duckdb
from fastapi import FastAPI

from common import store
from server import bars_api, live_hub, watchlist_api

app = FastAPI(title="tv-local")
app.include_router(bars_api.router)
app.include_router(watchlist_api.router)
app.include_router(live_hub.router)


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    try:
        root = store.data_dir()
    except store.DataDirError as e:
        return {"status": "error", "detail": str(e), "duckdb": duckdb.__version__}
    return {"status": "ok", "duckdb": duckdb.__version__, "data_dir": str(root)}
