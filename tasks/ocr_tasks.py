"""
Celery tasks for OCR processing of scanner files.

Architecture:
- processar_arquivo: main task triggered by the watchdog monitor for new files.
  Handles both 'nota' (scanned invoices) and 'canhoto' (signed stubs) types.
  For tipo='nota': OCR extracts NF number -> creates NotaFiscal with AGUARDANDO_CANHOTO.
  For tipo='canhoto': OCR extracts NF number -> finds NotaFiscal -> links Canhoto -> FINALIZADO.
- processar_canhoto: legacy task kept for backwards compatibility (wraps processar_arquivo).
- reprocessar_canhoto: re-runs OCR on an existing Canhoto (triggered from UI or admin).

Both tasks use exponential backoff retries and move files to /erro/ on max retries.
"""
import logging
import os
from pathlib import Path

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='tasks.ocr_tasks.processar_arquivo',
)
def processar_arquivo(self, caminho_arquivo: str, tipo: str) -> dict:
    """
    Process a scanned file from the scanner.

    tipo='nota'    -> OCR extracts NF number -> creates NotaFiscal with AGUARDANDO_CANHOTO
    tipo='canhoto' -> OCR extracts NF number -> finds NotaFiscal -> links Canhoto -> FINALIZADO
    """
    from services.ocr_service import OCRService
    from services.nota_service import NotaService
    from services.canhoto_service import CanhotoService
    from services.conciliacao_service import ConciliacaoService

    _logger = logging.getLogger(__name__)
    caminho = Path(caminho_arquivo)

    _logger.info('Iniciando processamento [%s]: %s', tipo.upper(), caminho.name)

    ocr_service = OCRService()
    canhoto_service = CanhotoService()

    try:
        resultado_ocr = ocr_service.processar_arquivo(caminho_arquivo)
        numero_nota = resultado_ocr.get('numero_nota')

        if tipo == 'nota':
            # Create NotaFiscal from scanned invoice
            if not numero_nota:
                novo_caminho = canhoto_service.mover_para_erro(caminho_arquivo, 'numero_nota_nao_detectado')
                _logger.warning('[NOTA] Numero nao detectado em %s -> movido para erro', caminho.name)
                return {'status': 'erro', 'motivo': 'numero_nao_detectado', 'arquivo': novo_caminho}

            nota_service = NotaService()
            nota = nota_service.registrar_nota_escaneada(
                numero=numero_nota,
                arquivo_path=caminho_arquivo,
            )
            novo_caminho = canhoto_service.mover_para_processados(caminho_arquivo, numero_nota)
            _logger.info('[NOTA] NF %s registrada (id=%s) -> %s', numero_nota, nota.id, novo_caminho)
            return {'status': 'sucesso', 'tipo': 'nota', 'numero': numero_nota, 'nota_id': nota.id}

        else:  # tipo == 'canhoto'
            canhoto = None
            try:
                canhoto = _criar_canhoto_processando(caminho_arquivo)

                # Salva texto OCR mesmo que numero nao seja detectado
                _salvar_texto_ocr(canhoto, resultado_ocr.get('texto', ''))

                if not numero_nota:
                    _finalizar_canhoto_erro(canhoto, 'numero_nota_nao_detectado_no_ocr')
                    novo_caminho = canhoto_service.mover_para_erro(caminho_arquivo, 'ocr_sem_numero')
                    _logger.warning('[CANHOTO] Numero nao detectado em %s', caminho.name)
                    return {'status': 'erro', 'motivo': 'numero_nao_detectado'}

                conciliacao_service = ConciliacaoService()
                resultado = conciliacao_service.conciliar(canhoto.id, numero_nota)
                novo_caminho = canhoto_service.mover_para_processados(caminho_arquivo, numero_nota)
                _logger.info('[CANHOTO] Conciliado NF %s -> %s', numero_nota, novo_caminho)
                return {'status': 'sucesso', 'tipo': 'canhoto', 'numero': numero_nota, 'conciliado': resultado.sucesso}

            except Exception as exc:
                if canhoto:
                    _finalizar_canhoto_erro(canhoto, str(exc))
                novo_caminho = canhoto_service.mover_para_erro(caminho_arquivo, str(exc))
                raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

    except Exception as exc:
        _logger.error('[%s] Erro ao processar %s: %s', tipo.upper(), caminho.name, exc, exc_info=True)
        try:
            canhoto_service.mover_para_erro(caminho_arquivo, str(exc))
        except Exception:
            pass
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        return {'status': 'erro', 'motivo': str(exc)}


