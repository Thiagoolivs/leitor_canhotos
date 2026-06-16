"""
Conciliation Service: links Canhotos to Notas Fiscais.

Architecture:
- Provides three operations: conciliar (auto), vincular_manual, desvincular.
- All three update both the Canhoto and the NotaFiscal statuses atomically
  within a Django database transaction.
- Uses NotaFiscalRepository and CanhotoRepository for all database access.
- Raises domain exceptions from core.exceptions on failure.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from apps.canhotos.models import StatusProcessamento
from apps.notas.models import StatusNota
from core.exceptions import ConciliacaoException, NotaFiscalNaoEncontradaException
from repositories.canhoto_repository import CanhotoRepository
from repositories.nota_repository import NotaFiscalRepository

logger = logging.getLogger(__name__)


@dataclass
class ConciliacaoResultado:
    """
    Result object returned by every ConciliacaoService operation.

    Attributes:
        sucesso: True if the operation completed without errors.
        canhoto_id: ID of the canhoto involved.
        nota_numero: invoice number of the nota involved (empty string if none).
        mensagem: human-readable description of the outcome.
    """
    sucesso: bool
    canhoto_id: int
    nota_numero: str
    mensagem: str


class ConciliacaoService:
    """
    Business logic for reconciling Canhotos with Notas Fiscais.

    Methods:
        conciliar(canhoto_id, numero_nota) -> ConciliacaoResultado
        vincular_manual(canhoto_id, nota_id) -> ConciliacaoResultado
        desvincular(canhoto_id) -> None
    """

    def __init__(self):
        self.nota_repo = NotaFiscalRepository()
        self.canhoto_repo = CanhotoRepository()
        self.logger = logging.getLogger(__name__)

    @transaction.atomic
    def conciliar(self, canhoto_id: int, numero_nota: str) -> ConciliacaoResultado:
        """
        Automatically link a canhoto to a nota fiscal by invoice number.

        Steps:
        1. Fetch the canhoto by ID.
        2. Look up the nota by numero_nota.
        3. Link them (canhoto.nota = nota).
        4. Update canhoto status -> SUCESSO.
        5. Update nota status -> FINALIZADO.

        Args:
            canhoto_id: primary key of the Canhoto to update.
            numero_nota: invoice number extracted by OCR.

        Returns:
            ConciliacaoResultado describing the outcome.

        Raises:
            ConciliacaoException: if canhoto not found or nota is already finalized.
            NotaFiscalNaoEncontradaException: if no nota matches numero_nota.
        """
        self.logger.info(
            'Iniciando conciliação: canhoto_id=%s numero_nota=%s',
            canhoto_id, numero_nota,
        )

        canhoto = self.canhoto_repo.buscar_por_id(canhoto_id)
        if canhoto is None:
            raise ConciliacaoException(
                f'Canhoto não encontrado: id={canhoto_id}',
                canhoto_id=canhoto_id,
            )

        nota = self.nota_repo.buscar_por_numero(numero_nota)
        if nota is None:
            # Update canhoto to ERRO because nota wasn't found
            self.canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.ERRO,
                erro_mensagem=f'Nota Fiscal não encontrada no sistema: {numero_nota}',
                numero_detectado=numero_nota,
            )
            raise NotaFiscalNaoEncontradaException(
                f'Nota Fiscal {numero_nota} não encontrada no sistema.',
                numero=numero_nota,
            )

        if nota.status == StatusNota.FINALIZADO:
            raise ConciliacaoException(
                f'Nota Fiscal {nota.numero} já está Finalizada. '
                'Desvincule o canhoto existente antes de conciliar novamente.',
                canhoto_id=canhoto_id,
                nota_numero=nota.numero,
            )

        # Perform the link
        canhoto.nota = nota
        canhoto.numero_detectado = numero_nota
        canhoto.status_processamento = StatusProcessamento.SUCESSO
        canhoto.erro_mensagem = ''
        canhoto.save(update_fields=['nota', 'numero_detectado', 'status_processamento', 'erro_mensagem', 'updated_at'])

        self.nota_repo.atualizar_status(nota, StatusNota.FINALIZADO)

        self.logger.info(
            'Conciliação bem-sucedida: canhoto_id=%s nota_id=%s nota_numero=%s',
            canhoto_id, nota.id, nota.numero,
        )

        return ConciliacaoResultado(
            sucesso=True,
            canhoto_id=canhoto_id,
            nota_numero=nota.numero,
            mensagem=f'Canhoto {canhoto_id} conciliado com Nota Fiscal {nota.numero}.',
        )

    @transaction.atomic
    def vincular_manual(self, canhoto_id: int, nota_id: int) -> ConciliacaoResultado:
        """
        Manually link a canhoto to a specific nota fiscal by nota ID.

        Unlike conciliar(), this uses nota_id (not invoice number), intended for
        operator-driven corrections via the web interface.

        Args:
            canhoto_id: primary key of the Canhoto.
            nota_id: primary key of the NotaFiscal to link to.

        Returns:
            ConciliacaoResultado describing the outcome.

        Raises:
            ConciliacaoException: if either record is not found or nota is already finalized.
        """
        self.logger.info(
            'Vínculo manual: canhoto_id=%s nota_id=%s',
            canhoto_id, nota_id,
        )

        canhoto = self.canhoto_repo.buscar_por_id(canhoto_id)
        if canhoto is None:
            raise ConciliacaoException(
                f'Canhoto não encontrado: id={canhoto_id}',
                canhoto_id=canhoto_id,
            )

        nota = self.nota_repo.buscar_por_id(nota_id)
        if nota is None:
            raise ConciliacaoException(
                f'Nota Fiscal não encontrada: id={nota_id}',
                canhoto_id=canhoto_id,
            )

        if nota.status == StatusNota.FINALIZADO:
            raise ConciliacaoException(
                f'Nota Fiscal {nota.numero} já está Finalizada.',
                canhoto_id=canhoto_id,
                nota_numero=nota.numero,
            )

        # If canhoto was previously linked to a different nota, reset that nota's status
        if canhoto.nota_id and canhoto.nota_id != nota_id:
            nota_anterior = self.nota_repo.buscar_por_id(canhoto.nota_id)
            if nota_anterior:
                self.nota_repo.atualizar_status(nota_anterior, StatusNota.AGUARDANDO_CANHOTO)
                self.logger.info(
                    'Nota anterior redefinida para AGUARDANDO_CANHOTO: id=%s',
                    nota_anterior.id,
                )

        canhoto.nota = nota
        canhoto.status_processamento = StatusProcessamento.SUCESSO
        canhoto.erro_mensagem = ''
        canhoto.save(update_fields=['nota', 'status_processamento', 'erro_mensagem', 'updated_at'])

        self.nota_repo.atualizar_status(nota, StatusNota.FINALIZADO)

        self.logger.info(
            'Vínculo manual bem-sucedido: canhoto_id=%s nota_id=%s nota_numero=%s',
            canhoto_id, nota_id, nota.numero,
        )

        return ConciliacaoResultado(
            sucesso=True,
            canhoto_id=canhoto_id,
            nota_numero=nota.numero,
            mensagem=f'Canhoto {canhoto_id} vinculado manualmente à Nota Fiscal {nota.numero}.',
        )

    @transaction.atomic
    def vincular_divisoria(self, canhoto_id: int, numeros: list) -> dict:
        """
        Attribute one or more Notas Fiscais to a single divider-sheet canhoto
        (tipo_pagina DIVISORIA/DIVISORIA_MISTA), which legitimately covers
        many notas at once via canhoto.notas_atendidas (M2M).

        For each numero: looks up the NotaFiscal, links it via notas_atendidas,
        and marks it FINALIZADO. Numbers without a matching nota, or notas
        already finalized by a different canhoto, are reported but skipped.

        Args:
            canhoto_id: primary key of the divider-sheet Canhoto.
            numeros: list of invoice numbers (str) to attribute to this canhoto.

        Returns:
            dict with keys: vinculadas, nao_encontradas, ja_finalizadas (lists of str).

        Raises:
            ConciliacaoException: if the canhoto is not found.
        """
        canhoto = self.canhoto_repo.buscar_por_id(canhoto_id)
        if canhoto is None:
            raise ConciliacaoException(
                f'Canhoto não encontrado: id={canhoto_id}',
                canhoto_id=canhoto_id,
            )

        vinculadas, nao_encontradas, ja_finalizadas = [], [], []
        for numero in numeros:
            numero = (numero or '').strip()
            if not numero:
                continue
            nota = self.nota_repo.buscar_por_numero(numero)
            if nota is None:
                nao_encontradas.append(numero)
                continue
            ja_atribuida = canhoto.notas_atendidas.filter(pk=nota.pk).exists()
            if nota.status == StatusNota.FINALIZADO and not ja_atribuida:
                ja_finalizadas.append(numero)
                continue
            canhoto.notas_atendidas.add(nota)
            self.nota_repo.atualizar_status(nota, StatusNota.FINALIZADO)
            vinculadas.append(numero)

        # Se todos os números detectados na divisória já têm uma nota
        # atribuída, a revisão manual está concluída — marca como SUCESSO
        # para que o canhoto saia da fila de "aguardando revisão".
        revisao_concluida = False
        numeros_esperados = canhoto.numeros_lista_items
        if numeros_esperados and canhoto.notas_atendidas.count() >= len(numeros_esperados):
            self.canhoto_repo.atualizar(
                canhoto,
                status_processamento=StatusProcessamento.SUCESSO,
                erro_mensagem='',
            )
            revisao_concluida = True

        self.logger.info(
            'Vínculo de divisória: canhoto_id=%s vinculadas=%s nao_encontradas=%s ja_finalizadas=%s revisao_concluida=%s',
            canhoto_id, vinculadas, nao_encontradas, ja_finalizadas, revisao_concluida,
        )

        return {
            'vinculadas': vinculadas,
            'nao_encontradas': nao_encontradas,
            'ja_finalizadas': ja_finalizadas,
            'revisao_concluida': revisao_concluida,
        }

    @transaction.atomic
    def desvincular(self, canhoto_id: int) -> None:
        """
        Unlink a canhoto from its nota fiscal and reset both statuses.

        The canhoto status is reset to PENDENTE; the nota status is reset to
        AGUARDANDO_CANHOTO.

        Args:
            canhoto_id: primary key of the Canhoto to unlink.

        Raises:
            ConciliacaoException: if the canhoto is not found or is not currently linked.
        """
        self.logger.info('Desvinculando canhoto: canhoto_id=%s', canhoto_id)

        canhoto = self.canhoto_repo.buscar_por_id(canhoto_id)
        if canhoto is None:
            raise ConciliacaoException(
                f'Canhoto não encontrado: id={canhoto_id}',
                canhoto_id=canhoto_id,
            )

        if canhoto.nota_id is None:
            raise ConciliacaoException(
                f'Canhoto {canhoto_id} não está vinculado a nenhuma Nota Fiscal.',
                canhoto_id=canhoto_id,
            )

        nota = self.nota_repo.buscar_por_id(canhoto.nota_id)

        canhoto.nota = None
        canhoto.status_processamento = StatusProcessamento.PENDENTE
        canhoto.erro_mensagem = ''
        canhoto.save(update_fields=['nota', 'status_processamento', 'erro_mensagem', 'updated_at'])

        if nota:
            self.nota_repo.atualizar_status(nota, StatusNota.AGUARDANDO_CANHOTO)

        self.logger.info(
            'Canhoto desvinculado: canhoto_id=%s nota_id=%s',
            canhoto_id, nota.id if nota else None,
        )
