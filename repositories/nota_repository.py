"""
Repository for NotaFiscal database access.

Architecture:
- All direct ORM queries for NotaFiscal are centralised here.
- Services call this repository; views never query the ORM directly.
- This makes it easy to swap the ORM or add caching without touching business logic.
"""
import logging
from typing import Optional

from django.db.models import QuerySet

from apps.notas.models import NotaFiscal, StatusNota
from core.utils import formatar_numero_nota

logger = logging.getLogger(__name__)


class NotaFiscalRepository:
    """Abstracts all database operations for NotaFiscal."""

    def buscar_por_numero(self, numero: str) -> Optional[NotaFiscal]:
        """
        Find a NotaFiscal by its invoice number.

        Tries both the raw number and the normalized (stripped zeros) version,
        and also a case-insensitive exact match, to tolerate minor OCR noise.

        Args:
            numero: the invoice number string to search for.

        Returns:
            The matching NotaFiscal instance, or None if not found.
        """
        numero_limpo = formatar_numero_nota(numero)
        # Try exact match first
        nota = NotaFiscal.objects.filter(numero=numero).first()
        if nota:
            return nota
        # Try with normalized number (no leading zeros)
        if numero_limpo and numero_limpo != numero:
            nota = NotaFiscal.objects.filter(numero=numero_limpo).first()
            if nota:
                return nota
        # Try case-insensitive contains as last resort
        nota = NotaFiscal.objects.filter(numero__iexact=numero).first()
        return nota

    def buscar_por_id(self, id: int) -> Optional[NotaFiscal]:
        """
        Fetch a NotaFiscal by primary key.

        Args:
            id: primary key integer.

        Returns:
            NotaFiscal instance or None.
        """
        try:
            return NotaFiscal.objects.get(pk=id)
        except NotaFiscal.DoesNotExist:
            return None

    def atualizar_status(self, nota: NotaFiscal, status: str) -> NotaFiscal:
        """
        Update the status field of a NotaFiscal instance and save it.

        Args:
            nota: the NotaFiscal instance to update.
            status: new status value (use StatusNota choices).

        Returns:
            The updated NotaFiscal instance.
        """
        nota.status = status
        nota.save(update_fields=['status', 'updated_at'])
        logger.debug('NotaFiscal status atualizado: id=%s status=%s', nota.id, status)
        return nota

    def listar_aguardando(self) -> QuerySet:
        """
        Return a QuerySet of all NotaFiscal with status AGUARDANDO_CANHOTO.

        Returns:
            Ordered QuerySet (by -created_at).
        """
        return NotaFiscal.objects.filter(
            status=StatusNota.AGUARDANDO_CANHOTO,
        ).order_by('-created_at')

    def criar(self, **kwargs) -> NotaFiscal:
        """
        Create and persist a new NotaFiscal.

        Args:
            **kwargs: field values for the new instance.

        Returns:
            The created NotaFiscal instance.

        Raises:
            django.db.IntegrityError: if numero already exists.
        """
        nota = NotaFiscal.objects.create(**kwargs)
        logger.info('NotaFiscal criada: id=%s numero=%s', nota.id, nota.numero)
        return nota

    def listar_todas(self) -> QuerySet:
        """Return all NotaFiscal records ordered by -created_at."""
        return NotaFiscal.objects.all().order_by('-created_at')
