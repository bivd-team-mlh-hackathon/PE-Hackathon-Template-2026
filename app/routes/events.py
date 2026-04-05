from flask import Blueprint, jsonify, request

from app.models.event import Event

events_bp = Blueprint("events", __name__)


def _event_to_dict(event):
    return {
        "id": event.id,
        "url_id": event.url_id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "details": event.details,
    }


@events_bp.route("/api/events", methods=["GET"])
def list_events():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    url_id = request.args.get("url_id", type=int)
    event_type = request.args.get("event_type")

    query = Event.select()
    if url_id is not None:
        query = query.where(Event.url == url_id)
    if event_type:
        query = query.where(Event.event_type == event_type)

    total = query.count()
    events = query.order_by(Event.timestamp.desc()).paginate(page, per_page)

    return jsonify(
        total=total,
        page=page,
        per_page=per_page,
        events=[_event_to_dict(e) for e in events],
    )