def _salvar_texto_ocr(canhoto, texto: str) -> None:
    """Helper: persist extracted OCR text on the Canhoto record."""
    if texto:
        from repositories.canhoto_repository import CanhotoRepository
        CanhotoRepository().atualizar(canhoto, texto_ocr=texto)


def _criar_canhoto_processando(caminho_arquivo: str):
    """Helper: create Canhoto record with PROCESSANDO status."""
    from repositories.canhoto_repository import CanhotoRepository
    from apps.canhotos.models import StatusProcessamento
    repo = CanhotoRepository()
    return repo.criar(
        arquivo=caminho_arquivo,
        status_processamento=StatusProcessamento.PROCESSANDO,
    )


def _finalizar_canhoto_erro(canhoto, mensagem: str) -> None:
    """Helper: update Canhoto to ERRO status."""
    from repositories.canhoto_repository import CanhotoRepository
    from apps.canhotos.models import StatusProcessamento
    repo = CanhotoRepository()
    repo.atualizar(canhoto, status_processamento=StatusProcessamento.ERRO, erro_mensagem=mensagem)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='tasks.ocr_tasks.processar_canhoto',
)
def processar_canhoto(self, caminho_arquivo: str) -> dict:
    """
    Process a newly detected canhoto file.

    Steps:
    1. Log the start of processing.
    2. Create a Canhoto DB record with status PROCESSANDO.
    3. Run OCRService.processar_arquivo() to extract text and invoice number.
    4. If invoice number found: run ConciliacaoService.conciliar().
    5. Move the file to /processados/ (success) or /erro/ (failure).
    6. Update the Canhoto's final status.
    7. Return a result dict.

    On exception: retry with exponential backoff (60s, 120s, 240s).
    After max_retries: move file to /erro/ and mark Canhoto as ERRO.

    Args:
        caminho_arquivo: absolute path to the scanned file.

    Returns:
        dict with keys: sucesso (bool), canhoto_id (int|None), numero_nota (str|None),
        mensagem (str).
    """
    logger.info('[processar_canhoto] Iniciando: arquivo=%s task_id=%s', caminho_arquivo, self.request.id)

    from apps.canhotos.models import StatusProcessamento
    from repositories.canhoto_repository import CanhotoRepository
    from services.ocr_service import OCRService
    from services.conciliacao_service import ConciliacaoService
    from core.exceptions import NotaFiscalNaoEncontradaException, ConciliacaoException

    canhoto_repo = CanhotoRepository()
    ocr_service = OCRService()
    canhoto_id = None

    try:
        # -- Step 1: Verify file exists
        caminho = Path(caminho_arquivo)
        if not caminho.exists():
            logger.error('[processar_canhoto] Arquivo não encontrado: %s', caminho_arquivo)
            return {
                'sucesso': False,
                'canhoto_id': None,
                'numero_nota': None,
                'mensagem': f'Arquivo não encontrado: {caminho_arquivo}',
            }

        # -- Step 2: Create Canhoto record with PROCESSANDO status
        # Store relative to MEDIA_ROOT if possible
        media_root = Path(settings.MEDIA_ROOT)
        try:
            arquivo_campo = str(caminho.relative_to(media_root))
        except ValueError:
            arquivo_campo = caminho_arquivo

        canhoto = canhoto_repo.criar(
            arquivo=arquivo_campo,
            status_processamento=StatusProcessamento.PROCESSANDO,
        )
        canhoto_id = canhoto.id
        logger.info('[processar_canhoto] Canhoto criado: id=%s', canhoto_id)

        # -- Step 3: Run OCR
        resultado_ocr = ocr_service.processar_arquivo(caminho_arquivo)
        numero_nota = resultado_ocr.get('numero_nota')
        texto_ocr = resultado_ocr.get('texto', '')
        ocr_sucesso = resultado_ocr.get('sucesso', False)
        ocr_erro = resultado_ocr.get('erro')

        logger.info(
            '[processar_canhoto] OCR concluído: canhoto_id=%s numero_nota=%s sucesso=%s',
            canhoto_id, numero_nota, ocr_sucesso,
        )

        if not ocr_sucesso:
            # OCR failed: mark canhoto as ERRO and move file
            canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.ERRO,
                erro_mensagem=ocr_erro or 'Falha no OCR',
                numero_detectado='',
            )
            _mover_para_erro(caminho_arquivo, f'OCR falhou: {ocr_erro}')
            return {
                'sucesso': False,
                'canhoto_id': canhoto_id,
                'numero_nota': None,
                'mensagem': f'OCR falhou: {ocr_erro}',
            }

        # Update detected number and persist OCR text
        canhoto_repo.atualizar(canhoto, numero_detectado=numero_nota or '', texto_ocr=texto_ocr)

        # -- Step 4: Attempt conciliation if invoice number was found
        if numero_nota:
            conciliacao_service = ConciliacaoService()
            try:
                resultado = conciliacao_service.conciliar(canhoto_id, numero_nota)
                logger.info(
                    '[processar_canhoto] Conciliação bem-sucedida: canhoto_id=%s nota=%s',
                    canhoto_id, numero_nota,
                )
                # -- Step 5: Move to processados
                _mover_para_processados(caminho_arquivo, numero_nota)
                return {
                    'sucesso': True,
                    'canhoto_id': canhoto_id,
                    'numero_nota': numero_nota,
                    'mensagem': resultado.mensagem,
                }
            except NotaFiscalNaoEncontradaException as exc:
                # OCR found a number but it's not in our system
                logger.warning(
                    '[processar_canhoto] Nota não encontrada: canhoto_id=%s numero=%s',
                    canhoto_id, numero_nota,
                )
                canhoto_repo.atualizar(
                    canhoto,
                    status_processamento=StatusProcessamento.ERRO,
                    erro_mensagem=str(exc),
                )
                _mover_para_erro(caminho_arquivo, str(exc))
                return {
                    'sucesso': False,
                    'canhoto_id': canhoto_id,
                    'numero_nota': numero_nota,
                    'mensagem': str(exc),
                }
            except ConciliacaoException as exc:
                logger.error(
                    '[processar_canhoto] ConciliacaoException: canhoto_id=%s erro=%s',
                    canhoto_id, exc,
                )
                canhoto_repo.atualizar(
                    canhoto,
                    status_processamento=StatusProcessamento.ERRO,
                    erro_mensagem=str(exc),
                )
                _mover_para_erro(caminho_arquivo, str(exc))
                return {
                    'sucesso': False,
                    'canhoto_id': canhoto_id,
                    'numero_nota': numero_nota,
                    'mensagem': str(exc),
                }
        else:
            # OCR ran but could not find an invoice number
            mensagem = 'OCR concluído mas número da nota não encontrado no texto.'
            canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.ERRO,
                erro_mensagem=mensagem,
            )
            _mover_para_erro(caminho_arquivo, mensagem)
            return {
                'sucesso': False,
                'canhoto_id': canhoto_id,
                'numero_nota': None,
                'mensagem': mensagem,
            }

    except Exception as exc:
        logger.exception(
            '[processar_canhoto] Exceção inesperada: arquivo=%s canhoto_id=%s tentativa=%d',
            caminho_arquivo, canhoto_id, self.request.retries,
        )

        # Update canhoto status if we managed to create the record
        if canhoto_id:
            try:
                canhoto = canhoto_repo.buscar_por_id(canhoto_id)
                if canhoto:
                    canhoto_repo.atualizar(
                        canhoto,
                        status_processamento=StatusProcessamento.ERRO,
                        erro_mensagem=f'Erro inesperado: {exc}',
                    )
            except Exception:
                pass

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            delay = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
            logger.info(
                '[processar_canhoto] Reagendando (tentativa %d/%d) em %ds',
                self.request.retries + 1, self.max_retries, delay,
            )
            raise self.retry(exc=exc, countdown=delay)

        # Max retries reached: move to error folder
        logger.error(
            '[processar_canhoto] Max retries atingido para %s. Movendo para /erro/',
            caminho_arquivo,
        )
        _mover_para_erro(caminho_arquivo, f'Max retries atingido: {exc}')
        return {
            'sucesso': False,
            'canhoto_id': canhoto_id,
            'numero_nota': None,
            'mensagem': f'Falha após {self.max_retries} tentativas: {exc}',
        }


