"""Prepare the next slide's explanation while the student reads the current one.

Two rules keep this cheap:
- Only the slide after the one the student is on is wanted. A queued job for a
  slide the student has already left is skipped when its turn comes.
- The same explanation is never generated twice at once: a request that arrives
  while a prefetch for the same slide is running waits for it (InFlight).
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

from studydesk.ai.runner import ClaudeError
from studydesk.jobs import JobQueue

T = TypeVar("T")
WAIT_LIMIT = 300  # seconds a waiter waits for another thread's Claude call


class InFlight:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def run_once(self, key: str, fn: Callable[[], T]) -> tuple[bool, T | None]:
        """Run `fn` unless another thread is already running it for `key`.

        Returns (True, result) for the thread that ran it, (False, None) for a thread
        that waited; the waiter should then read the result from the cache.
        """
        with self._lock:
            event = self._events.get(key)
            owner = event is None
            if owner:
                event = self._events[key] = threading.Event()
        if not owner:
            event.wait(WAIT_LIMIT)
            return False, None
        try:
            return True, fn()
        finally:
            with self._lock:
                self._events.pop(key, None)
            event.set()


class Prefetcher:
    def __init__(self, jobs: JobQueue, make_explainer: Callable) -> None:
        self.jobs = jobs
        self.make_explainer = make_explainer
        self.wanted: dict[int, tuple[int, str]] = {}  # deck id -> (slide idx, level)

    def want(self, deck_id: int, idx: int, level: str, live: bool = False) -> None:
        self.wanted[deck_id] = (idx, level)

        def job() -> None:
            if self.wanted.get(deck_id) != (idx, level):
                return  # the student moved on before this job's turn
            explainer = self.make_explainer(live)
            if explainer.cached(deck_id, idx, level):
                return
            try:
                explainer.explain(deck_id, idx, level)
            except (ClaudeError, LookupError):
                pass  # shown to the student if and when they open the slide

        self.jobs.submit(f"prefetch:{deck_id}:{idx}:{level}", job)
