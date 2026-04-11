"""In-process event bus for mission state propagation."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any, Callable

EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """Small thread-safe pub/sub bus for local process events."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: dict[str, set[EventHandler]] = defaultdict(set)

    def subscribe(self, topic: str, handler: EventHandler) -> Callable[[], None]:
        with self._lock:
            self._subscribers[topic].add(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subscribers.get(topic)
                if handlers is None:
                    return
                handlers.discard(handler)
                if not handlers:
                    self._subscribers.pop(topic, None)

        return unsubscribe

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
        for handler in handlers:
            try:
                handler(payload)
            except Exception:
                continue


EVENT_BUS = EventBus()

