"""Small middleware: permissive CORS for the shared campus front-end.

The demo UI is served from the same origin, but the three subsystems are developed separately
and the previous FastAPI stack allowed cross-origin calls during integration.  No cookies or
credentials are used: authentication always travels in the ``Authorization`` header.
"""

from __future__ import annotations

from django.http import HttpResponse

_ALLOWED_METHODS = "GET, POST, PATCH, OPTIONS"
_ALLOWED_HEADERS = "Authorization, Content-Type, Accept"
_EXPOSED_HEADERS = "Retry-After"


class SimpleCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in request.META:
            response: HttpResponse = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
        response["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
        response["Access-Control-Expose-Headers"] = _EXPOSED_HEADERS
        return response