@shared_task(name='tasks.ocr_tasks.reprocessar_canhoto')
def reprocessar_canhoto(canhoto_id: int) -> dict:
    """
    Re-run OCR on an existing Canhoto record.

    Used when the operator clicks "Reprocessar" in the web UI or admin.
    Does not create a new Canhoto record; updates the existing one.

    Args:
        canhoto_id: primary key of the Canhoto to reprocess.

    Returns:
        dict with keys: sucesso (bool), canhoto_id (int), numero_nota (str|None),
        mensagem (str).
    """
    logger.info('[reprocessar_canhoto] Iniciando: canhoto_id=%s', canhoto_id)

    from apps.canhotos.models import StatusProcessamento
    from repositories.canhoto_repository import CanhotoRepository
    from services.ocr_service import OCRService
    from services.conciliacao_service import ConciliacaoService
    from core.exceptions import NotaFiscalNaoEncontradaException, ConciliacaoException

    canhoto_repo = CanhotoRepository()
    ocr_service = OCRService()

    canhoto = canhoto_repo.buscar_por_id(canhoto_id)
    if canhoto is None:
        logger.error('[reprocessar_canhoto] Canhoto não encontrado: id=%s', canhoto_id)
        return {
            'sucesso': False,
            'canhoto_id': canhoto_id,
            'numero_nota': None,
            'mensagem': f'Canhoto {canhoto_id} não encontrado.',
        }

    # Set status to PROCESSANDO
    canhoto_repo.atualizar(
        canhoto,
        status_processamento=StatusProcessamento.PROCESSANDO,
        erro_mensagem='',
    )

    # Determine the file path
    arquivo_campo = str(canhoto.arquivo)
    if not arquivo_campo:
        msg = f'Canhoto {canhoto_id} não possui arquivo associado.'
        canhoto_repo.atualizar(
            canhoto,
            status_processamento=StatusProcessamento.ERRO,
            erro_mensagem=msg,
        )
        return {'sucesso': False, 'canhoto_id': canhoto_id, 'numero_nota': None, 'mensagem': msg}

    # Resolve absolute path
    from django.conf import settings
    caminho = Path(arquivo_campo)
    if not caminho.is_absolute():
        caminho = Path(settings.MEDIA_ROOT) / arquivo_campo

    if not caminho.exists():
        msg = f'Arquivo do canhoto não encontrado em disco: {caminho}'
        logger.error('[reprocessar_canhoto] %s', msg)
        canhoto_repo.atualizar(
            canhoto,
            status_processamento=StatusProcessamento.ERRO,
            erro_mensagem=msg,
        )
        return {'sucesso': False, 'canhoto_id': canhoto_id, 'numero_nota': None, 'mensagem': msg}

    try:
        resultado_ocr = ocr_service.processar_arquivo(str(caminho))
        numero_nota = resultado_ocr.get('numero_nota')
        texto_ocr = resultado_ocr.get('texto', '')
        ocr_sucesso = resultado_ocr.get('sucesso', False)
        ocr_erro = resultado_ocr.get('erro')

        if not ocr_sucesso:
            canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.ERRO,
                erro_mensagem=ocr_erro or 'Falha no OCR',
                numero_detectado='',
                texto_ocr=texto_ocr,
            )
            return {
                'sucesso': False,
                'canhoto_id': canhoto_id,
                'numero_nota': None,
                'mensagem': f'OCR falhou: {ocr_erro}',
            }

        canhoto_repo.atualizar(canhoto, numero_detectado=numero_nota or '', texto_ocr=texto_ocr)

        if numero_nota:
            # If canhoto already linked to a nota, desvincular first
            if canhoto.nota_id:
                try:
                    ConciliacaoService().desvincular(canhoto_id)
                    # Reload after desvincular
                    canhoto = canhoto_repo.buscar_por_id(canhoto_id)
                except Exception as exc:
                    logger.warning(
                        '[reprocessar_canhoto] Erro ao desvincular antes de reprocessar: %s', exc
                    )

            conciliacao_service = ConciliacaoService()
            try:
                resultado = conciliacao_service.conciliar(canhoto_id, numero_nota)
                logger.info(
                    '[reprocessar_canhoto] Conciliação bem-sucedida: canhoto_id=%s nota=%s',
                    canhoto_id, numero_nota,
                )
                return {
                    'sucesso': True,
                    'canhoto_id': canhoto_id,
                    'numero_nota': numero_nota,
                    'mensagem': resultado.mensagem,
                }
            except (NotaFiscalNaoEncontradaException, ConciliacaoException) as exc:
                canhoto_repo.atualizar(
                    canhoto,
                    status_processamento=StatusProcessamento.ERRO,
                    erro_mensagem=str(exc),
                )
                return {
                    'sucesso': False,
                    'canhoto_id': canhoto_id,
                    'numero_nota': numero_nota,
                    'mensagem': str(exc),
                }
        else:
            msg = 'Reprocessamento OCR concluído mas número da nota não detectado.'
            canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.ERRO,
                erro_mensagem=msg,
            )
            return {
                'sucesso': False,
                'canhoto_id': canhoto_id,
                'numero_nota': None,
                'mensagem': msg,
            }

    except Exception as exc:
        logger.exception('[reprocessar_canhoto] Exceção inesperada: canhoto_id=%s', canhoto_id)
        canhoto_repo.atualizar(
            canhoto,
            status_processamento=StatusProcessamento.ERRO,
            erro_mensagem=f'Erro inesperado: {exc}',
        )
        return {
            'sucesso': False,
            'canhoto_id': canhoto_id,
            'numero_nota': None,
            'mensagem': f'Erro inesperado: {exc}',
        }


