"""
Repository for Canhoto database access.

Architecture:
- All direct ORM queries for Canhoto are centralised here.
- Services call this repository; views never query the ORM directly.
"""
import logging
from typing import Optional

from django.db.models import QuerySet

from apps.canhotos.models import Canhoto, StatusProcessamento

logger = logging.getLogger(__name__)


class CanhotoRepository:
    """Abstracts all database operations for Canhoto."""

    def criar(self, **kwargs) -> Canhoto:
        """
        Create and persist a new Canhoto record.

        Args:
            **kwargs: field values for the new instance.

        Returns:
            The created Canhoto instance.
        """
        canhoto = Canhoto.objects.create(**kwargs)
        logger.info('Canhoto criado: id=%s arquivo=%s', canhoto.id, canhoto.arquivo)
        return canhoto

    def buscar_por_id(self, id: int) -> Optional[Canhoto]:
        """
        Fetch a Canhoto by primary key.

        Args:
            id: primary key integer.

        Returns:
            Canhoto instance or None if not found.
        """
        try:
            return Canhoto.objects.select_related('nota').get(pk=id)
        except Canhoto.DoesNotExist:
            return None

    def atualizar(self, canhoto: Canhoto, **kwargs) -> Canhoto:
        """
        Update fields on a Canhoto instance and save it.

        Only the fields provided in kwargs are updated; updated_at is always included.

        Args:
            canhoto: the Canhoto instance to modify.
            **kwargs: field names and new values to set.

        Returns:
            The updated Canhoto instance.
        """
        update_fields = list(kwargs.keys()) + ['updated_at']
        for field, value in kwargs.items():
            setattr(canhoto, field, value)
        canhoto.save(update_fields=update_fields)
        logger.debug('Canhoto atualizado: id=%s campos=%s', canhoto.id, list(kwargs.keys()))
        return canhoto

    def listar_com_erro(self) -> QuerySet:
        """
        Return a QuerySet of all Canhotos with status ERRO.

        Returns:
            Ordered QuerySet (by -created_at).
        """
        return Canhoto.objects.filter(
            status_processamento=StatusProcessamento.ERRO,
        ).order_by('-created_at')

    def listar_pendentes(self) -> QuerySet:
        """Return all Canhotos with status PENDENTE."""
        return Canhoto.objects.filter(
            status_processamento=StatusProcessamento.PENDENTE,
        ).order_by('-created_at')

    def listar_todos(self) -> QuerySet:
        """Return all Canhoto records ordered by -created_at."""
        return Canhoto.objects.all().select_related('nota').order_by('-created_at')
