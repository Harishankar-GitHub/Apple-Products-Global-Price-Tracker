"""
Gunicorn settings for the API.

Gunicorn reads this file by itself when it is started in this folder, which is
the case on Render (Root Directory `api`), so plain `gunicorn app:app` picks
these up too. render.yaml also names it (`-c gunicorn.conf.py`). The address
to listen on is left to gunicorn, which uses Render's PORT environment variable.
"""
import os


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# One process. The caches and the rate-limit counters live in this process's
# memory, so every request has to be served by the same one.
workers = 1

# …with a pool of threads, so visitors are served side by side. The default
# "sync" worker handles one request at a time: a search held up everyone else.
# Most threads spend their time waiting (on Apple, or for a fetch slot — see
# MAX_PARALLEL_FETCHES in tracker/config.py), so they are cheap; having more of
# them keeps cached searches and health checks from queueing behind searches
# that wait.
worker_class = "gthread"
threads = _int_env("WEB_THREADS", 16)

# With threads this is only a heartbeat: gunicorn restarts the process if it
# stops responding for this long. It does not limit how long one request may
# take, so a slow search is no longer cut off mid-stream (with the sync
# worker, 30 seconds was the limit for each request).
timeout = 120

# On a redeploy, give searches in progress time to finish.
graceful_timeout = 30

keepalive = 5

# The access log (a line per request) is not set here. On Render it is on anyway:
# Render sets GUNICORN_CMD_ARGS="--preload --access-logfile - --bind=0.0.0.0:10000",
# which takes precedence over this file. Its lines show Render's proxy (127.0.0.1)
# as the address, not the visitor's. The API's own log is set by LOG_LEVEL
# (see tracker/config.py).
