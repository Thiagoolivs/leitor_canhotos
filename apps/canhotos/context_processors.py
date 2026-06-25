"""
Context processors for Canhotos — exposes counters used in the navbar
(e.g. the "Revisão" and "Erros" tab badges) on every page without each
view needing to compute it explicitly.
"""
from apps.canhotos.models import Canhoto, StatusProcessamento


def revisao_pendente_count(request):
    try:
        count = Canhoto.objects.filter(status_processamento=StatusProcessamento.REVISAO).count()
    except Exception:
        count = 0
    return {'revisao_pendente_count': count}


def erro_count(request):
    try:
        count = Canhoto.objects.filter(status_processamento=StatusProcessamento.ERRO).count()
    except Exception:
        count = 0
    return {'erro_count': count}


def processando_count(request):
    try:
        count = Canhoto.objects.filter(
            status_processamento__in=[StatusProcessamento.PENDENTE, StatusProcessamento.PROCESSANDO],
        ).count()
    except Exception:
        count = 0
    return {'processando_count': count}
