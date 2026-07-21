"""Backend test package defaults.

Rate limiting stays disabled unless a test explicitly enables it via
``override_settings`` / ``make_test_settings(rate_limit_enabled=True)``.
"""

from backend.tests.auth_helpers import make_test_settings
from backend.src.app.core.config import set_settings_override

set_settings_override(make_test_settings(rate_limit_enabled=False))
