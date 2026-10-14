"""
Apple Products Global Price Tracker — the API.

Modules, roughly in the order a search uses them:

  routes         the HTTP endpoints
  limits         abuse protection: rate limits, telling visitors apart, the admin token
  lookup         product name → Apple's page for it (its slug), with a cache of answers
  results_cache  finished result sets per product
  exchange       exchange rates, kept for 30 minutes
  prices         reading a price off a store's page, and fetching every store at once
  web            connections to apple.com
  countries      the 50 stores: URL prefix, currency, symbol, flag
  config         every setting, including the environment variables
"""
from flask import Flask
from flask_cors import CORS


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)
    from .routes import bp
    app.register_blueprint(bp)
    return app
