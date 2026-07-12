"""Account lockout thresholds after repeated failed login attempts.

The lockout logic itself is Mongo-native (service_bridge.py's
check_locked_native/record_login_failure_native/record_login_success_native,
called from api/auth.py) — this module now only holds the threshold
constants shared with api/routers/auth.py's error messages.
"""
from __future__ import annotations

import os

MAX_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("ACCOUNT_LOCKOUT_MINUTES", "15"))
