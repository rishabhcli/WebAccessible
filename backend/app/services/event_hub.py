from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

Topic = UUID | str


def user_topic(user_id: str) -> str:
    """Return the participant-scoped topic used for notices outside any task session."""

    return f"user:{user_id}"


class SessionEventHub:
    """Fan out live notices to session-scoped and participant-scoped subscribers.

    A task session has its own topic keyed by session id. Proactive reminders have to
    reach the participant before any session exists, so they are published to a
    participant topic that the app subscribes to for the whole visit.
    """

    def __init__(self) -> None:
        self._subscribers: dict[Topic, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, topic: Topic, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers.get(topic, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscriber_count(self, topic: Topic) -> int:
        return len(self._subscribers.get(topic, set()))

    async def subscribe(self, topic: Topic) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        self._subscribers[topic].add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield event
                except TimeoutError:
                    yield {"type": "keepalive"}
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)
