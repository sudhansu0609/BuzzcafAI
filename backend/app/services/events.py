"""
Server-sent event bus for the Studio (roadmap v5, 3.1).

Dexter needs to hear about things that happen inside the Studio without
polling: a project was created, a step finished, a step is waiting for the
creator's approval, a step failed, a BuzzBrain snapshot arrived. One SSE
channel (`GET /api/studio/events`) carries all of it.

Same design as Dexter's own events.py: publish() is safe from any thread
(workflow steps run in FastAPI's threadpool) and hops onto the event loop via
call_soon_threadsafe once the loop is bound at startup.
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, Optional, Set

MAX_QUEUE = 200
HEARTBEAT_SECONDS = 20.0

EVENT_TYPES = (
    "project_created",
    "step_started",
    "step_completed",
    "approval_needed",
    "step_failed",
    "buzzbrain_snapshot",
    # v9: one agent handing work to another, and a department answering.
    "agent_invoked",
    "department_task",
)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.last: Dict[str, Dict[str, Any]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _deliver(self, message: Dict[str, Any]) -> None:
        dead = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, payload: Any = None) -> None:
        """Broadcast to every connected client. Safe from any thread."""
        message = {"type": event_type, "payload": payload, "ts": time.time()}
        self.last[event_type] = message

        if self._loop is None or self._loop.is_closed():
            self._deliver(message)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._deliver(message)
        else:
            self._loop.call_soon_threadsafe(self._deliver, message)

    async def stream(self, queue: asyncio.Queue) -> AsyncIterator[str]:
        yield frame("connected", {"ok": True, "events": list(EVENT_TYPES)})
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield frame(message["type"], message["payload"], message["ts"])
        except asyncio.CancelledError:
            raise
        finally:
            self.unsubscribe(queue)


def frame(event_type: str, payload: Any, ts: Optional[float] = None) -> str:
    body = json.dumps({"type": event_type, "payload": payload, "ts": ts or time.time()}, ensure_ascii=False)
    return f"event: {event_type}\ndata: {body}\n\n"


bus = EventBus()
