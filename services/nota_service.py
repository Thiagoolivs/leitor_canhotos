"""
Service layer for Nota Fiscal business logic.

Architecture:
- All business rules for creating, importing, and updating Notas Fiscais live here.
- Views and tasks call this service; they do not touch the ORM directly.
- Uses NotaFiscalRepository for all database access.
"""
import logging
from datetime import date
from typing import Optional

from django.db import IntegrityError

from apps.notas.models import NotaFiscal, StatusNota
from core.exceptions import NotaFiscalNaoEncontradaException
from core.utils import formatar_numero_nota
from repositories.nota_repository import NotaFiscalRepository

logger = logging.getLogger(__name__)


class NotaService:
    """
    Business logic for Notas Fiscais.

    Methods:
        criar_nota(numero, data_emissao, categoria) -> NotaFiscal
        importar_lote(lista_notas) -> dict
        atualizar_status(nota_id, status) -> NotaFiscal
        buscar_nota(numero) -> Optional[NotaFiscal]
    """

    def __init__(self):
        self.nota_repo = NotaFiscalRepository()
        self.logger = logging.getLogger(__name__)

    def criar_nota(
        self,
        numero: str,
        data_emissao,
        categoria: str = '',
        status: str = StatusNota.AGUARDANDO_CANHOTO,
    ) -> NotaFiscal:
        """
        Create a new Nota Fiscal.

        The invoice number is normalized (leading zeros stripped) before saving.

        Args:
            numero: invoice number string.
            data_emissao: date object or string (YYYY-MM-DD) for emission date.
            categoria: optional category label.
            status: initial status (defaults to AGUARDANDO_CANHOTO).

        Returns:
            The newly created NotaFiscal instance.

        Raises:
            ValueError: if numero is empty or already exists.
        """
        numero_normalizado = formatar_numero_nota(numero)
        if not numero_normalizado:
            raise ValueError('Número da nota não pode estar vazio.')

        # Check for duplicates
        existente = self.nota_repo.buscar_por_numero(numero_normalizado)
        if existente:
            raise ValueError(f'Nota Fiscal com número {numero_normalizado} já existe (id={existente.id}).')

        nota = self.nota_repo.criar(
            numero=numero_normalizado,
            data_emissao=data_emissao,
            categoria=categoria,
            status=status,
        )
        self.logger.info('NotaFiscal criada via NotaService: id=%s numero=%s', nota.id, nota.numero)
        self._retro_conciliar(nota)
        return nota

    def _retro_conciliar(self, nota) -> None:
        """
        Após registrar uma nota, procura canhotos que já esperavam por ela
        (em ERRO/REVISAO/PENDENTE) e concilia automaticamente. Falha silenciosa:
        a criação da nota nunca deve ser bloqueada por isso.
        """
        try:
            from services.conciliacao_service import ConciliacaoService
            ConciliacaoService().conciliar_pendentes_para_nota(nota)
        except Exception as exc:
            self.logger.warning('Retro-conciliação ignorada para NF %s: %s', nota.numero, exc)

    def importar_lote(self, lista_notas: list) -> dict:
        """
        Import multiple Notas Fiscais from a list of dicts.

        Each dict should have keys: 'numero', 'data_emissao', optionally 'categoria'.
        Skips duplicates and collects errors without aborting the entire import.

        Args:
            lista_notas: list of dicts, each with at least 'numero' and 'data_emissao'.

        Returns:
            A dict with:
                - 'criadas' (int): number of successfully created notas.
                - 'ignoradas' (int): number of skipped duplicates.
                - 'erros' (list[str]): list of error messages for failed records.
        """
        criadas = 0
        ignoradas = 0
        erros = []

        for item in lista_notas:
            numero = str(item.get('numero', '')).strip()
            data_emissao = item.get('data_emissao')
            categoria = str(item.get('categoria', '')).strip()

            if not numero:
                erros.append('Item sem número da nota ignorado.')
                continue
            if not data_emissao:
                erros.append(f'Nota {numero}: data_emissao não informada.')
                continue

            try:
                self.criar_nota(numero, data_emissao, categoria)
                criadas += 1
            except ValueError as exc:
                if 'já existe' in str(exc):
                    ignoradas += 1
                    self.logger.debug('Nota duplicada ignorada: %s', numero)
                else:
                    erros.append(f'Nota {numero}: {exc}')
            except IntegrityError as exc:
                ignoradas += 1
                self.logger.debug('IntegrityError para nota %s (duplicada): %s', numero, exc)
            except Exception as exc:
                erros.append(f'Nota {numero}: erro inesperado - {exc}')
                self.logger.exception('Erro ao importar nota %s', numero)

        self.logger.info(
            'Importação em lote concluída: criadas=%d ignoradas=%d erros=%d',
            criadas, ignoradas, len(erros),
        )
        return {'criadas': criadas, 'ignoradas': ignoradas, 'erros': erros}

    def atualizar_status(self, nota_id: int, status: str) -> NotaFiscal:
        """
        Update the status of a Nota Fiscal.

        Args:
            nota_id: primary key of the NotaFiscal.
            status: new status value (use StatusNota constants).

        Returns:
            The updated NotaFiscal instance.

        Raises:
            NotaFiscalNaoEncontradaException: if nota_id does not exist.
            ValueError: if status is not a valid StatusNota value.
        """
        valid_statuses = [choice[0] for choice in StatusNota.choices]
        if status not in valid_statuses:
            raise ValueError(f'Status inválido: {status}. Valores válidos: {valid_statuses}')

        nota = self.nota_repo.buscar_por_id(nota_id)
        if nota is None:
            raise NotaFiscalNaoEncontradaException(
                f'Nota Fiscal com id={nota_id} não encontrada.',
                numero=str(nota_id),
            )

        nota_atualizada = self.nota_repo.atualizar_status(nota, status)
        self.logger.info(
            'Status da NotaFiscal atualizado: id=%s status=%s',
            nota_id, status,
        )
        return nota_atualizada

    def registrar_nota_escaneada(
        self,
        numero: str,
        arquivo_path: str,
        data_emissao=None,
        destinatario: str = '',
        valor_total=None,
    ) -> NotaFiscal:
        """
        Register or update a NotaFiscal from a scanned invoice file.
        If nota already exists, updates extracted fields and returns it.
        """
        numero_formatado = formatar_numero_nota(numero)
        nota = self.nota_repo.buscar_por_numero(numero_formatado)
        if nota:
            self.logger.info('NotaFiscal %s ja existe (id=%s), atualizando dados OCR', numero_formatado, nota.id)
            campos = {}
            if data_emissao and not nota.data_emissao:
                campos['data_emissao'] = data_emissao
            if destinatario and not nota.destinatario:
                campos['destinatario'] = destinatario
            if valor_total is not None and nota.valor_total is None:
                campos['valor_total'] = valor_total
            if campos:
                for k, v in campos.items():
                    setattr(nota, k, v)
                nota.save(update_fields=list(campos.keys()) + ['updated_at'])
            return nota
        nota = self.nota_repo.criar(
            numero=numero_formatado,
            data_emissao=data_emissao or date.today(),
            destinatario=destinatario,
            valor_total=valor_total,
            status=StatusNota.AGUARDANDO_CANHOTO,
        )
        self.logger.info('NotaFiscal criada automaticamente: numero=%s id=%s', numero_formatado, nota.id)
        self._retro_conciliar(nota)
        return nota

    def buscar_nota(self, numero: str) -> Optional[NotaFiscal]:
        """
        Find a Nota Fiscal by invoice number.

        Normalizes the number before searching to handle leading-zero variations.

        Args:
            numero: invoice number string.

        Returns:
            The NotaFiscal instance, or None if not found.
        """
        numero_normalizado = formatar_numero_nota(numero) if numero else ''
        if not numero_normalizado:
            return None
        return self.nota_repo.buscar_por_numero(numero_normalizado)
