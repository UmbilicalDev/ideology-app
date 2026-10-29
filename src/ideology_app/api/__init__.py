"""Public, read-only JSON API under ``/api/v1`` (``public-dataset-api``).

``router`` is GET only, SELECT only, no voter data. The single write route,
``POST /api/v1/feedback``, is ``feedback_router`` (``feedback_routes``); it
writes only the separate feedback store. The Operator routes are
``admin_router`` (``admin_routes``), under ``/admin/api/v1``, outside the public
prefix and the public OpenAPI. Dependency direction:
``db`` / ``models`` / ``pipeline.publishing`` -> ``api`` -> ``main``.
"""

from ideology_app.api.queries import ApiNotFoundError
from ideology_app.api.admin_routes import admin_router
from ideology_app.api.feedback_routes import feedback_router
from ideology_app.api.routes import router

__all__ = ["ApiNotFoundError", "admin_router", "feedback_router", "router"]
