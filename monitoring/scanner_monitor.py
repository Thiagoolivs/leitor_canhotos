#!/usr/bin/env python
"""
Watchdog-based folder monitor for leitor_canhotos.

Architecture:
- Runs as a standalone process (docker-compose 'monitor' service).
- Watches SCANNER_INPUT_DIR for new files.
- On each new file: waits briefly for the write to complete, then enqueues
  a processar_canhoto Celery task.
- Supported file types: PDF, PNG, JPG, JPEG, TIFF, TIF.
- Tracks files currently being processed to avoid duplicate submissions.
- Handles KeyboardInterrupt and SIGTERM gracefully.

Django setup happens before any app imports so that the Celery tasks
(which import Django models) work correctly in this standalone context.
"""
import logging
import os
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap Django before any local imports
# ---------------------------------------------------------------------------
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402
django.setup()

# ---------------------------------------------------------------------------
# Now it is safe to import Django-aware modules
# ---------------------------------------------------------------------------
from django.conf import settings  # noqa: E402
from watchdog.events import FileCreatedEvent, FileSystemEventHandler  # noqa: E402
from watchdog.observers import Observer  # noqa: E402

from tasks.ocr_tasks import processar_canhoto  # noqa: E402

logger = logging.getLogger(__name__)


class CanhotoFileHandler(FileSystemEventHandler):
    """
    Watchdog event handler that reacts to new files in the scanner input directory.

    Only PDF and common image extensions are processed. A small in-memory set
    (_processando) prevents duplicate task submissions when the OS fires
    multiple events for the same file (e.g. on Windows/SMB mounts).
    """

    EXTENSOES_SUPORTADAS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self._processando: set = set()

    def on_created(self, event: FileCreatedEvent):
        """
        Triggered when a new file or directory is detected.

        Ignores directory creation events and unsupported file types.
        Waits 2 seconds for the file write to complete (important on
        network/SMB mounts where files may arrive in chunks) before
        dispatching the Celery task.
        """
        if event.is_directory:
            return

        caminho = Path(event.src_path)
        extensao = caminho.suffix.lower()

        if extensao not in self.EXTENSOES_SUPORTADAS:
            self.logger.debug('Arquivo ignorado (extensão não suportada): %s', caminho.name)
            return

        caminho_str = str(caminho)

        if caminho_str in self._processando:
            self.logger.debug('Arquivo já está sendo processado, ignorando duplicata: %s', caminho.name)
            return

        self._processando.add(caminho_str)
        self.logger.info('Novo arquivo detectado: %s', caminho.name)

        # Wait briefly for the file write to finish (important for large PDFs)
        time.sleep(2)

        # Double-check the file still exists (may have been moved/deleted)
        if not caminho.exists():
            self.logger.warning('Arquivo desapareceu antes de ser processado: %s', caminho.name)
            self._processando.discard(caminho_str)
            return

        try:
            task = processar_canhoto.delay(caminho_str)
            self.logger.info(
                'Tarefa enviada ao Celery: arquivo=%s task_id=%s',
                caminho.name, task.id,
            )
        except Exception as exc:
            self.logger.error(
                'Erro ao enfileirar tarefa para %s: %s',
                caminho.name, exc,
            )
        finally:
            self._processando.discard(caminho_str)


def main():
    """
    Entry point for the scanner monitor process.

    Sets up logging, resolves the input directory from settings, creates
    a Watchdog Observer, and runs until interrupted or SIGTERM received.
    """
    # Configure logging (settings.LOGGING is already active via django.setup())
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    input_dir = getattr(settings, 'SCANNER_INPUT_DIR', '/entrada_canhotos')
    input_path = Path(input_dir)

    # Ensure the monitored directory exists
    input_path.mkdir(parents=True, exist_ok=True)

    logger.info('='*60)
    logger.info('Leitor de Canhotos - Monitor iniciado')
    logger.info('Monitorando diretório: %s', input_path)
    logger.info('='*60)

    event_handler = CanhotoFileHandler()
    observer = Observer()
    observer.schedule(event_handler, str(input_path), recursive=False)

    # Graceful shutdown on SIGTERM (used by Docker stop)
    shutdown_requested = [False]

    def handle_sigterm(signum, frame):
        logger.info('SIGTERM recebido. Encerrando monitor...')
        shutdown_requested[0] = True

    signal.signal(signal.SIGTERM, handle_sigterm)

    observer.start()
    logger.info('Observer iniciado. Aguardando novos arquivos...')

    try:
        while not shutdown_requested[0]:
            observer.join(timeout=1)
            if not observer.is_alive():
                logger.error('Observer parou inesperadamente. Reiniciando...')
                observer = Observer()
                observer.schedule(event_handler, str(input_path), recursive=False)
                observer.start()
    except KeyboardInterrupt:
        logger.info('KeyboardInterrupt recebido. Encerrando monitor...')
    finally:
        observer.stop()
        observer.join()
        logger.info('Monitor encerrado.')


if __name__ == '__main__':
    main()
