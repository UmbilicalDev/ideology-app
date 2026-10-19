"""Public, read-only JSON API under ``/api/v1`` (``public-dataset-api``).

GET only, SELECT only, no voter data. Dependency direction:
``db`` / ``models`` / ``pipeline.publishing`` -> ``api`` -> ``main``.
"""

from ideology_app.api.queries import ApiNotFoundError
from ideology_app.api.routes import router

__all__ = ["ApiNotFoundError", "router"]
