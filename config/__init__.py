# This makes config a Python package and also imports the Celery app
# so that shared_task decorators work correctly across the project.
from .celery import app as celery_app

__all__ = ('celery_app',)
