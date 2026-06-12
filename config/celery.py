"""
Celery configuration for leitor_canhotos project.

Architecture decision:
- Using Redis as both broker and result backend for simplicity.
- Tasks are autodiscovered from apps/ and tasks/ directories.
- The --pool=solo flag is used in docker-compose for the Celery worker to
  avoid multiprocessing issues with pytesseract on some platforms.
"""
import os

from celery import Celery

# Set the default Django settings module for the Celery program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('leitor_canhotos')

# Use a string here so the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodiscover tasks from all installed Django apps and from the tasks/ directory.
app.autodiscover_tasks([
    'apps.notas',
    'apps.canhotos',
    'tasks',
])

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """A simple debug task to verify Celery is working."""
    print(f'Request: {self.request!r}')
