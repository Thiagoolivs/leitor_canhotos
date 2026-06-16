"""
Views for Canhotos.

Uses class-based views throughout.
- CanhotoListView: paginated list with filtering
- CanhotoDetailView: detail with file preview
- ReprocessarOCRView: POST only, triggers Celery reprocessing task
- VincularManualView: POST only, manually links canhoto to a nota fiscal
"""
import logging
import mimetypes
import os

from django.contrib import messages
from django.db.models import Case, CharField, F, Func, IntegerField, Value, When
from django.db.models.functions import Cast
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import ListView, DetailView

from apps.canhotos.forms import CanhotoFilterSet, CorrigirNumeroForm, VincularManualForm
from apps.canhotos.models import Canhoto, StatusProcessamento
from core.mixins import PersistedFilterMixin

logger = logging.getLogger(__name__)


class CanhotoListView(PersistedFilterMixin, ListView):
    """
    Paginated list of all canhotos with status and filtering support.
    Filters persist across navigation via session (see PersistedFilterMixin).
    """
    model = Canhoto
    template_name = 'canhotos/lista.html'
    context_object_name = 'canhotos'
    paginate_by = 20
    session_key = 'canhotos_filtros'

    def get_queryset(self):
        # numero_detectado pode conter texto/vazio; remove tudo que não é
        # dígito antes de converter para inteiro, tratando o resultado vazio
        # como NULL para ordenar os não-numéricos sempre por último.
        numero_limpo = Func(
            F('numero_detectado'), Value(r'\D'), Value(''), Value('g'),
            function='regexp_replace', output_field=CharField(),
        )
        queryset = Canhoto.objects.annotate(
            numero_limpo=numero_limpo,
        ).annotate(
            numero_int=Case(
                When(numero_limpo='', then=Value(None)),
                default=Cast('numero_limpo', IntegerField()),
                output_field=IntegerField(),
            ),
        ).select_related('nota')
        self.filterset = CanhotoFilterSet(self.request.GET, queryset=queryset)
        ordem = self.request.GET.get('ordem', 'desc')
        if ordem == 'asc':
            return self.filterset.qs.order_by(F('numero_int').asc(nulls_last=True))
        return self.filterset.qs.order_by(F('numero_int').desc(nulls_last=True))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filterset'] = self.filterset
        context['total_count'] = self.filterset.qs.count()
        context['ordem'] = self.request.GET.get('ordem', 'desc')
        return context


class CanhotoDetailView(DetailView):
    """
    Detail view for a single canhoto with file preview and manual link form.
    """
    model = Canhoto
    template_name = 'canhotos/detalhe.html'
    context_object_name = 'canhoto'

    def get_queryset(self):
        return Canhoto.objects.select_related('nota')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vincular_form'] = VincularManualForm()
        context['corrigir_form'] = CorrigirNumeroForm(initial={
            'numero_detectado': self.object.numero_detectado,
        })
        return context


@method_decorator(xframe_options_sameorigin, name='get')
class ServirArquivoCanhotoView(View):
    """
    Serve o arquivo físico do canhoto independente de onde ele esteja no disco.
    Necessário porque os arquivos podem estar em pastas do scanner fora do MEDIA_ROOT.

    O decorator xframe_options_sameorigin sobrescreve o X-Frame-Options: DENY
    global apenas neste endpoint, permitindo que o <iframe> de pré-visualização
    (mesma origem) renderize o PDF.
    """
    http_method_names = ['get']

    def get(self, request, pk):
        from django.conf import settings
        from pathlib import Path

        canhoto = get_object_or_404(Canhoto, pk=pk)
        if not canhoto.arquivo:
            raise Http404('Arquivo não associado a este canhoto.')

        # Resolve o caminho absoluto
        caminho = Path(str(canhoto.arquivo.name))
        if not caminho.is_absolute():
            caminho = Path(settings.MEDIA_ROOT) / caminho

        if not caminho.exists():
            raise Http404(f'Arquivo não encontrado em disco: {caminho}')

        content_type, _ = mimetypes.guess_type(str(caminho))
        content_type = content_type or 'application/octet-stream'

        response = FileResponse(
            open(caminho, 'rb'),
            content_type=content_type,
            as_attachment=False,
        )
        # Força exibição inline no browser (não download)
        response['Content-Disposition'] = f'inline; filename="{caminho.name}"'
        return response


