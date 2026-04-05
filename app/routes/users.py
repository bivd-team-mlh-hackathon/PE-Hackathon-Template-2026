import csv
import io
import re
from datetime import datetime

from flask import Blueprint, jsonify, request
from peewee import IntegrityError, chunked

from app.database import db
from app.models.url import Url
from app.models.user import User

users_bp = Blueprint("users", __name__)


def _user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _validate_email(email):
    """Basic email format validation."""
    if not isinstance(email, str):
        return False
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


# ─── List Users ──────────────────────────────────────────────────────────────


@users_bp.route("/users", methods=["GET"])
@users_bp.route("/api/users", methods=["GET"])
def list_users():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = max(1, min(request.args.get("per_page", 20, type=int), 100))

    total = User.select().count()
    users = User.select().order_by(User.id.asc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        users=[_user_to_dict(u) for u in users],
    )


# ─── Get User by ID ─────────────────────────────────────────────────────────


@users_bp.route("/users/<int:user_id>", methods=["GET"])
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


# ─── Create User ─────────────────────────────────────────────────────────────


@users_bp.route("/users", methods=["POST"])
@users_bp.route("/api/users", methods=["POST"])
def create_user():
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify(error="Invalid JSON body"), 400

    errors = {}

    # Validate username
    username = data.get("username")
    if username is None or username == "":
        errors["username"] = "username is required"
    elif not isinstance(username, str):
        errors["username"] = "username must be a string"
    else:
        username = username.strip()
        if len(username) < 1:
            errors["username"] = "username cannot be empty"
        elif len(username) > 100:
            errors["username"] = "username must be 100 characters or fewer"

    # Validate email
    email = data.get("email")
    if email is None or email == "":
        errors["email"] = "email is required"
    elif not isinstance(email, str):
        errors["email"] = "email must be a string"
    else:
        email = email.strip()
        if not _validate_email(email):
            errors["email"] = "invalid email format"

    if errors:
        return jsonify(error="Validation failed", details=errors), 422

    now = datetime.utcnow()
    try:
        user = User.create(
            username=username,
            email=email,
            created_at=now,
        )
    except IntegrityError as e:
        db.rollback()
        err_msg = str(e).lower()
        if "username" in err_msg:
            return jsonify(error="username already exists"), 409
        if "email" in err_msg:
            return jsonify(error="email already exists"), 409
        return jsonify(error="Duplicate entry"), 409

    return jsonify(_user_to_dict(user)), 201


# ─── Update User ─────────────────────────────────────────────────────────────


@users_bp.route("/users/<int:user_id>", methods=["PUT"])
@users_bp.route("/api/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify(error="Invalid JSON body"), 400

    user = User.get_or_none(User.id == user_id)
    if user is None:
        return jsonify(error="User not found"), 404

    errors = {}

    if "username" in data:
        username = data["username"]
        if not isinstance(username, str):
            errors["username"] = "username must be a string"
        else:
            username = username.strip()
            if len(username) < 1:
                errors["username"] = "username cannot be empty"
            elif len(username) > 100:
                errors["username"] = "username must be 100 characters or fewer"
            else:
                user.username = username

    if "email" in data:
        email = data["email"]
        if not isinstance(email, str):
            errors["email"] = "email must be a string"
        else:
            email = email.strip()
            if not _validate_email(email):
                errors["email"] = "invalid email format"
            else:
                user.email = email

    if errors:
        return jsonify(error="Validation failed", details=errors), 422

    try:
        user.save()
    except IntegrityError as e:
        db.rollback()
        err_msg = str(e).lower()
        if "username" in err_msg:
            return jsonify(error="username already exists"), 409
        if "email" in err_msg:
            return jsonify(error="email already exists"), 409
        return jsonify(error="Duplicate entry"), 409

    return jsonify(_user_to_dict(user))


# ─── Bulk Load Users (CSV Import) ───────────────────────────────────────────


@users_bp.route("/users/bulk", methods=["POST"])
@users_bp.route("/api/users/bulk", methods=["POST"])
def bulk_users():
    if "file" not in request.files:
        return jsonify(error="No file uploaded. Use 'file' field."), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify(error="Empty filename"), 400

    try:
        content = file.read().decode("utf-8")
    except UnicodeDecodeError:
        return jsonify(error="File must be UTF-8 encoded"), 400

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    now = datetime.utcnow()

    for row in reader:
        entry = {
            "username": row.get("username", "").strip(),
            "email": row.get("email", "").strip(),
            "created_at": row.get("created_at", now.isoformat()),
        }
        if row.get("id"):
            entry["id"] = int(row["id"])
        if entry["username"] and entry["email"]:
            rows.append(entry)

    if not rows:
        return jsonify(error="No valid rows found in CSV"), 400

    imported = 0
    with db.atomic():
        for batch in chunked(rows, 100):
            User.insert_many(batch).on_conflict_ignore().execute()
            imported += len(batch)

    # Reset sequence if we inserted explicit IDs
    if any("id" in r for r in rows):
        max_id = max(r.get("id", 0) for r in rows)
        try:
            db.execute_sql(
                f"SELECT setval(pg_get_serial_sequence('users', 'id'), GREATEST({max_id}, (SELECT COALESCE(MAX(id), 1) FROM users)))"
            )
        except Exception:
            pass

    return jsonify(imported=imported, count=imported), 201
