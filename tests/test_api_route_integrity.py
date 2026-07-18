from collections import Counter

from fastapi.routing import APIRoute

from backend.app.main import app


def test_api_routes_are_registered_only_once():
    route_keys = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        for method in route.methods or set():
            if method in {
                "HEAD",
                "OPTIONS",
            }:
                continue

            route_keys.append(
                (
                    method,
                    route.path,
                )
            )

    counts = Counter(route_keys)

    duplicates = {
        f"{method} {path}": count
        for (
            method,
            path,
        ), count in counts.items()
        if count > 1
    }

    assert duplicates == {} 