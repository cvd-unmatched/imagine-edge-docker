import asyncio
import datetime
from typing import List, Optional

from .models import Counts, ProgressEvent, StatusResponse


class AppState:
    def __init__(self):
        self.state = "idle"
        self.counts = Counts()
        self.current_file: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_completed_at: Optional[str] = None
        self._subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def snapshot(self) -> StatusResponse:
        return StatusResponse(
            state=self.state,
            counts=self.counts.model_copy(),
            current_file=self.current_file,
            last_error=self.last_error,
            last_completed_at=self.last_completed_at,
        )

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def _publish(self, event: ProgressEvent):
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    def emit(self, type_: str, message: str, current_file: Optional[str] = None):
        if current_file is not None:
            self.current_file = current_file
        event = ProgressEvent(
            type=type_,
            message=message,
            state=self.state,
            counts=self.counts.model_copy(),
            current_file=self.current_file,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        # emit() can be called from the sync worker thread (via asyncio.to_thread),
        # so publishing must always be scheduled back onto the event loop thread.
        if self._loop:
            self._loop.call_soon_threadsafe(self._publish, event)
        else:
            self._publish(event)


app_state = AppState()
