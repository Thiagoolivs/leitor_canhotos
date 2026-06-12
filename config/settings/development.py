"""
Development settings for leitor_canhotos.

Extends base.py with development-specific overrides:
- DEBUG=True
- ALLOWED_HOSTS accepts all hosts
- More verbose logging
- Django debug toolbar can be added here if needed
"""
from .base import *  # noqa: F401, F403
from decouple import config

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = ['*']

# In development, show full exception details
INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
]

# Use a simple in-memory cache in development if Redis is not available
# (falls back to Redis if REDIS_URL is set, which it is in docker-compose)

# Extra logging verbosity in development
LOGGING['loggers']['apps']['level'] = 'DEBUG'  # noqa: F405
LOGGING['loggers']['services']['level'] = 'DEBUG'  # noqa: F405
LOGGING['loggers']['tasks']['level'] = 'DEBUG'  # noqa: F405
LOGGING['loggers']['monitoring']['level'] = 'DEBUG'  # noqa: F405
