"""Anonymous Voter feedback (feedback-api): the message rule, its own store and the abuse guard.

Dependency direction: ``config`` / ``db.make_engine`` / ``shared_db`` -> ``feedback``
-> ``api.feedback_routes`` / ``cli``. Never imports ``models``: the feedback
store is not part of the shared database.
"""
