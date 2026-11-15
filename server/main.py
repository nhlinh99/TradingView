"""Server cục bộ. Chạy: python -m uvicorn server.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import duckdb
from fastapi import FastAPI, Request

from common import store
from server import memguard
from server import alerts_api, bars_api, drawings_api, footprint_api, gex_api, heatmap_api, live_hub, pine_api, watchlist_api

@asynccontextmanager
async def _lifespan(_: FastAPI):
    memguard.start()
    yield


app = FastAPI(title="tv-local", lifespan=_lifespan)


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    t = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        memguard.note_request(request.url.path, time.perf_counter() - t)

app.include_router(bars_api.router)
app.include_router(footprint_api.router)
app.include_router(heatmap_api.router)
app.include_router(gex_api.router)
app.include_router(pine_api.router)
app.include_router(drawings_api.router)
app.include_router(alerts_api.router)
app.include_router(watchlist_api.router)
app.include_router(live_hub.router)


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    try:
        root = store.data_dir()
    except store.DataDirError as e:
        return {"status": "error", "detail": str(e), "duckdb": duckdb.__version__}
    return {"status": "ok", "duckdb": duckdb.__version__, "data_dir": str(root), **memguard.snapshot()}
