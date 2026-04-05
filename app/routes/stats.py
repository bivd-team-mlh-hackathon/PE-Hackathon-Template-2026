from flask import Blueprint, jsonify
from peewee import fn

from app.cache import cache
from app.models.event import Event
from app.models.url import Url
from app.models.user import User

stats_bp = Blueprint("stats", __name__)


@stats_bp.route("/api/stats", methods=["GET"])
@cache.cached(timeout=30, key_prefix="api_stats")
def global_stats():
    total_urls = Url.select().count()
    active_urls = Url.select().where(Url.is_active).count()
    total_users = User.select().count()
    total_events = Event.select().count()
    total_clicks = Event.select().where(Event.event_type == "click").count()

    top_urls = (
        Url.select(Url, fn.COUNT(Event.id).alias("click_count"))
        .join(Event, on=(Event.url == Url.id))
        .where(Event.event_type == "click")
        .group_by(Url.id)
        .order_by(fn.COUNT(Event.id).desc())
        .limit(10)
    )

    return jsonify(
        total_urls=total_urls,
        active_urls=active_urls,
        total_users=total_users,
        total_events=total_events,
        total_clicks=total_clicks,
        top_urls=[
            {
                "id": u.id,
                "short_code": u.short_code,
                "title": u.title,
                "original_url": u.original_url,
                "clicks": u.click_count,
            }
            for u in top_urls
        ],
    )
