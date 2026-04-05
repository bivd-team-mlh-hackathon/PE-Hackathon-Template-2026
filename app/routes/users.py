import csv
from datetime import datetime
from io import StringIO

from flask import Blueprint, jsonify, request
from peewee import chunked

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


@users_bp.route("/users", methods=["GET"])
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


@users_bp.route("/users/<int:user_id>", methods=["GET"])
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


@users_bp.route("/users/bulk", methods=["POST"])
def bulk_load_users():
    if "file" not in request.files:
        return jsonify(error="No file part"), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify(error="No selected file"), 400

    try:
        stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        rows = list(reader)

        data = []
        for r in rows:
            data.append(
                {
                    "id": int(r["id"]) if r.get("id") else None,
                    "username": r["username"],
                    "email": r["email"],
                    "created_at": r.get("created_at") or datetime.utcnow().isoformat(),
                }
            )

        with db.atomic():
            for batch in chunked(data, 100):
                User.insert_many(batch).execute()

        return jsonify(count=len(data)), 201
    except Exception as e:
        return jsonify(error=str(e)), 400
