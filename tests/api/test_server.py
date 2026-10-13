"""
The API under real gunicorn, with the settings in api/gunicorn.conf.py and apple.com
faked (tests/servers/fake_api.py): visitors are served side by side, a long search is
not cut off, and a closed page stops waiting for a fetch slot.
"""
import json
import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

pytestmark = pytest.mark.server

ROOT = pathlib.Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TOKEN = "server-test-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def environment(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("WEB_THREADS", "MAX_PARALLEL_FETCHES")}
    paths = [str(API_DIR), str(ROOT / "tests"), str(ROOT / "tests" / "servers"), os.environ.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(filter(None, paths))
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Which settings gunicorn ends up with
# ---------------------------------------------------------------------------

def printed_settings(args: list[str], **env) -> dict:
    out = subprocess.run([sys.executable, "-m", "gunicorn", *args, "--print-config", "app:app"], cwd=API_DIR,
                         env=environment(PORT="5090", **env), capture_output=True, text=True, check=True).stdout
    keys = r"workers|worker_class|threads|timeout|graceful_timeout|bind"
    return dict(re.findall(rf"^({keys})\s*=\s*(.+)$", out, re.M))


EXPECTED = {"workers": "1", "worker_class": "gthread", "threads": "16", "timeout": "120",
            "graceful_timeout": "30", "bind": "['0.0.0.0:5090']"}


@pytest.mark.parametrize("args", [[], ["-c", "gunicorn.conf.py"]], ids=["plain-gunicorn-app", "render-yaml-command"])
def test_gunicorn_picks_up_the_settings_file(args):
    assert printed_settings(args) == EXPECTED


def test_web_threads_reaches_gunicorn():
    assert printed_settings([], WEB_THREADS="4")["threads"] == "4"


# ---------------------------------------------------------------------------
# A live server
# ---------------------------------------------------------------------------

class Server:
    def __init__(self, port: int, process: subprocess.Popen, log: pathlib.Path):
        self.port, self.process, self.log_path = port, process, log

    @property
    def log(self) -> str:
        return self.log_path.read_text()

    def get(self, path: str, headers=None) -> tuple[int, dict, float]:
        started = time.monotonic()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.loads(resp.read()), time.monotonic() - started

    def cached_slugs(self) -> set:
        return set(self.get("/api/cache/status", {"X-Admin-Token": TOKEN})[1]["results_cache"]["slugs"])


@pytest.fixture(scope="module")
def live(tmp_path_factory) -> Server:
    """gunicorn with the project's settings, a 2 s heartbeat timeout, and slow products on demand."""
    port = free_port()
    log = tmp_path_factory.mktemp("gunicorn") / "server.log"
    env = environment(ADMIN_TOKEN=TOKEN, FETCH_SLOT_NOTICE="0.3",
                      FAKE_APPLE_SLOW="prod901=1.5,prod902=2.5,prod903=1.5,prod904=1.5,prod905=1.5,prod906=1.5")
    with log.open("w") as out:
        process = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "-c", str(API_DIR / "gunicorn.conf.py"),
             "--bind", f"127.0.0.1:{port}", "--timeout", "2", "fake_api:app"],
            cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
    server = Server(port, process, log)
    for _ in range(100):
        try:
            server.get("/api/health")
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("gunicorn did not start:\n" + server.log)
    yield server
    process.send_signal(signal.SIGTERM)
    process.wait(15)


class Connection(threading.Thread):
    """A browser connection to the stream, over a real socket (HTTP/1.0: the body ends when the server closes)."""

    def __init__(self, server: Server, product: str, close_on: str = ""):
        super().__init__(daemon=True)
        self.server, self.product, self.close_on = server, product, close_on
        self.events: list[str] = []
        self.seconds = None

    def run(self):
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.server.port)) as sock:
            sock.sendall(f"GET /api/prices/stream?product={self.product} HTTP/1.0\r\n\r\n".encode())
            buffer = b""
            while chunk := sock.recv(65536):
                buffer += chunk
                self.events = re.findall(r"^event: (\w+)", buffer.decode(errors="replace"), re.M)
                if self.close_on and self.close_on in self.events:
                    sock.shutdown(socket.SHUT_RDWR)
                    break
        self.seconds = time.monotonic() - started

    def results(self) -> int:
        return self.events.count("result")


def test_one_process_with_threads(live):
    assert "Using worker: gthread" in live.log and live.log.count("Booting worker") == 1


def test_visitors_are_served_side_by_side(live):
    live.get("/api/prices?product=MacBook+Air")                      # in the cache
    slow = Connection(live, "prod901")
    slow.start()
    time.sleep(0.5)
    _, health, health_time = live.get("/api/health")
    _, cached, cached_time = live.get("/api/prices?product=MacBook+Air")
    other = Connection(live, "iPhone+17")
    other.start()
    other.join(10)
    assert slow.is_alive()                                            # all of this happened during the slow search
    assert health == {"status": "ok"} and health_time < 0.5
    assert cached["cached"] is True and cached_time < 0.5
    assert other.events[-1] == "done" and "queued" not in other.events and other.seconds < 2
    slow.join(30)


def test_search_longer_than_the_timeout_is_not_cut_off(live):
    """`--timeout 2` here: with threads it only checks the process is alive, it does not limit a request."""
    search = Connection(live, "prod902")
    search.start()
    search.join(30)
    assert search.seconds > 4                                         # 2.5 s for each of two downloads per store
    assert search.events[-1] == "done" and search.results() == 50
    assert "WORKER TIMEOUT" not in live.log and live.log.count("Booting worker") == 1


def test_closed_page_stops_waiting_for_a_slot(live):
    running = [Connection(live, "prod903"), Connection(live, "prod904")]   # take both fetch slots
    for c in running:
        c.start()
    time.sleep(0.5)
    closed = Connection(live, "prod905", close_on="queued")              # the visitor leaves while it waits
    kept = Connection(live, "prod906")                                   # this one stays
    closed.start()
    kept.start()
    closed.join(5)
    for c in (*running, kept):
        c.join(30)
    assert closed.events == ["searching", "queued"]
    assert "queued" in kept.events and kept.events[-1] == "done"
    cached = live.cached_slugs()
    assert {"prod903", "prod904", "prod906"} <= cached and "prod905" not in cached
