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
import re
from pathlib import Path
from typing import Optional

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
    tipo='canhoto' -> copies to MEDIA first -> OCR on copy -> links Canhoto -> FINALIZADO
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
        if tipo == 'nota':
            resultado_ocr = ocr_service.processar_arquivo(caminho_arquivo)
            numero_nota = resultado_ocr.get('numero_nota')

            if not numero_nota:
                novo_caminho = canhoto_service.mover_para_erro(caminho_arquivo, 'numero_nota_nao_detectado')
                _logger.warning('[NOTA] Numero nao detectado em %s -> movido para erro', caminho.name)
                return {'status': 'erro', 'motivo': 'numero_nao_detectado', 'arquivo': novo_caminho}

            nota_service = NotaService()
            nota = nota_service.registrar_nota_escaneada(
                numero=numero_nota,
                arquivo_path=caminho_arquivo,
                data_emissao=resultado_ocr.get('data_emissao'),
                destinatario=resultado_ocr.get('destinatario', ''),
                valor_total=resultado_ocr.get('valor_total'),
            )
            novo_caminho = canhoto_service.mover_para_processados(caminho_arquivo, numero_nota)
            _logger.info('[NOTA] NF %s registrada (id=%s) -> %s', numero_nota, nota.id, novo_caminho)
            return {'status': 'sucesso', 'tipo': 'nota', 'numero': numero_nota, 'nota_id': nota.id}

        else:  # tipo == 'canhoto'
            # Se for PDF com múltiplas páginas: divide e enfileira uma tarefa por página
            if caminho.suffix.lower() == '.pdf':
                _aguardar_arquivo_disponivel(caminho)
                n_paginas = ocr_service.contar_paginas_pdf(caminho_arquivo)
                if n_paginas > 1:
                    _logger.info('[CANHOTO] PDF com %d páginas — dividindo em tarefas individuais', n_paginas)
                    paginas = _dividir_canhoto_em_paginas(caminho_arquivo, n_paginas)
                    for i, pagina_path in enumerate(paginas, 1):
                        processar_arquivo.delay(pagina_path, 'canhoto')
                    _logger.info('[CANHOTO] %d tarefas enfileiradas para %s', len(paginas), caminho.name)
                    return {'status': 'dividido', 'paginas': n_paginas, 'arquivo': caminho.name}

            # PDF de página única ou imagem: processa diretamente
            canhoto = None
            pagina_num = _extrair_numero_pagina_do_nome(caminho.name)
            try:
                # Copia para MEDIA primeiro — OCR APENAS na cópia (não trava o arquivo original)
                canhoto, caminho_copia = _criar_canhoto_processando(
                    caminho_arquivo, pagina_numero=pagina_num
                )

                # Usa processamento especializado: OCR + barcode na mesma imagem
                resultado_ocr = ocr_service.processar_pagina_canhoto(caminho_copia)

                # Folha divisória? Não concilia — marca para revisão manual.
                tipo_pagina = resultado_ocr.get('tipo_pagina', 'CANHOTO')
                if tipo_pagina in ('DIVISORIA', 'DIVISORIA_MISTA'):
                    return _tratar_divisoria(canhoto, resultado_ocr, tipo_pagina)

                numero_nota = resultado_ocr.get('numero_nota')

                # Persiste todos os campos extraídos
                campos_extras = {
                    'texto_ocr': resultado_ocr.get('texto', ''),
                    'confianca_deteccao': resultado_ocr.get('confianca', ''),
                }
                if numero_nota:
                    campos_extras['numero_detectado'] = numero_nota
                numero_barcode = resultado_ocr.get('numero_barcode', '')
                if numero_barcode:
                    campos_extras['numero_barcode'] = numero_barcode
                data_recebimento = resultado_ocr.get('data_recebimento')
                if data_recebimento:
                    campos_extras['data_recebimento'] = data_recebimento
                from repositories.canhoto_repository import CanhotoRepository
                CanhotoRepository().atualizar(canhoto, **campos_extras)

                if not numero_nota:
                    _finalizar_canhoto_erro(canhoto, 'numero_nota_nao_detectado_no_ocr')
                    _logger.warning('[CANHOTO] Numero nao detectado em %s', caminho.name)
                    return {'status': 'erro', 'motivo': 'numero_nao_detectado'}

                confianca = resultado_ocr.get('confianca', 'BAIXA')
                if getattr(settings, 'AUTO_VINCULAR_ALTA_CONFIANCA', True) and confianca == 'BAIXA':
                    from apps.canhotos.models import StatusProcessamento as _SP
                    CanhotoRepository().atualizar(
                        canhoto,
                        status_processamento=_SP.REVISAO,
                        erro_mensagem=f'Confiança baixa ({confianca}) — confirmar número manualmente.',
                    )
                    _logger.info('[CANHOTO] Confiança BAIXA → REVISAO: NF=%s', numero_nota)
                    return {'status': 'revisao', 'motivo': 'confianca_baixa', 'numero': numero_nota}

                conciliacao_service = ConciliacaoService()
                try:
                    resultado = conciliacao_service.conciliar(canhoto.id, numero_nota)
                    _logger.info('[CANHOTO] Conciliado NF %s (pág %s)', numero_nota, pagina_num)
                    return {'status': 'sucesso', 'tipo': 'canhoto', 'numero': numero_nota, 'conciliado': resultado.sucesso}
                except Exception as exc_concil:
                    _finalizar_canhoto_erro(canhoto, str(exc_concil))
                    _logger.warning('[CANHOTO] Conciliacao falhou para NF %s: %s', numero_nota, exc_concil)
                    return {'status': 'erro', 'motivo': str(exc_concil), 'numero': numero_nota}

            except Exception as exc:
                if canhoto:
                    _finalizar_canhoto_erro(canhoto, str(exc))
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


