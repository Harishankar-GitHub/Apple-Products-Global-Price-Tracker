"""
The cache both the name look-ups (lookup.py) and the result sets
(results_cache.py) are kept in: a dictionary where each entry has its own
lifetime, capped in size, safe to use from the several threads that serve
requests.

Entries are kept oldest first, and storing a key again makes it the newest.
When the cache is over its cap, entries that have expired go first, then the
oldest ones.
"""
import threading
import time
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, Optional, TypeVar

V = TypeVar("V")


@dataclass(frozen=True)
class Entry(Generic[V]):
    value: V
    stored_at: float              # time.monotonic() when it was stored
    ttl: Optional[float]          # seconds it is kept; None: until it is dropped to make room

    def age(self, now: float) -> float:
        return now - self.stored_at

    def expires_in(self, now: float) -> Optional[float]:
        """Seconds left (0 once expired), or None for an entry kept for good."""
        return None if self.ttl is None else max(0.0, self.ttl - self.age(now))

    def expired(self, now: float) -> bool:
        return self.ttl is not None and self.age(now) >= self.ttl


class TTLCache(Generic[V]):
    def __init__(self, max_size: Callable[[], int]):
        # A function, not a number, so the cap is read when it is applied: a
        # test can change the setting in config without making a new cache.
        self._max_size = max_size
        self._entries: dict[Hashable, Entry[V]] = {}
        self._lock = threading.RLock()

    def get(self, key: Hashable) -> Optional[Entry[V]]:
        """The entry for `key` if it has not expired; an expired one is dropped."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expired(time.monotonic()):
                del self._entries[key]
                return None
            return entry

    def put(self, key: Hashable, value: V, ttl: Optional[float]) -> Entry[V]:
        """Store `value` as the newest entry, kept for `ttl` seconds (None: for good)."""
        entry = Entry(value, time.monotonic(), ttl)
        with self._lock:
            self._entries.pop(key, None)            # re-insert so it counts as newest
            self._entries[key] = entry
            if len(self._entries) > self._max_size():
                self._drop_expired()
            while len(self._entries) > self._max_size():
                del self._entries[next(iter(self._entries))]
        return entry

    def items(self) -> list[tuple[Hashable, Entry[V]]]:
        """Every entry that has not expired, oldest first."""
        with self._lock:
            self._drop_expired()
            return list(self._entries.items())

    def keys(self) -> list[Hashable]:
        return [key for key, _ in self.items()]

    def __len__(self) -> int:
        return len(self.items())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _drop_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, e in self._entries.items() if e.expired(now)]:
            del self._entries[key]
