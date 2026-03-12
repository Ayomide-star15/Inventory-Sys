# app/core/rate_limit.py

from slowapi import Limiter
from slowapi.util import get_remote_address

# Uses the client's IP address as the identifier
limiter = Limiter(key_func=get_remote_address)