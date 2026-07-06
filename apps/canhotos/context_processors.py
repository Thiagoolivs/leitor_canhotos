"""
Context processors for Canhotos — expõe os contadores da navbar (badges de
Revisão, Erros e Processando) em todas as páginas.

Um único processor com uma única query agregada — antes eram três processors
com três queries COUNT separadas por página renderizada.
"""
from django.db.models import Count, Q

from apps.canhotos.models import Canhoto, StatusProcessamento


def contadores_navbar(request):
    try:
        contagem = Canhoto.objects.aggregate(
            revisao=Count('id', filter=Q(status_processamento=StatusProcessamento.REVISAO)),
            erro=Count('id', filter=Q(status_processamento=StatusProcessamento.ERRO)),
            processando=Count('id', filter=Q(status_processamento__in=[
                StatusProcessamento.PENDENTE, StatusProcessamento.PROCESSANDO,
            ])),
        )
        return {
            'revisao_pendente_count': contagem['revisao'],
            'erro_count': contagem['erro'],
            'processando_count': contagem['processando'],
        }
    except Exception:
        return {'revisao_pendente_count': 0, 'erro_count': 0, 'processando_count': 0}
