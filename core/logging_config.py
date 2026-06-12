"""
Structured logging configuration for leitor_canhotos.

Returns a dict-based logging config compatible with Django's LOGGING setting.

Format: timestamp | level | module | message
Handlers:
  - console: outputs to stderr
  - file: rotating file at /app/logs/leitor_canhotos.log (10MB, 5 backups)
  - error_file: rotating file at /app/logs/errors.log (errors only)

Usage in settings:
    from core.logging_config import get_logging_config
    LOGGING = get_logging_config(log_dir='/app/logs', log_level='INFO')
"""
import os


def get_logging_config(log_dir: str = '/app/logs', log_level: str = 'INFO') -> dict:
    """
    Return a Django-compatible LOGGING dict config.

    Args:
        log_dir: directory where log files will be written.
        log_level: minimum log level for application loggers (DEBUG, INFO, WARNING, ERROR).

    Returns:
        dict suitable for Django's LOGGING setting.
    """
    os.makedirs(log_dir, exist_ok=True)

    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'structured': {
                'format': '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            'verbose': {
                'format': (
                    '%(asctime)s | %(levelname)-8s | %(name)s | '
                    '%(process)d | %(thread)d | %(message)s'
                ),
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            'simple': {
                'format': '%(levelname)s %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'structured',
                'stream': 'ext://sys.stdout',
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(log_dir, 'leitor_canhotos.log'),
                'maxBytes': 10 * 1024 * 1024,  # 10 MB
                'backupCount': 5,
                'formatter': 'structured',
                'encoding': 'utf-8',
            },
            'error_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(log_dir, 'errors.log'),
                'maxBytes': 10 * 1024 * 1024,  # 10 MB
                'backupCount': 5,
                'formatter': 'verbose',
                'level': 'ERROR',
                'encoding': 'utf-8',
            },
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': log_level,
        },
        'loggers': {
            'django': {
                'handlers': ['console', 'file'],
                'level': 'WARNING',
                'propagate': False,
            },
            'django.request': {
                'handlers': ['console', 'file', 'error_file'],
                'level': 'WARNING',
                'propagate': False,
            },
            'apps': {
                'handlers': ['console', 'file', 'error_file'],
                'level': log_level,
                'propagate': False,
            },
            'services': {
                'handlers': ['console', 'file', 'error_file'],
                'level': log_level,
                'propagate': False,
            },
            'tasks': {
                'handlers': ['console', 'file', 'error_file'],
                'level': log_level,
                'propagate': False,
            },
            'monitoring': {
                'handlers': ['console', 'file', 'error_file'],
                'level': log_level,
                'propagate': False,
            },
            'repositories': {
                'handlers': ['console', 'file', 'error_file'],
                'level': log_level,
                'propagate': False,
            },
            'celery': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': False,
            },
        },
    }