class ReprocessarOCRView(View):
    """
    POST-only view that enqueues a Celery task to re-run OCR on an existing canhoto.
    The canhoto file path must already be stored in canhoto.arquivo.
    """
    http_method_names = ['post']

    def post(self, request, pk):
        canhoto = get_object_or_404(Canhoto, pk=pk)
        from tasks.ocr_tasks import reprocessar_canhoto
        try:
            # Roteado para a fila 'prioridade' para furar a fila de processamento
            # automático (notas/canhotos) — ação manual do usuário deve ser rápida.
            reprocessar_canhoto.apply_async(args=[canhoto.id], queue='prioridade')
            canhoto.status_processamento = StatusProcessamento.PENDENTE
            canhoto.erro_mensagem = ''
            canhoto.save(update_fields=['status_processamento', 'erro_mensagem', 'updated_at'])
            messages.success(request, f'Canhoto {canhoto.id} enviado para reprocessamento OCR.')
            logger.info('Reprocessamento solicitado: canhoto_id=%s', canhoto.id)
        except Exception as exc:
            messages.error(request, f'Erro ao enfileirar reprocessamento: {exc}')
            logger.exception('Erro ao enfileirar reprocessamento para canhoto %s', pk)
        return redirect(reverse('canhotos:detalhe', kwargs={'pk': pk}))


class VincularManualView(View):
    """
    POST-only view that manually links a canhoto to a specific nota fiscal.
    Uses ConciliacaoService.vincular_manual() to ensure consistent status updates.
    """
    http_method_names = ['post']

    def post(self, request, pk):
        canhoto = get_object_or_404(Canhoto, pk=pk)
        form = VincularManualForm(request.POST)
        if form.is_valid():
            nota = form.cleaned_data['nota']
            from services.conciliacao_service import ConciliacaoService
            try:
                service = ConciliacaoService()
                resultado = service.vincular_manual(canhoto.id, nota.id)
                messages.success(
                    request,
                    f'Canhoto {canhoto.id} vinculado manualmente à Nota Fiscal {nota.numero}.',
                )
                logger.info(
                    'Vínculo manual criado: canhoto_id=%s nota_id=%s nota_numero=%s',
                    canhoto.id, nota.id, nota.numero,
                )
            except Exception as exc:
                messages.error(request, f'Erro ao vincular: {exc}')
                logger.exception('Erro ao vincular manualmente canhoto %s a nota %s', pk, nota.id)
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f'{field}: {err}')
        return redirect(reverse('canhotos:detalhe', kwargs={'pk': pk}))


class ExcluirCanhotoView(View):
    """
    POST-only view that deletes a canhoto record and its physical file.
    If the canhoto is linked to a nota, the nota's status is reverted to
    AGUARDANDO_CANHOTO so it can be matched again later.
    """
    http_method_names = ['post']

    def post(self, request, pk):
        canhoto = get_object_or_404(Canhoto, pk=pk)
        canhoto_id = canhoto.id

        nota = canhoto.nota
        if nota is not None:
            from apps.notas.models import StatusNota
            nota.status = StatusNota.AGUARDANDO_CANHOTO
            nota.save(update_fields=['status', 'updated_at'])

        if canhoto.arquivo:
            try:
                from django.conf import settings
                from pathlib import Path
                caminho = Path(str(canhoto.arquivo.name))
                if not caminho.is_absolute():
                    caminho = Path(settings.MEDIA_ROOT) / caminho
                if caminho.exists():
                    caminho.unlink()
            except Exception as exc:
                logger.warning('Falha ao remover arquivo físico do canhoto %s: %s', canhoto_id, exc)

        canhoto.delete()
        messages.success(request, f'Canhoto {canhoto_id} excluído com sucesso.')
        logger.info('Canhoto excluído: canhoto_id=%s', canhoto_id)
        return redirect(reverse('canhotos:lista'))


