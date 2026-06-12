"""
Service layer for Canhoto business logic.

Architecture:
- Handles creating canhoto records from scanned files, moving files on success/error,
  and triggering OCR reprocessing via Celery.
- Uses CanhotoRepository for all database access.
- Uses core.utils for file operations.
"""
import logging
from pathlib import Path

from django.conf import settings

from apps.canhotos.models import Canhoto, StatusProcessamento
from core.exceptions import ArquivoException
from core.utils import garantir_diretorios, mover_arquivo, sanitize_filename
from repositories.canhoto_repository import CanhotoRepository

logger = logging.getLogger(__name__)


class CanhotoService:
    """
    Business logic for Canhotos.

    Methods:
        registrar_canhoto(caminho_arquivo) -> Canhoto
        reprocessar_ocr(canhoto_id) -> None
        mover_para_processados(caminho, numero_nota) -> str
        mover_para_erro(caminho, motivo) -> str
    """

    def __init__(self):
        self.canhoto_repo = CanhotoRepository()
        self.logger = logging.getLogger(__name__)
        self.input_dir = getattr(settings, 'SCANNER_INPUT_DIR', '/entrada_canhotos')
        self.processados_dir = getattr(settings, 'SCANNER_PROCESSED_DIR', '/processados')
        self.erro_dir = getattr(settings, 'SCANNER_ERROR_DIR', '/erro')

    def registrar_canhoto(self, caminho_arquivo: str) -> Canhoto:
        """
        Create a new Canhoto database record for a newly detected file.

        The arquivo field stores the path relative to MEDIA_ROOT when the file
        is inside the media directory; otherwise stores the absolute path as-is.
        The initial status is PENDENTE (OCR not yet attempted).

        Args:
            caminho_arquivo: absolute path to the scanned file.

        Returns:
            The newly created Canhoto instance.

        Raises:
            ArquivoException: if the file does not exist.
        """
        caminho = Path(caminho_arquivo)
        if not caminho.exists():
            raise ArquivoException(
                f'Arquivo não encontrado ao registrar canhoto: {caminho_arquivo}',
                caminho=caminho_arquivo,
            )

        # Store relative path inside MEDIA_ROOT if applicable, else store full path
        media_root = Path(settings.MEDIA_ROOT)
        try:
            arquivo_relativo = caminho.relative_to(media_root)
            arquivo_campo = str(arquivo_relativo)
        except ValueError:
            # File is outside MEDIA_ROOT (e.g. in /entrada_canhotos); store absolute
            arquivo_campo = caminho_arquivo

        canhoto = self.canhoto_repo.criar(
            arquivo=arquivo_campo,
            status_processamento=StatusProcessamento.PENDENTE,
        )
        self.logger.info(
            'Canhoto registrado: id=%s arquivo=%s',
            canhoto.id, arquivo_campo,
        )
        return canhoto

    def reprocessar_ocr(self, canhoto_id: int) -> None:
        """
        Enqueue a Celery task to re-run OCR on an existing canhoto.

        Resets the status to PENDENTE and clears any previous error message
        before enqueuing so the UI reflects the pending state immediately.

        Args:
            canhoto_id: primary key of the Canhoto to reprocess.

        Raises:
            ValueError: if no Canhoto with canhoto_id exists.
        """
        from tasks.ocr_tasks import reprocessar_canhoto

        canhoto = self.canhoto_repo.buscar_por_id(canhoto_id)
        if canhoto is None:
            raise ValueError(f'Canhoto com id={canhoto_id} não encontrado.')

        self.canhoto_repo.atualizar(
            canhoto,
            status_processamento=StatusProcessamento.PENDENTE,
            erro_mensagem='',
        )

        reprocessar_canhoto.delay(canhoto_id)
        self.logger.info('OCR reprocessamento enfileirado: canhoto_id=%s', canhoto_id)

    def mover_para_processados(self, caminho: str, numero_nota: str = '') -> str:
        """
        Move a scanned file to the /processados/ directory after successful OCR.

        Creates the destination directory if it does not exist.
        If the invoice number is known, organises files into a sub-folder by number.

        Args:
            caminho: current absolute path of the file.
            numero_nota: invoice number used as a sub-folder name (optional).

        Returns:
            The new absolute path as a string.

        Raises:
            ArquivoException: if the move fails.
        """
        if numero_nota:
            destino_dir = Path(self.processados_dir) / numero_nota
        else:
            destino_dir = Path(self.processados_dir)

        garantir_diretorios(destino_dir)

        novo_caminho = mover_arquivo(caminho, str(destino_dir))
        self.logger.info(
            'Arquivo movido para processados: %s -> %s',
            caminho, novo_caminho,
        )
        return str(novo_caminho)

    def mover_para_erro(self, caminho: str, motivo: str = '') -> str:
        """
        Move a file to the /erro/ directory when OCR processing fails.

        Creates the destination directory if it does not exist.
        Logs the failure reason for diagnostics.

        Args:
            caminho: current absolute path of the file.
            motivo: human-readable reason for the failure (logged, not stored in filename).

        Returns:
            The new absolute path as a string.

        Raises:
            ArquivoException: if the move fails.
        """
        garantir_diretorios(self.erro_dir)

        novo_caminho = mover_arquivo(caminho, self.erro_dir)
        self.logger.warning(
            'Arquivo movido para erro: %s -> %s | motivo: %s',
            caminho, novo_caminho, motivo,
        )
        return str(novo_caminho)
