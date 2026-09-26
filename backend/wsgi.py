"""WSGI entry point for the API server."""
from academicai.app import create_app

app = create_app()

if __name__ == "__main__":  # pragma: no cover - development convenience only
    app.run(host="127.0.0.1", port=5000, debug=False)
