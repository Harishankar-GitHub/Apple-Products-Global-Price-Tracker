"""
Apple Products Global Price Tracker — the API's entry point.

Render (and local gunicorn) start it from this folder with
`gunicorn -c gunicorn.conf.py app:app`. The code lives in the `tracker`
package next to this file; see tracker/__init__.py for a map of it.
"""
from tracker import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
