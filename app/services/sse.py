"""In-memory pub/sub broker for Server-Sent Events (SSE) queue streaming."""

from __future__ import annotations

import json
import queue
from typing import Dict, List


class SSEBroker:
    def __init__(self):
        # Maps hospital_id -> list of subscriber queues
        self._subscribers: Dict[int, List[queue.Queue]] = {}

    def subscribe(self, hospital_id: int) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        if hospital_id not in self._subscribers:
            self._subscribers[hospital_id] = []
        self._subscribers[hospital_id].append(q)
        return q

    def unsubscribe(self, hospital_id: int, q: queue.Queue):
        if hospital_id in self._subscribers:
            try:
                self._subscribers[hospital_id].remove(q)
                if not self._subscribers[hospital_id]:
                    del self._subscribers[hospital_id]
            except ValueError:
                pass

    def publish(self, hospital_id: int, event_type: str, data: dict):
        if hospital_id not in self._subscribers:
            return
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        dead_queues = []
        for q in self._subscribers[hospital_id]:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead_queues.append(q)
        for q in dead_queues:
            self.unsubscribe(hospital_id, q)


sse_broker = SSEBroker()
