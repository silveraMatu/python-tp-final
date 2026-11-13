"""Limitador de frecuencia en memoria (ventana deslizante)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable, DefaultDict, Deque


class SlidingWindowLimiter:
    """Permite hasta ``max_events`` eventos por clave dentro de ``window_seconds``.

    Es por proceso (suficiente para una instancia); con varias instancias habría que
    moverlo a un almacén compartido.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("max_events >= 1 y window_seconds > 0")
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        events = self._events[key]
        while events and now - events[0] >= self._window:
            events.popleft()
        return events

    def hit(self, key: str) -> bool:
        """Registra un evento; ``False`` si la clave ya agotó su cupo."""
        with self._lock:
            now = self._clock()
            events = self._prune(key, now)
            if len(events) >= self._max:
                return False
            events.append(now)
            return True

    def is_blocked(self, key: str) -> bool:
        """True si la clave alcanzó el cupo (sin registrar un evento nuevo)."""
        with self._lock:
            return len(self._prune(key, self._clock())) >= self._max

    def retry_after(self, key: str) -> int:
        """Segundos hasta que se libere un cupo."""
        with self._lock:
            now = self._clock()
            events = self._prune(key, now)
            if len(events) < self._max:
                return 0
            return max(1, int(self._window - (now - events[0])) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
