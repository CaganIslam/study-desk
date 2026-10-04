"""One background worker: jobs run one at a time, in the order they were submitted.

A job whose key is already queued or running is not queued again, so repeated
triggers (page reloads, a timer) cannot pile up duplicate work.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)


class JobQueue:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, Callable[[], None]]] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, key: str, fn: Callable[[], None]) -> bool:
        """Queue `fn` unless a job with the same key is queued or running. True if queued."""
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, name="studydesk-jobs", daemon=True)
                self._thread.start()
        self._queue.put((key, fn))
        return True

    def busy(self, key: str) -> bool:
        with self._lock:
            return key in self._pending

    def join(self) -> None:
        """Block until every queued job has finished (used by tests and shutdown)."""
        self._queue.join()

    def _work(self) -> None:
        while True:
            key, fn = self._queue.get()
            try:
                fn()
            except Exception:  # a failing job must not kill the worker
                log.exception("job %s failed", key)
            finally:
                with self._lock:
                    self._pending.discard(key)
                self._queue.task_done()
