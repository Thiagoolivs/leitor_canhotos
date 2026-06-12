"""
Views for Notas Fiscais.

Uses class-based views throughout.
Business logic is delegated to NotaService in services/nota_service.py.
Filtering is handled by django-filter's NotaFiscalFilterSet.
"""
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View

from apps.notas.forms import NotaFiscalFilterSet, NotaFiscalForm
from apps.notas.models import NotaFiscal

logger = logging.getLogger(__name__)


class NotaFiscalListView(ListView):
    """
    Displays paginated list of Notas Fiscais with filtering support.
    Supports filtering by numero, data_emissao, categoria, status via GET params.
    """
    model = NotaFiscal
    template_name = 'notas/lista.html'
    context_object_name = 'notas'
    paginate_by = 20

    def get_queryset(self):
        queryset = NotaFiscal.objects.all().select_related()
        self.filterset = NotaFiscalFilterSet(self.request.GET, queryset=queryset)
        return self.filterset.qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filterset'] = self.filterset
        context['total_count'] = self.filterset.qs.count()
        return context


class NotaFiscalDetailView(DetailView):
    """
    Shows details of a single Nota Fiscal, including linked canhoto (if any).
    """
    model = NotaFiscal
    template_name = 'notas/detalhe.html'
    context_object_name = 'nota'

    def get_queryset(self):
        return NotaFiscal.objects.select_related('canhoto')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        nota = self.object
        context['canhoto'] = getattr(nota, 'canhoto', None)
        return context


class NotaFiscalCreateView(CreateView):
    """
    Form to create a new Nota Fiscal manually.
    Bulk import is handled via the service layer (importar_lote).
    """
    model = NotaFiscal
    form_class = NotaFiscalForm
    template_name = 'notas/form.html'
    success_url = reverse_lazy('notas:lista')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Nota Fiscal {self.object.numero} criada com sucesso.')
        logger.info('NotaFiscal criada: numero=%s', self.object.numero)
        return response

    def form_invalid(self, form):
        messages.error(self.request, 'Erro ao criar Nota Fiscal. Verifique os dados.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Nova Nota Fiscal'
        context['botao'] = 'Criar Nota'
        return context


class NotaFiscalUpdateView(UpdateView):
    """
    Form to edit an existing Nota Fiscal.
    """
    model = NotaFiscal
    form_class = NotaFiscalForm
    template_name = 'notas/form.html'

    def get_success_url(self):
        return reverse_lazy('notas:detalhe', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Nota Fiscal {self.object.numero} atualizada com sucesso.')
        logger.info('NotaFiscal atualizada: id=%s numero=%s', self.object.id, self.object.numero)
        return response

    def form_invalid(self, form):
        messages.error(self.request, 'Erro ao atualizar Nota Fiscal. Verifique os dados.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = f'Editar Nota Fiscal {self.object.numero}'
        context['botao'] = 'Salvar Alterações'
        return context


class StatusCountsView(View):
    """Returns current NotaFiscal status counts as JSON for frontend polling."""

    def get(self, request):
        from apps.notas.models import NotaFiscal, StatusNota
        counts = {
            'aguardando': NotaFiscal.objects.filter(status=StatusNota.AGUARDANDO_CANHOTO).count(),
            'finalizado': NotaFiscal.objects.filter(status=StatusNota.FINALIZADO).count(),
            'erro': NotaFiscal.objects.filter(status=StatusNota.ERRO).count(),
            'total': NotaFiscal.objects.count(),
        }
        return JsonResponse(counts)