class AtribuirNotasDivisoriaView(View):
    """
    POST-only view for folha-divisória canhotos: attributes one or more
    Notas Fiscais (by número) to this single canhoto record, since a divider
    sheet legitimately covers many notas at once.
    """
    http_method_names = ['post']

    def post(self, request, pk):
        canhoto = get_object_or_404(Canhoto, pk=pk)
        numeros = request.POST.getlist('numeros')
        # Campo de texto livre: números adicionais separados por vírgula.
        numeros_texto = request.POST.get('numeros_texto', '')
        numeros += [n.strip() for n in numeros_texto.split(',') if n.strip()]
        # Remove duplicados preservando ordem
        numeros = list(dict.fromkeys(numeros))
        if not numeros:
            messages.warning(request, 'Selecione ou digite ao menos um número para atribuir a este canhoto.')
            return redirect(reverse('canhotos:detalhe', kwargs={'pk': pk}))

        from services.conciliacao_service import ConciliacaoService
        try:
            service = ConciliacaoService()
            resultado = service.vincular_divisoria(canhoto.id, numeros)
            if resultado['vinculadas']:
                messages.success(
                    request,
                    f"Notas Fiscais atribuídas a este canhoto: {', '.join(resultado['vinculadas'])}.",
                )
            if resultado['nao_encontradas']:
                messages.warning(
                    request,
                    f"Nenhuma Nota Fiscal encontrada para: {', '.join(resultado['nao_encontradas'])}.",
                )
            if resultado['ja_finalizadas']:
                messages.warning(
                    request,
                    f"Já finalizadas por outro canhoto (ignoradas): {', '.join(resultado['ja_finalizadas'])}.",
                )
            logger.info('Notas atribuídas a divisória: canhoto_id=%s numeros=%s', canhoto.id, numeros)
        except Exception as exc:
            messages.error(request, f'Erro ao atribuir notas: {exc}')
            logger.exception('Erro ao atribuir notas à divisória %s', pk)
        return redirect(reverse('canhotos:detalhe', kwargs={'pk': pk}))


class CorrigirNumeroView(View):
    """
    POST-only view that lets an operator manually validate/correct the
    numero_detectado of a canhoto (typically one with MEDIA/BAIXA confidence
    or no detection at all). Marks confianca_deteccao as ALTA since a human
    confirmed it. Does not auto-link to a nota — use VincularManualView for that.
    """
    http_method_names = ['post']

    def post(self, request, pk):
        canhoto = get_object_or_404(Canhoto, pk=pk)
        form = CorrigirNumeroForm(request.POST)
        if form.is_valid():
            numeros = form.numeros_list
            if len(numeros) > 1:
                # Vários números → trata o canhoto como divisória que atende
                # múltiplas notas. Popula numeros_lista para liberar a checklist
                # de atribuição "Quais notas esses canhotos atendem?".
                from apps.canhotos.models import TipoPagina
                canhoto.tipo_pagina = TipoPagina.DIVISORIA
                canhoto.numeros_lista = ', '.join(numeros)
                canhoto.numero_detectado = ''
                canhoto.confianca_deteccao = 'ALTA'
                canhoto.status_processamento = StatusProcessamento.REVISAO
                canhoto.erro_mensagem = ''
                canhoto.save(update_fields=[
                    'tipo_pagina', 'numeros_lista', 'numero_detectado',
                    'confianca_deteccao', 'status_processamento', 'erro_mensagem', 'updated_at',
                ])
                messages.success(
                    request,
                    f'Canhoto {canhoto.id} marcado como divisória com {len(numeros)} números. '
                    'Selecione abaixo quais notas ele atende.',
                )
                logger.info('Canhoto %s definido como divisória manual: %s', canhoto.id, numeros)
            else:
                numero = numeros[0]
                canhoto.numero_detectado = numero
                canhoto.confianca_deteccao = 'ALTA'
                canhoto.save(update_fields=['numero_detectado', 'confianca_deteccao', 'updated_at'])
                messages.success(
                    request,
                    f'Número do canhoto {canhoto.id} corrigido manualmente para {numero}.',
                )
                logger.info('Número corrigido manualmente: canhoto_id=%s numero=%s', canhoto.id, numero)
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f'{field}: {err}')
        return redirect(reverse('canhotos:detalhe', kwargs={'pk': pk}))
