"""
Apple Products Global Price Tracker — the API.

Modules, roughly in the order a search uses them:

  routes         the HTTP endpoints
  search         one search, start to finish, for both price endpoints
  limits         abuse protection: rate limits, telling visitors apart, the admin token
  lookup         product name → Apple's page for it (its slug), with a cache of answers
  results_cache  finished result sets per product
  caches         the cache class those two keep their answers in
  exchange       exchange rates, fetched again in the background every 30 minutes
  prices         reading a price off a store's page, and fetching every store at once
  web            one event loop and connection pool for apple.com
  countries      the 50 stores, from countries.json: URL prefix, currency, symbol, flag
  config         every setting, including the environment variables
"""
import logging

from flask import Flask
from flask_cors import CORS

from . import config


def configure_logging() -> None:
    """
    The API's messages (the `tracker.*` loggers) go to standard error, in the
    format gunicorn uses for its own, at config.LOG_LEVEL.
    """
    log = logging.getLogger(__name__)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(process)d] [%(levelname)s] %(name)s: %(message)s",
                                               "%Y-%m-%d %H:%M:%S %z"))
        log.addHandler(handler)
    log.setLevel(config.LOG_LEVEL)


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)
    CORS(app)
    from .routes import bp
    app.register_blueprint(bp)
    return app
