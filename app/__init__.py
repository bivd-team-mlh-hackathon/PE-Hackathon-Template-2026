import os

from dotenv import load_dotenv
from flask import Flask, jsonify

from app.cache import init_cache
from app.database import db, init_db
from app.routes import register_routes


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    init_db(app)
    init_cache(app)

    from app import models  # noqa: F401 - registers models with Peewee

    register_routes(app)

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
