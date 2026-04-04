import os

from flask_caching import Cache

cache = Cache()


def init_cache(app):
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Probe Redis at startup; fall back to SimpleCache if unreachable.
    # This makes tests and local dev work without a running Redis instance.
    try:
        import redis as _redis

        _redis.from_url(redis_url, socket_connect_timeout=1).ping()
        cache_config = {
            "CACHE_TYPE": "RedisCache",
            "CACHE_REDIS_URL": redis_url,
            "CACHE_DEFAULT_TIMEOUT": 60,
        }
    except Exception:
        cache_config = {
            "CACHE_TYPE": "SimpleCache",
            "CACHE_DEFAULT_TIMEOUT": 60,
        }

    cache.init_app(app, config=cache_config)
