"""Helpers for the API tests: a clock, a small client for both endpoints, and readers for their answers."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

import app as api

LIMITERS = (api._request_limiter, api._fetch_limiter, api._global_fetch_limiter)


class Clock:
    """Real monotonic time plus an offset a test can jump forward."""

    def __init__(self, monkeypatch):
        self.offset = 0.0
        real = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real() + self.offset)

    def advance(self, seconds: float):
        self.offset += seconds


@dataclass
class Event:
    name: str
    data: dict


def parse_sse(raw: str) -> list[Event]:
    """Server-sent events, in order; comment lines (keep-alives) are skipped."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append(Event(fields["event"], json.loads(fields["data"])))
    return events


@dataclass
class Result:
    """One search, read the same way whichever endpoint answered it."""
    via: str
    status: int
    error: Optional[dict] = None      # the error payload, if the search failed
    meta: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    events: list = field(default_factory=list)

    @property
    def cached(self) -> bool:
        return self.meta.get("cached") is True

    def row(self, country: str) -> dict:
        return next(r for r in self.rows if r["country"] == country)

    @property
    def priced(self) -> int:
        return sum(1 for r in self.rows if r["available"])


class Api:
    def __init__(self, client):
        self.client = client

    @staticmethod
    def _headers(ip: Optional[str], headers: Optional[dict]) -> dict:
        h = {"CF-Connecting-IP": ip} if ip else {}
        h.update(headers or {})
        return h

    def get(self, product: Optional[str], ip: Optional[str] = None, headers: Optional[dict] = None):
        """GET /api/prices; returns the Flask response."""
        query = {} if product is None else {"product": product}
        return self.client.get("/api/prices", query_string=query, headers=self._headers(ip, headers))

    def stream(self, product: Optional[str], ip: Optional[str] = None, headers: Optional[dict] = None) -> list[Event]:
        """GET /api/prices/stream; returns the events."""
        query = {} if product is None else {"product": product}
        resp = self.client.get("/api/prices/stream", query_string=query, headers=self._headers(ip, headers))
        assert resp.status_code == 200 and resp.mimetype == "text/event-stream"
        return parse_sse(resp.get_data(as_text=True))

    def search(self, product: str, via: str = "json", ip: Optional[str] = None,
               headers: Optional[dict] = None) -> Result:
        if via == "json":
            resp = self.get(product, ip, headers)
            body = resp.get_json()
            if "error" in body:
                return Result(via, resp.status_code, error=body)
            meta = {k: v for k, v in body.items() if k != "results"}
            return Result(via, resp.status_code, meta=meta, rows=body["results"])
        events = self.stream(product, ip, headers)
        result = Result(via, 200, events=events)
        for e in events:
            if e.name == "meta":
                result.meta = e.data
            elif e.name == "result":
                result.rows.append(e.data)
            elif e.name == "error":
                result.error = e.data
        return result

    def status(self, token: Optional[str] = None, headers: Optional[dict] = None) -> dict:
        h = dict(headers or {})
        if token is not None:
            h["X-Admin-Token"] = token
        return self.client.get("/api/cache/status", headers=h).get_json()


def cached_ttl(slug: str) -> int:
    """How long the results cache keeps `slug` (seconds)."""
    return api._results_cache[slug]["ttl"]
