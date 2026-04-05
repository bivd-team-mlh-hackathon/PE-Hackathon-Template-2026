import csv
import io
import re
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.database import db
from app.models.url import Url
from app.models.user import User

users_bp = Blueprint("users", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@users_bp.route("/api/users", methods=["GET"])
def list_users():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    total = User.select().count()
    users = User.select().order_by(User.created_at.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        users=[_user_to_dict(u) for u in users],
    )


@users_bp.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = User.get_or_none(User.id == user_id)
    if user is None:
        return jsonify(error="User not found"), 404

    urls = Url.select().where(Url.user == user).order_by(Url.created_at.desc())

    result = _user_to_dict(user)
    result["urls"] = [
        {
            "id": u.id,
            "short_code": u.short_code,
            "original_url": u.original_url,
            "title": u.title,
            "is_active": u.is_active,
        }
        for u in urls
    ]
    return jsonify(result)


@users_bp.route("/api/users", methods=["POST"])
def create_user():
    # The Fractured Vessel: must be a JSON object
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Request body must be a JSON object"), 400

    # The Unwitting Stranger: validate types and required fields
    username = data.get("username")
    email = data.get("email")

    if not isinstance(username, str) or not username.strip():
        return jsonify(error="username is required and must be a non-empty string"), 400
    if not isinstance(email, str) or not email.strip():
        return jsonify(error="email is required and must be a non-empty string"), 400

    username = username.strip()
    email = email.strip()

    if not _EMAIL_RE.match(email):
        return jsonify(error="email is invalid"), 400

    if User.select().where(User.username == username).exists():
        return jsonify(error="username already taken"), 409
    if User.select().where(User.email == email).exists():
        return jsonify(error="email already registered"), 409

    user = User.create(username=username, email=email, created_at=datetime.utcnow())
    return jsonify(_user_to_dict(user)), 201


@users_bp.route("/api/users/bulk", methods=["POST"])
def bulk_create_users():
    """Bulk import users from a CSV file (multipart/form-data, field: file)."""
    if "file" not in request.files:
        return jsonify(error="multipart field 'file' is required"), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify(error="No file selected"), 400

    try:
        content = file.read().decode("utf-8")
    except Exception:
        return jsonify(error="Could not decode file as UTF-8"), 400

    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None or not {"username", "email"}.issubset(
        {f.strip() for f in reader.fieldnames}
    ):
        return jsonify(error="CSV must have 'username' and 'email' columns"), 400

    imported = []
    now = datetime.utcnow()
    with db.atomic():
        for row in reader:
            username = (row.get("username") or "").strip()
            email = (row.get("email") or "").strip()
            if not username or not email or not _EMAIL_RE.match(email):
                continue
            if (
                User.select().where(User.username == username).exists()
                or User.select().where(User.email == email).exists()
            ):
                continue
            user = User.create(username=username, email=email, created_at=now)
            imported.append(_user_to_dict(user))

    return jsonify(count=len(imported), imported=imported), 201
