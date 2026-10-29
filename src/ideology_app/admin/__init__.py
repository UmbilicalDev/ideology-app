"""Operator accounts and sessions for the admin page (feedback-admin).

Standard library and ``config`` only. Accounts come from ``ADMIN_USERS``
(``accounts``); sessions live in memory, per process (``sessions``). Nothing
here logs a username, password, hash, token or CSRF token.
"""
