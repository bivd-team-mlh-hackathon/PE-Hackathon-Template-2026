import json
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, redirect, request

from app.cache import cache
from app.database import db
from app.models.event import Event
from app.models.url import Url
from app.models.user import User
from app.utils import is_valid_custom_code, to_base62

urls_bp = Blueprint("urls", __name__)


def _parse_bool(value):
    """Safely parse booleans — handles 'false' string correctly."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _url_to_dict(url):
    return {
        "id": url.id,
        "short_code": url.short_code,
        "original_url": url.original_url,
        "title": url.title,
        "is_active": url.is_active,
        "user_id": url.user_id,
        "created_at": url.created_at.isoformat() if url.created_at else None,
        "updated_at": url.updated_at.isoformat() if url.updated_at else None,
    }


def _generate_unique_short_code():
    """Generate a random unique 6-char short code using secrets."""
    charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    while True:
        code = "".join(secrets.choice(charset) for _ in range(6))
        if not Url.select().where(Url.short_code == code).exists():
            return code


@cache.memoize(timeout=3600)
def _get_redirect_target(short_code):
    """Cache the short_code → original_url mapping in Redis (plan §URL redirecting deep dive)."""
    url = Url.get_or_none(Url.short_code == short_code)
    if url is None:
        return None
    return {
        "id": url.id,
        "original_url": url.original_url,
        "user_id": url.user_id,
        "is_active": url.is_active,
    }


@urls_bp.route("/<short_code>")
def redirect_url(short_code):
    target = _get_redirect_target(short_code)
    if target is None:
        return jsonify(error="URL not found"), 404

    # The Slumbering Guide: dormant routes offer no passage and leave no footprint.
    if not target["is_active"]:
        return jsonify({"error": "This URL has been deactivated"}), 410

    # Log click event BEFORE redirecting
    Event.create(
        url_id=url.id,
        user=None,
        event_type="click",
        timestamp=datetime.utcnow(),
        details=json.dumps({
            "short_code": url.short_code,
            "original_url": url.original_url,
        }),
    )
    return redirect(url.original_url, code=302)


# ─── List URLs ───────────────────────────────────────────────────────────────

@urls_bp.route("/urls", methods=["GET"])
def list_urls():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = max(1, min(request.args.get("per_page", 20, type=int), 100))
    active_only = request.args.get("active", "").lower() == "true"
    user_id_filter = request.args.get("user_id", None, type=int)

    query = Url.select()
    if active_only:
        query = query.where(Url.is_active)
    if user_id_filter is not None:
        query = query.where(Url.user_id == user_id_filter)

    total = query.count()
    urls = query.order_by(Url.created_at.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        urls=[_url_to_dict(u) for u in urls],
    )


@urls_bp.route("/urls/<int:url_id>", methods=["GET"])
@cache.memoize(timeout=60)
def get_url(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404
    return jsonify(_url_to_dict(url))


@urls_bp.route("/urls", methods=["POST"])
def create_url():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Payload must be a JSON object"), 400

    original_url = data.get("original_url")
    user_id = data.get("user_id")

    if not original_url or not user_id:
        return jsonify(error="original_url and user_id are required"), 400
    if not isinstance(user_id, int):
        return jsonify(error="user_id must be an integer"), 400
    if not isinstance(original_url, str):
        return jsonify(error="original_url must be a string"), 400

    original_url = original_url.strip()

    if not User.get_or_none(User.id == user_id):
        return jsonify(error="User not found"), 400

    custom_code = data.get("short_code", "")
    if custom_code:
        custom_code = custom_code.strip()
        ok, err = is_valid_custom_code(custom_code)
        if not ok:
            return jsonify(error=err), 400
        if Url.select().where(Url.short_code == custom_code).exists():
            return jsonify(error="short_code already taken"), 409

    # Parse is_active safely
    is_active = _parse_bool(data.get("is_active", True))

    # Always generate a unique short_code — even for duplicate original_url
    now = datetime.utcnow()
    with db.atomic():
        url = Url.create(
            user_id=user_id,
            short_code=custom_code or _generate_unique_short_code(),
            original_url=original_url,
            title=title if isinstance(title, str) else None,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

    Event.create(
        url=url,
        user_id=user_id,
        event_type="created",
        timestamp=now,
        details=json.dumps({
            "short_code": url.short_code,
            "original_url": url.original_url,
        }),
    )

    return jsonify(_url_to_dict(url)), 201


@urls_bp.route("/urls/<int:url_id>", methods=["PUT"])
def update_url(url_id):
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify(error="Invalid JSON body"), 400

    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    if "original_url" in data:
        if not isinstance(data["original_url"], str):
            return jsonify(error="original_url must be a string"), 422
        url.original_url = data["original_url"]
    if "title" in data:
        if data["title"] is not None and not isinstance(data["title"], str):
            return jsonify(error="title must be a string"), 422
        url.title = data["title"]
    if "is_active" in data:
        url.is_active = _parse_bool(data["is_active"])

    url.updated_at = datetime.utcnow()
    url.save()

    cache.delete_memoized(get_url, url_id)
    cache.delete_memoized(_get_redirect_target, url.short_code)

    return jsonify(_url_to_dict(url))


@urls_bp.route("/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    short_code = url.short_code
    url.delete_instance(recursive=True)

    cache.delete_memoized(get_url, url_id)
    cache.delete_memoized(_get_redirect_target, short_code)

    return jsonify(message="URL deleted"), 200


@urls_bp.route("/urls/<int:url_id>/stats", methods=["GET"])
def url_stats(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        return jsonify(error="URL not found"), 404

    events = Event.select().where(Event.url == url)
    total_events = events.count()
    clicks = events.where(Event.event_type == "click").count()

    return jsonify(
        url_id=url_id,
        short_code=url.short_code,
        total_events=total_events,
        clicks=clicks,
    )
