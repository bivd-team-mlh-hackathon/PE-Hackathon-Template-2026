import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.cache import init_cache
from app.database import db, init_db
from app.routes import register_routes

from prometheus_flask_exporter import PrometheusMetrics
def create_app():
    load_dotenv()

    app = Flask(__name__)
    metrics = PrometheusMetrics(app)
    metrics.info('app_info', 'URL Shortener', version='1.0')
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    init_db(app)
    init_cache(app)

    from app import models  # noqa: F401 - registers models with Peewee

    register_routes(app)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Catches 400 Bad Request (malformed JSON) and returns clean JSON."""
        return jsonify({"error": e.name, "message": e.description}), e.code

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        """Prevents the app from leaking raw 500 HTML traces."""
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                }
            ),
            500,
        )

    @app.route("/health")
    def health():
        checks = {}
        try:
            db.execute_sql("SELECT 1")
            checks["db_primary"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["db_primary"] = f"error: {e}"
        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        return jsonify(status=status, checks=checks)

    return app
