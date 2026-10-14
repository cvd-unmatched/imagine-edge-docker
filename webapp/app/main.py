import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, sync_service
from .config import settings
from .login_page import render_login_page
from .state import app_state

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

BUSY_STATES = {"starting", "joining_wifi", "verifying_camera", "transferring"}

logger = logging.getLogger("uvicorn.error")


def _start_pairing(reason: str) -> bool:
    """Marks the app busy and starts a sync in the background. False if one is already running."""
    if app_state.state in BUSY_STATES:
        return False
    app_state.state = "starting"
    app_state.emit("phase", reason)
    asyncio.create_task(_run_pairing())
    return True


async def _run_pairing():
    await asyncio.to_thread(sync_service.run_pairing_flow, app_state, settings)


async def _auto_scan_loop():
    interval = settings.auto_scan_interval_seconds
    logger.info("Auto scan on: checking for the camera every %ss", interval)
    while True:
        if app_state.state not in BUSY_STATES:
            try:
                if await asyncio.to_thread(sync_service.camera_visible, settings):
                    _start_pairing("Camera found, starting sync")
            except Exception as e:
                # misconfiguration (missing interface, no SSID, ...): keep going, retry next tick
                logger.warning("Auto scan check failed: %s", e)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed: refuse to run wide open if login credentials or the
    # session-signing key were never configured.
    if not settings.webapp_username or not settings.webapp_password or not settings.webapp_secret_key:
        raise RuntimeError(
            "WEBAPP_USERNAME, WEBAPP_PASSWORD, and WEBAPP_SECRET_KEY must all be set in .env, "
            "the app will not start without them. See webapp/.env.example."
        )
    app_state.bind_loop(asyncio.get_running_loop())
    scan_task = asyncio.create_task(_auto_scan_loop()) if settings.auto_scan_enabled else None
    yield
    if scan_task:
        scan_task.cancel()
        with suppress(asyncio.CancelledError):
            await scan_task


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path == "/healthz" or path == "/login":
        return await call_next(request)
    if path.startswith("/api/"):
        if not auth.is_authenticated(request, settings):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        return await call_next(request)
    if path == "/" and not auth.is_authenticated(request, settings):
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_form(error: int = 0):
    return render_login_page(error=bool(error))


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    if not auth.check_credentials(username, password, settings):
        return RedirectResponse(url="/login?error=1", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_cookie(settings),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/status")
async def get_status():
    return app_state.snapshot()


@app.post("/api/pair")
async def pair():
    if not _start_pairing("Pair requested"):
        raise HTTPException(status_code=409, detail="Sync already in progress")
    return JSONResponse(status_code=202, content={"status": "accepted"})


@app.get("/api/events")
async def events():
    queue = app_state.subscribe()

    async def generator():
        try:
            snapshot = app_state.snapshot()
            yield f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: progress\ndata: {event.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            app_state.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/photos")
async def list_photos(limit: int = 60, offset: int = 0):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    output_dir = Path(settings.output_dir)
    if not output_dir.exists():
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    # stat once per file, then sort newest-first, then slice the requested page
    entries = [(p, p.stat()) for p in output_dir.rglob("*") if p.is_file()]
    entries.sort(key=lambda e: e[1].st_mtime, reverse=True)
    total = len(entries)
    items = [
        {
            "path": str(p.relative_to(output_dir)),
            "name": p.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
        for p, stat in entries[offset : offset + limit]
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/photos/{photo_path:path}")
async def get_photo(photo_path: str):
    output_dir = Path(settings.output_dir).resolve()
    target = (output_dir / photo_path).resolve()
    if not target.is_relative_to(output_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


@app.get("/api/config")
async def get_config():
    ssid = settings.wifi_ssid
    masked = (ssid[:2] + "***" + ssid[-2:]) if len(ssid) > 4 else "***"
    return {
        "wifi_interface": settings.wifi_interface,
        "camera_ip": settings.camera_ip,
        "camera_port": settings.camera_port,
        "wifi_ssid_masked": masked if ssid else "(not set)",
        "auto_scan_seconds": settings.auto_scan_interval_seconds if settings.auto_scan_enabled else None,
    }


# Mounted last so the /api/* and /healthz routes above take precedence.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
