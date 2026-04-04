import secrets
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from peewee import JOIN, fn

from app.cache import cache
from app.database import db
from app.models.event import Event
from app.models.url import Url
from app.models.user import User
from app.utils import is_valid_custom_code, to_base62

frontend_bp = Blueprint("frontend", __name__)

PER_PAGE = 20


# ─── Dashboard ───────────────────────────────────────────────────────────────


@frontend_bp.route("/")
@cache.cached(timeout=30, key_prefix="view_index")
def index():
    stats = _get_global_stats()
    recent_urls = list(Url.select().order_by(Url.created_at.desc()).limit(8))
    return render_template("index.html", stats=stats, recent_urls=recent_urls)


def _get_global_stats():
    total_urls = Url.select().count()
    active_urls = Url.select().where(Url.is_active).count()
    total_users = User.select().count()
    total_clicks = Event.select().where(Event.event_type == "click").count()
    total_events = Event.select().count()

    top_urls = (
        Url.select(Url, fn.COUNT(Event.id).alias("click_count"))
        .join(Event, on=(Event.url == Url.id))
        .where(Event.event_type == "click")
        .group_by(Url.id)
        .order_by(fn.COUNT(Event.id).desc())
        .limit(10)
    )

    return {
        "total_urls": total_urls,
        "active_urls": active_urls,
        "total_users": total_users,
        "total_clicks": total_clicks,
        "total_events": total_events,
        "top_urls": [
            {
                "id": u.id,
                "short_code": u.short_code,
                "title": u.title,
                "original_url": u.original_url,
                "clicks": u.click_count,
            }
            for u in top_urls
        ],
    }


# ─── URLs ────────────────────────────────────────────────────────────────────


@frontend_bp.route("/urls")
def urls_list():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    active_filter = request.args.get("active", "")

    query = Url.select()
    if q:
        query = query.where(Url.short_code.contains(q) | Url.title.contains(q))
    if active_filter == "true":
        query = query.where(Url.is_active)
    elif active_filter == "false":
        query = query.where(~Url.is_active)

    total = query.count()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    urls = list(query.order_by(Url.created_at.desc()).paginate(page, PER_PAGE))

    return render_template(
        "urls/list.html",
        urls=urls,
        total=total,
        page=page,
        total_pages=total_pages,
        q=q,
        active_filter=active_filter,
    )


@frontend_bp.route("/urls/new", methods=["GET", "POST"])
def urls_new():
    if request.method == "POST":
        original_url = request.form.get("original_url", "").strip()
        title = request.form.get("title", "").strip() or None
        custom_code = request.form.get("short_code", "").strip()
        user_id = request.form.get("user_id", "").strip() or None

        if not original_url:
            flash("Destination URL is required.", "error")
            return render_template("urls/new.html", form=request.form)

        # Duplicate long URL check (per plan §URL shortening deep dive step 2-3)
        existing = Url.get_or_none(Url.original_url == original_url, Url.is_active)
        if existing:
            flash(f"That URL already exists as /{existing.short_code}", "info")
            return redirect(url_for("frontend.url_detail", url_id=existing.id))

        if custom_code:
            ok, err = is_valid_custom_code(custom_code)
            if not ok:
                flash(err, "error")
                return render_template("urls/new.html", form=request.form)
            if Url.select().where(Url.short_code == custom_code).exists():
                flash(f'Short code "{custom_code}" is already taken.', "error")
                return render_template("urls/new.html", form=request.form)

        now = datetime.utcnow()
        with db.atomic():
            url = Url.create(
                user_id=int(user_id) if user_id else None,
                short_code=f"__pending_{secrets.token_hex(4)}",
                original_url=original_url,
                title=title,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            # Base 62 from auto-increment ID (per plan §Base 62 conversion)
            url.short_code = custom_code or to_base62(url.id)
            url.save()

        Event.create(
            url=url,
            user_id=url.user_id,
            event_type="created",
            timestamp=now,
            details=None,
        )
        cache.delete("view_index")
        short_url = request.url_root.rstrip("/") + "/" + url.short_code
        flash(
            f'Short URL created: <a href="/{url.short_code}" class="alert-link fw-bold">{short_url}</a>',
            "success",
        )
        return redirect(url_for("frontend.url_detail", url_id=url.id))

    return render_template("urls/new.html", form={})


@frontend_bp.route("/urls/<int:url_id>")
def url_detail(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        flash("URL not found.", "error")
        return redirect(url_for("frontend.urls_list"))

    events = list(
        Event.select()
        .where(Event.url == url)
        .order_by(Event.timestamp.desc())
        .limit(20)
    )
    total_events = Event.select().where(Event.url == url).count()
    clicks = Event.select().where(Event.url == url, Event.event_type == "click").count()

    return render_template(
        "urls/detail.html",
        url=url,
        events=events,
        url_stats={"total_events": total_events, "clicks": clicks},
    )


@frontend_bp.route("/urls/<int:url_id>/edit", methods=["POST"])
def url_edit(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url is None:
        flash("URL not found.", "error")
        return redirect(url_for("frontend.urls_list"))

    url.original_url = request.form.get("original_url", url.original_url).strip()
    url.title = request.form.get("title", "").strip() or None
    url.is_active = "is_active" in request.form
    url.updated_at = datetime.utcnow()
    url.save()

    from app.routes.urls import _get_redirect_target

    cache.delete_memoized(_get_redirect_target, url.short_code)
    cache.delete("view_index")
    flash("URL updated.", "success")
    return redirect(url_for("frontend.url_detail", url_id=url_id))


@frontend_bp.route("/urls/<int:url_id>/toggle", methods=["POST"])
def url_toggle(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url:
        url.is_active = not url.is_active
        url.updated_at = datetime.utcnow()
        url.save()
        cache.delete("view_index")
    return redirect(request.referrer or url_for("frontend.urls_list"))


@frontend_bp.route("/urls/<int:url_id>/delete", methods=["POST"])
def url_delete(url_id):
    url = Url.get_or_none(Url.id == url_id)
    if url:
        from app.routes.urls import _get_redirect_target

        cache.delete_memoized(_get_redirect_target, url.short_code)
        url.delete_instance(recursive=True)
        cache.delete("view_index")
        flash("URL deleted.", "success")
    return redirect(url_for("frontend.urls_list"))


# ─── Users ───────────────────────────────────────────────────────────────────


@frontend_bp.route("/users")
def users_list():
    page = request.args.get("page", 1, type=int)

    total = User.select().count()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    users_q = (
        User.select(User, fn.COUNT(Url.id).alias("url_count"))
        .join(Url, JOIN.LEFT_OUTER, on=(Url.user == User.id))
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .paginate(page, PER_PAGE)
    )

    users = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "created_at": u.created_at,
            "url_count": u.url_count,
        }
        for u in users_q
    ]

    return render_template(
        "users/list.html",
        users=users,
        total=total,
        page=page,
        total_pages=total_pages,
    )


@frontend_bp.route("/users/<int:user_id>")
def user_detail(user_id):
    user = User.get_or_none(User.id == user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("frontend.users_list"))

    urls = list(Url.select().where(Url.user == user).order_by(Url.created_at.desc()))
    active_count = sum(1 for u in urls if u.is_active)

    return render_template(
        "users/detail.html", user=user, urls=urls, active_count=active_count
    )
