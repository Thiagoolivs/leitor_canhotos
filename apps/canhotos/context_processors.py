"""
Context processors for Canhotos — exposes counters used in the navbar
(e.g. the "Revisão" tab badge) on every page without each view needing
to compute it explicitly.
"""
from apps.canhotos.models import Canhoto, StatusProcessamento


def revisao_pendente_count(request):
    try:
        count = Canhoto.objects.filter(status_processamento=StatusProcessamento.REVISAO).count()
    except Exception:
        count = 0
    return {'revisao_pendente_count': count}
