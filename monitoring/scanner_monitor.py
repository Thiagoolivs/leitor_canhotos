#!/usr/bin/env python
"""
Scanner monitor for leitor_canhotos.

Watches two sets of directories:
  SCANNER_NOTA_DIRS    -> files are scanned invoices  -> processar_arquivo(caminho, tipo='nota')
  SCANNER_CANHOTO_DIRS -> files are scanned canhotos  -> processar_arquivo(caminho, tipo='canhoto')

One Observer per directory. Handles KeyboardInterrupt and SIGTERM gracefully.
"""
import logging
import os
import signal
import sys
import time
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django
django.setup()

from django.conf import settings
from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from tasks.ocr_tasks import processar_arquivo

logger = logging.getLogger(__name__)


class ScannerFileHandler(FileSystemEventHandler):
    """Handles new files in a scanner folder. Passes tipo='nota' or 'canhoto' to Celery."""

    EXTENSOES_SUPORTADAS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

    def __init__(self, pasta_origem: str, tipo: str):
        super().__init__()
        assert tipo in ('nota', 'canhoto'), f"tipo deve ser 'nota' ou 'canhoto', recebeu: {tipo}"
        self.pasta_origem = pasta_origem
        self.tipo = tipo
        self._processando: set = set()

    def _enfileirar(self, caminho: Path) -> None:
        if caminho.suffix.lower() not in self.EXTENSOES_SUPORTADAS:
            return
        chave = str(caminho)
        if chave in self._processando:
            return
        self._processando.add(chave)
        logger.info('[%s][%s] Novo arquivo detectado: %s', self.tipo.upper(), self.pasta_origem, caminho.name)
        time.sleep(2)
        if not caminho.exists():
            logger.warning('[%s] Arquivo desapareceu: %s', self.tipo.upper(), caminho.name)
            self._processando.discard(chave)
            return
        try:
            task = processar_arquivo.delay(str(caminho), self.tipo)
            logger.info('[%s] Tarefa enfileirada: arquivo=%s task_id=%s', self.tipo.upper(), caminho.name, task.id)
        except Exception as exc:
            logger.error('[%s] Erro ao enfileirar %s: %s', self.tipo.upper(), caminho.name, exc)
        finally:
            self._processando.discard(chave)

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._enfileirar(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        if not event.is_directory:
            self._enfileirar(Path(event.dest_path))


def iniciar_observers(diretorios: list, tipo: str) -> list:
    observers = []
    for diretorio in diretorios:
        pasta = Path(diretorio)
        pasta.mkdir(parents=True, exist_ok=True)
        handler = ScannerFileHandler(pasta_origem=str(pasta), tipo=tipo)
        observer = Observer()
        observer.schedule(handler, str(pasta), recursive=False)
        observer.start()
        observers.append((observer, handler, str(pasta)))
        logger.info('[%s] Monitorando: %s', tipo.upper(), pasta)
    return observers


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    nota_dirs: list = getattr(settings, 'SCANNER_NOTA_DIRS', [])
    canhoto_dirs: list = getattr(settings, 'SCANNER_CANHOTO_DIRS', [])

    if not nota_dirs and not canhoto_dirs:
        logger.error('SCANNER_NOTA_DIRS e SCANNER_CANHOTO_DIRS estao ambos vazios. Encerrando.')
        sys.exit(1)

    logger.info('=' * 60)
    logger.info('Leitor de Canhotos - Monitor iniciado')
    logger.info('Pastas de NOTAS: %s', nota_dirs)
    logger.info('Pastas de CANHOTOS: %s', canhoto_dirs)
    logger.info('=' * 60)

    observers = []
    observers += iniciar_observers(nota_dirs, tipo='nota')
    observers += iniciar_observers(canhoto_dirs, tipo='canhoto')

    shutdown_requested = [False]

    def handle_sigterm(signum, frame):
        logger.info('SIGTERM recebido. Encerrando...')
        shutdown_requested[0] = True

    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        while not shutdown_requested[0]:
            for i, (observer, handler, pasta) in enumerate(observers):
                if not observer.is_alive():
                    logger.warning('Observer parou para %s, reiniciando...', pasta)
                    new_obs = Observer()
                    new_obs.schedule(handler, pasta, recursive=False)
                    new_obs.start()
                    observers[i] = (new_obs, handler, pasta)
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info('Interrompido pelo usuario.')
    finally:
        for observer, _, _ in observers:
            observer.stop()
        for observer, _, _ in observers:
            observer.join()
        logger.info('Todos os monitores encerrados.')


if __name__ == '__main__':
    main()
