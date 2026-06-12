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

# Autodiscover tasks from installed Django apps.
app.autodiscover_tasks([
    'apps.notas',
    'apps.canhotos',
])

# tasks/ocr_tasks.py lives outside any Django app so autodiscover won't find it.
# Force-import the module so Celery registers processar_arquivo / reprocessar_canhoto.
@app.on_after_configure.connect
def import_ocr_tasks(sender, **kwargs):
    import tasks.ocr_tasks  # noqa: F401

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """A simple debug task to verify Celery is working."""
    print(f'Request: {self.request!r}')
