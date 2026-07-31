"""Single shared Limiter instance. Its own module (not helpers.py) so both
auth.py and helpers.py can import it without a circular import -- helpers.py
already imports from auth.py."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
