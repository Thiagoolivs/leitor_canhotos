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
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import ListView, DetailView

from apps.canhotos.forms import CanhotoFilterSet, VincularManualForm
from apps.canhotos.models import Canhoto, StatusProcessamento

logger = logging.getLogger(__name__)


class CanhotoListView(ListView):
    """
    Paginated list of all canhotos with status and filtering support.
    """
    model = Canhoto
    template_name = 'canhotos/lista.html'
    context_object_name = 'canhotos'
    paginate_by = 20

    def get_queryset(self):
        queryset = Canhoto.objects.all().select_related('nota')
        self.filterset = CanhotoFilterSet(self.request.GET, queryset=queryset)
        return self.filterset.qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filterset'] = self.filterset
        context['total_count'] = self.filterset.qs.count()
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
        return context


class ServirArquivoCanhotoView(View):
    """
    Serve o arquivo físico do canhoto independente de onde ele esteja no disco.
    Necessário porque os arquivos podem estar em pastas do scanner fora do MEDIA_ROOT.
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
            reprocessar_canhoto.delay(canhoto.id)
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