# ---------------------------------------------------------------------------
# Internal helpers (not Celery tasks)
# ---------------------------------------------------------------------------

def _mover_para_processados(caminho_arquivo: str, numero_nota: str = '') -> None:
    """Move file to the processados directory. Silently logs on failure."""
    from django.conf import settings
    from pathlib import Path
    processados_dir = getattr(settings, 'SCANNER_PROCESSED_DIR', '/processados')
    destino = Path(processados_dir) / numero_nota if numero_nota else Path(processados_dir)
    try:
        from core.utils import garantir_diretorios, mover_arquivo
        garantir_diretorios(destino)
        mover_arquivo(caminho_arquivo, str(destino))
        logger.info('Arquivo movido para processados: %s -> %s', caminho_arquivo, destino)
    except Exception as exc:
        logger.warning('Falha ao mover arquivo para processados: %s | %s', caminho_arquivo, exc)


def _mover_para_erro(caminho_arquivo: str, motivo: str = '') -> None:
    """Move file to the erro directory. Silently logs on failure."""
    from django.conf import settings
    from pathlib import Path
    erro_dir = getattr(settings, 'SCANNER_ERROR_DIR', '/erro')
    try:
        from core.utils import garantir_diretorios, mover_arquivo
        garantir_diretorios(erro_dir)
        mover_arquivo(caminho_arquivo, erro_dir)
        logger.info('Arquivo movido para erro: %s -> %s | motivo: %s', caminho_arquivo, erro_dir, motivo)
    except Exception as exc:
        logger.warning('Falha ao mover arquivo para erro: %s | %s', caminho_arquivo, exc)