def _aguardar_arquivo_disponivel(caminho: 'Path', timeout: int = 60) -> None:
    """
    Aguarda até que o arquivo seja legível (scanner terminou de escrever).
    - Se o arquivo não existir: lança FileNotFoundError imediatamente.
    - Se estiver bloqueado: tenta a cada 3s por até `timeout` segundos.
    """
    import time as _time
    prazo = _time.time() + timeout
    while True:
        if not caminho.exists():
            raise FileNotFoundError(f'Arquivo removido pelo scanner antes de ser copiado: {caminho}')
        try:
            with open(str(caminho), 'rb') as f:
                f.read(1024)
            return  # acessível, pode copiar
        except PermissionError:
            if _time.time() >= prazo:
                raise PermissionError(f'Arquivo ainda bloqueado pelo scanner após {timeout}s: {caminho}')
            logger.debug('Arquivo ainda bloqueado, aguardando: %s', caminho.name)
            _time.sleep(3)


def _copiar_para_media(caminho_arquivo: str) -> str:
    """
    Aguarda o arquivo ser liberado pelo scanner, depois copia para MEDIA_ROOT/canhotos/.
    Retorna o caminho relativo ao MEDIA_ROOT (para salvar no FileField).
    """
    import shutil
    from django.conf import settings
    from pathlib import Path

    origem = Path(caminho_arquivo)

    # Aguarda scanner terminar de escrever o arquivo (evita WinError 32)
    _aguardar_arquivo_disponivel(origem)

    destino_dir = Path(settings.MEDIA_ROOT) / 'canhotos'
    destino_dir.mkdir(parents=True, exist_ok=True)

    from django.utils import timezone
    ts = timezone.now().strftime('%Y%m%d_%H%M%S_%f')
    nome_destino = f"{ts}_{origem.name}"
    destino = destino_dir / nome_destino

    shutil.copy2(str(origem), str(destino))
    logger.info('Arquivo copiado para media: %s -> %s', origem.name, destino)

    return str(Path('canhotos') / nome_destino)


def _salvar_texto_ocr(canhoto, texto: str) -> None:
    """Helper: persist extracted OCR text on the Canhoto record."""
    if texto:
        from repositories.canhoto_repository import CanhotoRepository
        CanhotoRepository().atualizar(canhoto, texto_ocr=texto)


