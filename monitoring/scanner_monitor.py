#!/usr/bin/env python
"""
Watchdog-based folder monitor for leitor_canhotos.

Architecture:
- Runs as a standalone process (docker-compose 'monitor' service).
- Watches every directory listed in SCANNER_INPUT_DIRS for new files.
- On each new file: waits briefly for the write to complete, then enqueues
  a processar_canhoto Celery task.
- One Observer per directory — a crash in one folder does not affect others.
- Supported file types: PDF, PNG, JPG, JPEG, TIFF, TIF.
- Tracks files currently being processed to avoid duplicate submissions.
- Handles KeyboardInterrupt and SIGTERM gracefully.

Django setup happens before any app imports so that the Celery tasks
(which import Django models) work correctly in this standalone context.

Configure monitored folders via .env:
    SCANNER_INPUT_DIRS=/entrada_canhotos
    # or multiple:
    SCANNER_INPUT_DIRS=/entrada_canhotos,/entrada_canhotos_2,/entrada_canhotos_3
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
from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler  # noqa: E402
from watchdog.observers import Observer  # noqa: E402

from tasks.ocr_tasks import processar_canhoto  # noqa: E402

logger = logging.getLogger(__name__)


class CanhotoFileHandler(FileSystemEventHandler):
    """
    Watchdog event handler that reacts to new files in a scanner input directory.

    Only PDF and common image extensions are processed. A small in-memory set
    (_processando) prevents duplicate task submissions when the OS fires
    multiple events for the same file (e.g. on Windows/SMB mounts).
    """

    EXTENSOES_SUPORTADAS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

    def __init__(self, pasta_origem: str):
        super().__init__()
        self.pasta_origem = pasta_origem
        self._processando: set = set()

    def _enfileirar(self, caminho: Path) -> None:
        if caminho.suffix.lower() not in self.EXTENSOES_SUPORTADAS:
            logger.debug('[%s] Extensão ignorada: %s', self.pasta_origem, caminho.name)
            return

        caminho_str = str(caminho)
        if caminho_str in self._processando:
            logger.debug('[%s] Duplicata ignorada: %s', self.pasta_origem, caminho.name)
            return

        self._processando.add(caminho_str)
        logger.info('[%s] Novo arquivo detectado: %s', self.pasta_origem, caminho.name)

        # Wait briefly for the file write to finish (important for large PDFs
        # and network/SMB mounts where files may arrive in chunks).
        time.sleep(2)

        if not caminho.exists():
            logger.warning('[%s] Arquivo desapareceu antes de ser processado: %s', self.pasta_origem, caminho.name)
            self._processando.discard(caminho_str)
            return

        try:
            task = processar_canhoto.delay(caminho_str)
            logger.info('[%s] Tarefa enviada ao Celery: arquivo=%s task_id=%s', self.pasta_origem, caminho.name, task.id)
        except Exception as exc:
            logger.error('[%s] Erro ao enfileirar %s: %s', self.pasta_origem, caminho.name, exc)
        finally:
            self._processando.discard(caminho_str)

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        self._enfileirar(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        """Handles files renamed/moved into the watched folder from a temp write."""
        if event.is_directory:
            return
        self._enfileirar(Path(event.dest_path))


def iniciar_observers(diretorios: list) -> list:
    """Create and start one Observer per directory. Returns list of started observers."""
    observers = []
    for diretorio in diretorios:
        pasta = Path(diretorio)
        if not pasta.exists():
            logger.warning('Pasta nao encontrada, criando: %s', pasta)
            pasta.mkdir(parents=True, exist_ok=True)

        handler = CanhotoFileHandler(pasta_origem=str(pasta))
        observer = Observer()
        observer.schedule(handler, str(pasta), recursive=False)
        observer.start()
        observers.append((observer, handler, str(pasta)))
        logger.info('Monitorando pasta: %s', pasta)

    return observers


def main():
    """
    Entry point for the scanner monitor process.

    Sets up logging, resolves input directories from SCANNER_INPUT_DIRS,
    starts one Observer per directory, and runs until interrupted or SIGTERM.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    diretorios: list = getattr(settings, 'SCANNER_INPUT_DIRS', ['/entrada_canhotos'])

    if not diretorios:
        logger.error('SCANNER_INPUT_DIRS esta vazio. Encerrando.')
        sys.exit(1)

    logger.info('=' * 60)
    logger.info('Leitor de Canhotos - Monitor iniciado')
    logger.info('Monitorando %d pasta(s): %s', len(diretorios), diretorios)
    logger.info('=' * 60)

    observers = iniciar_observers(diretorios)

    shutdown_requested = [False]

    def handle_sigterm(signum, frame):
        logger.info('SIGTERM recebido. Encerrando monitor...')
        shutdown_requested[0] = True

    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        while not shutdown_requested[0]:
            # Check that all observers are still alive; restart any that died.
            for i, (observer, handler, pasta) in enumerate(observers):
                if not observer.is_alive():
                    logger.warning('Observer parou para pasta %s, reiniciando...', pasta)
                    new_observer = Observer()
                    new_observer.schedule(handler, pasta, recursive=False)
                    new_observer.start()
                    observers[i] = (new_observer, handler, pasta)
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info('KeyboardInterrupt recebido. Encerrando monitor...')
    finally:
        for observer, _, pasta in observers:
            observer.stop()
        for observer, _, pasta in observers:
            observer.join()
        logger.info('Todos os monitores encerrados.')


if __name__ == '__main__':
    main()
