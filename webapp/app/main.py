import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import sync_service
from .config import settings
from .state import app_state

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

BUSY_STATES = {"starting", "joining_wifi", "verifying_camera", "transferring"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/status")
async def get_status():
    return app_state.snapshot()


@app.post("/api/pair")
async def pair():
    if app_state.state in BUSY_STATES:
        raise HTTPException(status_code=409, detail="Sync already in progress")
    app_state.state = "starting"
    app_state.emit("phase", "Pair requested")
    asyncio.create_task(_run_pairing())
    return JSONResponse(status_code=202, content={"status": "accepted"})


async def _run_pairing():
    await asyncio.to_thread(sync_service.run_pairing_flow, app_state, settings)


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
async def list_photos(limit: int = 50):
    output_dir = Path(settings.output_dir)
    if not output_dir.exists():
        return []
    files = [p for p in output_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for p in files[:limit]:
        stat = p.stat()
        result.append(
            {
                "path": str(p.relative_to(output_dir)),
                "name": p.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return result


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
    }


# Mounted last so the /api/* and /healthz routes above take precedence.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
