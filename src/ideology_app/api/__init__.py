"""Public, read-only JSON API under ``/api/v1`` (``public-dataset-api``).

``router`` is GET only, SELECT only, no voter data. The single write route,
``POST /api/v1/feedback``, is ``feedback_router`` (``feedback_routes``); it
writes only the separate feedback store. Dependency direction:
``db`` / ``models`` / ``pipeline.publishing`` -> ``api`` -> ``main``.
"""

from ideology_app.api.queries import ApiNotFoundError
from ideology_app.api.feedback_routes import feedback_router
from ideology_app.api.routes import router

__all__ = ["ApiNotFoundError", "feedback_router", "router"]
