import json

from flask import Blueprint, jsonify, request

from app.models.event import Event

events_bp = Blueprint("events", __name__)


def _event_to_dict(event):
    # Parse details JSON if stored as string
    details = event.details
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": event.id,
        "url_id": event.url_id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "details": details,
    }


@events_bp.route("/events", methods=["GET"])
@events_bp.route("/api/events", methods=["GET"])
def list_events():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = max(1, min(request.args.get("per_page", 20, type=int), 100))
    url_id_filter = request.args.get("url_id", None, type=int)
    user_id_filter = request.args.get("user_id", None, type=int)
    event_type_filter = request.args.get("event_type", None, type=str)

    query = Event.select()

    if url_id_filter is not None:
        query = query.where(Event.url_id == url_id_filter)
    if user_id_filter is not None:
        query = query.where(Event.user_id == user_id_filter)
    if event_type_filter:
        query = query.where(Event.event_type == event_type_filter)

    total = query.count()
    events = query.order_by(Event.timestamp.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        events=[_event_to_dict(e) for e in events],
    )