def _extrair_numero_pagina_do_nome(nome_arquivo: str) -> Optional[int]:
    """Extrai o número da página do nome do arquivo (ex: '...20260615_p003.pdf' → 3)."""
    m = re.search(r'_p(\d{3})\.pdf$', nome_arquivo, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _dividir_canhoto_em_paginas(caminho_arquivo: str, n_paginas: int) -> list:
    """
    Aguarda o arquivo ser liberado, copia para MEDIA_ROOT e divide em páginas individuais.
    Retorna lista de caminhos absolutos dos PDFs de página única.
    """
    from services.ocr_service import OCRService
    from django.conf import settings
    from pathlib import Path
    from django.utils import timezone

    caminho = Path(caminho_arquivo)
    _aguardar_arquivo_disponivel(caminho)

    ts = timezone.now().strftime('%Y%m%d_%H%M%S_%f')
    stem = f'{ts}_{caminho.stem}'

    destino_dir = Path(settings.MEDIA_ROOT) / 'canhotos' / 'paginas'
    destino_dir.mkdir(parents=True, exist_ok=True)

    # Cria um PDF temporário no destino para usar como base da divisão
    import shutil
    pdf_temp = destino_dir / f'{stem}.pdf'
    shutil.copy2(str(caminho), str(pdf_temp))

    paginas = OCRService.dividir_pdf_em_paginas(str(pdf_temp), str(destino_dir))

    # Remove o PDF completo temporário após dividir
    try:
        pdf_temp.unlink()
    except Exception:
        pass

    logger.info('[CANHOTO] PDF dividido: %d páginas em %s', n_paginas, destino_dir)
    return paginas


def _criar_canhoto_processando(caminho_arquivo: str, pagina_numero: Optional[int] = None):
    """
    Copia o arquivo para MEDIA_ROOT (se ainda não estiver lá) e cria o registro
    Canhoto com status PROCESSANDO. Retorna (canhoto, caminho_absoluto_copia).
    """
    from repositories.canhoto_repository import CanhotoRepository
    from apps.canhotos.models import StatusProcessamento
    from django.conf import settings
    from pathlib import Path

    media_root = Path(settings.MEDIA_ROOT)
    caminho = Path(caminho_arquivo)

    # Se o arquivo já está dentro do MEDIA_ROOT (ex: página já dividida), não copia
    try:
        caminho_relativo = str(caminho.relative_to(media_root))
        caminho_absoluto = str(caminho)
    except ValueError:
        # Arquivo fora do MEDIA_ROOT → copiar agora
        caminho_relativo = _copiar_para_media(caminho_arquivo)
        caminho_absoluto = str(media_root / caminho_relativo)

    repo = CanhotoRepository()
    canhoto = repo.criar(
        arquivo=caminho_relativo,
        status_processamento=StatusProcessamento.PROCESSANDO,
        pagina_numero=pagina_numero,
    )
    return canhoto, caminho_absoluto


def _tratar_divisoria(canhoto, resultado_ocr: dict, tipo_pagina: str) -> dict:
    """
    Trata uma folha divisória detectada.

    Com AUTO_VINCULAR_ALTA_CONFIANCA habilitado, canhotos com confiança ALTA
    são automaticamente vinculados às notas fiscais correspondentes.
    Canhotos com confiança MEDIA ou BAIXA vão para REVISAO.
    """
    from repositories.canhoto_repository import CanhotoRepository
    from apps.canhotos.models import StatusProcessamento, TipoPagina
    from services.conciliacao_service import ConciliacaoService

    auto_vincular = getattr(settings, 'AUTO_VINCULAR_ALTA_CONFIANCA', True)
    repo = CanhotoRepository()
    sequencia = resultado_ocr.get('numeros_sequencia', [])
    numeros_lista = ', '.join(str(n) for n in sequencia)
    texto_ocr = resultado_ocr.get('texto', '')
    canhotos_info = resultado_ocr.get('canhotos_info', [])

    tipo_enum = (
        TipoPagina.DIVISORIA_MISTA if tipo_pagina == 'DIVISORIA_MISTA' else TipoPagina.DIVISORIA
    )

    filhos = []
    auto_vinculados = []
    revisao = []

    if tipo_pagina == 'DIVISORIA_MISTA' and canhotos_info:
        conciliacao_service = ConciliacaoService()

        for info in canhotos_info:
            numero = info.get('numero', '')
            confianca = info.get('confianca', 'BAIXA')
            origem = info.get('origem', '')
            if not numero:
                continue

            if auto_vincular and confianca == 'ALTA':
                filho = repo.criar(
                    arquivo=str(canhoto.arquivo),
                    status_processamento=StatusProcessamento.PROCESSANDO,
                    tipo_pagina=TipoPagina.CANHOTO,
                    numero_detectado=numero,
                    confianca_deteccao=confianca,
                    pagina_numero=canhoto.pagina_numero,
                    texto_ocr=texto_ocr,
                )
                filhos.append(filho.id)
                try:
                    conciliacao_service.conciliar(filho.id, numero)
                    auto_vinculados.append(numero)
                    logger.info(
                        '[DIVISÓRIA] Auto-vinculado: filho=%s NF=%s [%s via %s]',
                        filho.id, numero, confianca, origem,
                    )
                except Exception as exc:
                    repo.atualizar(
                        filho,
                        status_processamento=StatusProcessamento.REVISAO,
                        erro_mensagem=f'Auto-vinculação falhou: {exc}',
                    )
                    revisao.append(numero)
                    logger.warning(
                        '[DIVISÓRIA] Auto-vinculação falhou NF %s: %s', numero, exc,
                    )
            else:
                filho = repo.criar(
                    arquivo=str(canhoto.arquivo),
                    status_processamento=StatusProcessamento.REVISAO,
                    tipo_pagina=TipoPagina.CANHOTO,
                    numero_detectado=numero,
                    confianca_deteccao=confianca,
                    pagina_numero=canhoto.pagina_numero,
                    texto_ocr=texto_ocr,
                    erro_mensagem=f'Confirmar manualmente (confiança {confianca}, via {origem}).',
                )
                filhos.append(filho.id)
                revisao.append(numero)

    elif tipo_pagina == 'DIVISORIA_MISTA':
        for stub in resultado_ocr.get('numeros_canhotos', []):
            if not stub:
                continue
            filho = repo.criar(
                arquivo=str(canhoto.arquivo),
                status_processamento=StatusProcessamento.REVISAO,
                tipo_pagina=TipoPagina.CANHOTO,
                numero_detectado=stub,
                confianca_deteccao='BAIXA',
                pagina_numero=canhoto.pagina_numero,
                erro_mensagem='Canhoto extraído de folha divisória — confirmar manualmente.',
            )
            filhos.append(filho.id)
            revisao.append(stub)

    if auto_vinculados and not revisao:
        parent_status = StatusProcessamento.SUCESSO
        msg = f'Divisória processada: {len(auto_vinculados)} canhoto(s) vinculado(s) automaticamente.'
    elif auto_vinculados:
        parent_status = StatusProcessamento.REVISAO
        msg = (
            f'{len(auto_vinculados)} vinculado(s) automaticamente, '
            f'{len(revisao)} aguardando revisão.'
        )
    else:
        parent_status = StatusProcessamento.REVISAO
        msg = (
            'Folha divisória com canhotos colados — confira e valide manualmente.'
            if tipo_pagina == 'DIVISORIA_MISTA'
            else 'Folha divisória detectada — valide se todos os canhotos foram recebidos.'
        )

    repo.atualizar(
        canhoto,
        tipo_pagina=tipo_enum,
        status_processamento=parent_status,
        numeros_lista=numeros_lista,
        numero_detectado='',
        confianca_deteccao='',
        texto_ocr=texto_ocr,
        erro_mensagem=msg,
    )

    logger.info(
        '[CANHOTO] Divisória %s (id=%s): %d números, %d filho(s), %d auto, %d revisão',
        tipo_pagina, canhoto.id, len(sequencia), len(filhos),
        len(auto_vinculados), len(revisao),
    )
    return {
        'status': 'divisoria',
        'tipo': tipo_pagina,
        'canhoto_id': canhoto.id,
        'numeros': sequencia,
        'filhos': filhos,
        'auto_vinculados': auto_vinculados,
        'revisao': revisao,
    }


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

        # Update detected number, date and persist OCR text
        campos_canhoto = {'numero_detectado': numero_nota or '', 'texto_ocr': texto_ocr}
        data_recebimento = resultado_ocr.get('data_recebimento')
        if data_recebimento:
            campos_canhoto['data_recebimento'] = data_recebimento
        canhoto_repo.atualizar(canhoto, **campos_canhoto)

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
        resultado_ocr = ocr_service.processar_pagina_canhoto(str(caminho))

        tipo_pagina = resultado_ocr.get('tipo_pagina', 'CANHOTO')
        if tipo_pagina in ('DIVISORIA', 'DIVISORIA_MISTA'):
            resultado = _tratar_divisoria(canhoto, resultado_ocr, tipo_pagina)
            return {
                'sucesso': True,
                'canhoto_id': canhoto_id,
                'numero_nota': None,
                'mensagem': f'Folha divisória detectada ({tipo_pagina}).',
                **resultado,
            }

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
