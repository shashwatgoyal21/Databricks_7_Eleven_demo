"""Small in-process caches for the API (what st.cache_data / st.cache_resource did in the Streamlit app)."""

import functools
import threading
import time

_registry = []


def ttl_cache(ttl):
    """Cache a function's results for `ttl` seconds, keyed by its arguments."""
    def wrap(fn):
        store, lock = {}, threading.Lock()

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit and now - hit[0] < ttl:
                    return hit[1]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (now, value)
            return value

        inner.clear = store.clear
        _registry.append(store)
        return inner
    return wrap


def resource(fn):
    """Create once per process (connections, clients)."""
    cached = functools.cache(fn)
    _registry.append(cached)
    return cached


def clear_all():
    for c in _registry:
        (c.cache_clear if hasattr(c, "cache_clear") else c.clear)()
