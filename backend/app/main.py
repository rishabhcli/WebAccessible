from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import router
from backend.app.config import RuntimeMode, Settings, get_settings
from backend.app.dependencies import AppContainer


def cors_origins(settings: Settings) -> list[str]:
    configured = str(settings.app_public_url).rstrip("/")
    origins = [configured]
    if settings.app_env not in {RuntimeMode.DEVELOPMENT, RuntimeMode.TEST}:
        return origins
    parsed = urlsplit(configured)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return origins
    alternate_host = "127.0.0.1" if parsed.hostname == "localhost" else "localhost"
    port = f":{parsed.port}" if parsed.port is not None else ""
    origins.append(f"{parsed.scheme}://{alternate_host}{port}")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container = AppContainer()
    app.state.container = container
    await container.start()
    try:
        yield
    finally:
        await container.close()


app = FastAPI(
    title="WebAccessible API",
    version="0.1.0",
    description=(
        "User-controlled browser guidance with live Browserbase, EverOS, and Snowflake paths."
    ),
    lifespan=lifespan,
)


@app.exception_handler(KeyError)
async def not_found(_request: Request, error: KeyError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error).strip("'")})


@app.exception_handler(PermissionError)
async def forbidden(_request: Request, error: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(error)})


app.include_router(router)


container_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(container_settings),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
)


web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
assets = web_dist / "assets"
if assets.is_dir():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str) -> FileResponse:
    candidate = (web_dist / path).resolve()
    if web_dist.is_dir() and candidate.is_relative_to(web_dist) and candidate.is_file():
        return FileResponse(candidate)
    index = web_dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return FileResponse(Path(__file__).resolve().parents[2] / "README.md", media_type="text/plain")
