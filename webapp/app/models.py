from typing import Optional

from pydantic import BaseModel


class Counts(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    seen: int = 0


class StatusResponse(BaseModel):
    state: str
    counts: Counts
    current_file: Optional[str] = None
    last_error: Optional[str] = None
    last_completed_at: Optional[str] = None


class ProgressEvent(BaseModel):
    type: str
    message: str
    state: str
    counts: Counts
    current_file: Optional[str] = None
    timestamp: str


class PhotoRecord(BaseModel):
    path: str
    name: str
    size: int
    mtime: float
