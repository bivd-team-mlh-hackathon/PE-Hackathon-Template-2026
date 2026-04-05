import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect as flask_redirect, request

from app.cache import init_cache
from app.database import db, init_db
from app.routes import register_routes


def _parse_bool(value):
    """Safely parse a boolean from various input types."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # Store the helper on app so routes can use it
    app._parse_bool = _parse_bool

    init_db(app)
    init_cache(app)

    from app import models  # noqa: F401 - registers models with Peewee

    register_routes(app)

    # ─── Health check ────────────────────────────────────────────────────
    @app.route("/health")
    def health():
        return jsonify(status="ok")

    # ─── Root redirect to frontend dashboard ─────────────────────────────
    @app.route("/")
    def root_redirect():
        return flask_redirect("/view/")

    # ─── Global error handlers ───────────────────────────────────────────

    @app.before_request
    def _check_json_body():
        """Reject malformed JSON on POST/PUT requests that claim to be JSON."""
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.content_type or ""

            # Skip JSON validation for multipart endpoints
            if request.path in ("/users/bulk", "/api/users/bulk"):
                return None

            # If Content-Type says JSON but body is not parseable, reject
            if "application/json" in content_type:
                try:
                    data = request.get_json(force=True, silent=False)
                except Exception:
                    return jsonify(error="Malformed JSON in request body"), 400

                # Bare string, int, etc. sent as JSON — must be object or array
                if data is not None and not isinstance(data, (dict, list)):
                    return jsonify(error="Request body must be a JSON object or array"), 400

            # Non-JSON Content-Type on a JSON endpoint (not multipart)
            elif content_type and "multipart" not in content_type:
                # Try to parse anyway; if body looks like JSON, accept it
                try:
                    data = request.get_json(force=True, silent=False)
                    if data is not None and not isinstance(data, (dict, list)):
                        return jsonify(error="Request body must be a JSON object or array"), 400
                except Exception:
                    return jsonify(error="Content-Type must be application/json"), 400

        return None

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error=str(e.description) if hasattr(e, "description") else "Bad Request"), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="Not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(error="Method not allowed"), 405

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify(error="Unprocessable Entity"), 422

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify(error="Internal server error"), 500

    return app
