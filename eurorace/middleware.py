"""Middleware helpers for running behind a path-stripped reverse proxy."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings


def _script_prefix() -> str:
    return (getattr(settings, "FORCE_SCRIPT_NAME", None) or "").rstrip("/")


class ForceScriptNameRedirectMiddleware:
    """
    Nginx proxies /euroapp/ -> app with the prefix stripped.

    1) Prefix request.get_full_path() so admin login form action stays under /euroapp.
    2) Rewrite Location / next= on redirects that still omit the prefix.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        script = _script_prefix()
        if script:
            request.META["SCRIPT_NAME"] = script
            original_get_full_path = request.get_full_path

            def get_full_path(force_append_slash=False, _original=original_get_full_path):
                path = _original(force_append_slash=force_append_slash)
                if path == script or path.startswith(f"{script}/"):
                    return path
                if path.startswith("/"):
                    return f"{script}{path}"
                return path

            request.get_full_path = get_full_path  # type: ignore[method-assign]

        response = self.get_response(request)
        if not script or "Location" not in response:
            return response

        location = response["Location"]
        parsed = urlparse(location)
        path = parsed.path or "/"

        # External absolute URLs — leave alone.
        if parsed.netloc and not self._same_host(parsed.netloc, request):
            return response

        new_path = path
        if path.startswith("/") and not path.startswith(f"{script}/") and path != script:
            new_path = f"{script}{path}"

        new_query = self._fix_next_query(parsed.query, script)
        if new_path == path and new_query == parsed.query:
            return response

        response["Location"] = urlunparse(
            parsed._replace(path=new_path, query=new_query)
        )
        return response

    @staticmethod
    def _same_host(netloc: str, request) -> bool:
        host = request.get_host().split(":")[0].lower()
        return netloc.split(":")[0].lower() in {host, f"www.{host}"}

    @staticmethod
    def _fix_next_query(query: str, script: str) -> str:
        if not query:
            return query
        pairs = []
        changed = False
        for key, value in parse_qsl(query, keep_blank_values=True):
            if (
                key == "next"
                and value.startswith("/")
                and not value.startswith(f"{script}/")
                and value != script
            ):
                value = f"{script}{value}"
                changed = True
            pairs.append((key, value))
        return urlencode(pairs) if changed else query
