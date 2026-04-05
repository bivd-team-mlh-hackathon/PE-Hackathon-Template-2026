from flask import Blueprint, jsonify, request
from playhouse.shortcuts import model_to_dict

from app.models.event import Event

events_bp = Blueprint("events", __name__)


@events_bp.route("/events", methods=["GET"])
def list_events():
    """List all events (optionally filtered by url_id)"""
    url_id = request.args.get("url_id")
    query = Event.select()

    if url_id:
        query = query.where(Event.url_id == url_id)

    events = [model_to_dict(e) for e in query]
    return jsonify(events), 200
