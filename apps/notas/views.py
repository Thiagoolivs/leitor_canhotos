"""
Views for Notas Fiscais.

Uses class-based views throughout.
Business logic is delegated to NotaService in services/nota_service.py.
Filtering is handled by django-filter's NotaFiscalFilterSet.
"""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from datetime import timedelta
from django.db.models import Case, CharField, Count, F, Func, IntegerField, Value, When
from django.db.models.functions import Cast, TruncMonth
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
        # numero é normalizado para dígitos puros por formatar_numero_nota(), mas
        # notas criadas manualmente via formulário podem conter texto; protege
        # a ordenação numérica removendo não-dígitos antes do cast.
        numero_limpo = Func(
            F('numero'), Value(r'\D'), Value(''), Value('g'),
            function='regexp_replace', output_field=CharField(),
        )
        queryset = NotaFiscal.objects.annotate(
            numero_limpo=numero_limpo,
        ).annotate(
            numero_int=Case(
                When(numero_limpo='', then=Value(None)),
                default=Cast('numero_limpo', IntegerField()),
                output_field=IntegerField(),
            ),
        ).select_related()
        self.filterset = NotaFiscalFilterSet(self.request.GET, queryset=queryset)
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


class BuscarNotaAPIView(View):
    """
    JSON search endpoint used by the manual-link search box on the canhoto
    detail page. Searches NotaFiscal by partial numero match (icontains).
    """

    def get(self, request):
        termo = request.GET.get('q', '').strip()
        if len(termo) < 2:
            return JsonResponse({'resultados': []})

        notas = NotaFiscal.objects.filter(numero__icontains=termo).order_by('-created_at')[:10]
        resultados = [
            {
                'id': nota.id,
                'numero': nota.numero,
                'status': nota.status,
                'destinatario': nota.destinatario,
                'vinculada': hasattr(nota, 'canhoto') and nota.canhoto is not None,
            }
            for nota in notas
        ]
        return JsonResponse({'resultados': resultados})


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


class DashboardView(LoginRequiredMixin, View):
    """Main dashboard with KPI cards, charts, alerts and activity feed."""
    login_url = '/admin/login/'

    def get(self, request):
        return render(request, 'dashboard.html')


class DashboardAPIView(View):
    """JSON API endpoint for dashboard data — used by Chart.js polling."""

    def get(self, request):
        from apps.notas.models import NotaFiscal, StatusNota
        from apps.canhotos.models import Canhoto

        now = timezone.now()
        hoje = now.date()
        um_mes_atras = hoje - timedelta(days=30)
        tres_meses_atras = hoje - timedelta(days=90)
        mes_atual_inicio = hoje.replace(day=1)
        mes_anterior_inicio = (mes_atual_inicio - timedelta(days=1)).replace(day=1)

        # KPI counts
        total = NotaFiscal.objects.count()
        aguardando = NotaFiscal.objects.filter(status=StatusNota.AGUARDANDO_CANHOTO).count()
        finalizado = NotaFiscal.objects.filter(status=StatusNota.FINALIZADO).count()
        erro = NotaFiscal.objects.filter(status=StatusNota.ERRO).count()
        canhotos_sem_nota = Canhoto.objects.filter(nota__isnull=True).count()

        # Distribuição de confiança de detecção dos canhotos
        canhotos_alta = Canhoto.objects.filter(confianca_deteccao='ALTA').count()
        canhotos_media = Canhoto.objects.filter(confianca_deteccao='MEDIA').count()
        canhotos_baixa = Canhoto.objects.filter(confianca_deteccao='BAIXA').count()

        # Alertas
        aguardando_mais_1_mes = NotaFiscal.objects.filter(
            status=StatusNota.AGUARDANDO_CANHOTO,
            created_at__date__lte=um_mes_atras,
        ).count()

        sem_correspondencia_3_meses = NotaFiscal.objects.filter(
            status=StatusNota.AGUARDANDO_CANHOTO,
            created_at__date__lte=tres_meses_atras,
        ).count()

        # Tendencia: finalizadas este mes vs mes anterior
        finalizadas_mes_atual = NotaFiscal.objects.filter(
            status=StatusNota.FINALIZADO,
            updated_at__date__gte=mes_atual_inicio,
        ).count()
        finalizadas_mes_anterior = NotaFiscal.objects.filter(
            status=StatusNota.FINALIZADO,
            updated_at__date__gte=mes_anterior_inicio,
            updated_at__date__lt=mes_atual_inicio,
        ).count()
        if finalizadas_mes_anterior > 0:
            tendencia = round(((finalizadas_mes_atual - finalizadas_mes_anterior) / finalizadas_mes_anterior) * 100)
        else:
            tendencia = 0

        # Notas por mes (ultimos 6 meses) for bar chart
        seis_meses_atras = hoje - timedelta(days=180)
        notas_por_mes = (
            NotaFiscal.objects
            .filter(created_at__date__gte=seis_meses_atras)
            .annotate(mes=TruncMonth('created_at'))
            .values('mes')
            .annotate(total=Count('id'))
            .order_by('mes')
        )
        meses_labels = []
        meses_data = []
        meses_map = {
            1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
            7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
        }
        for item in notas_por_mes:
            meses_labels.append(f"{meses_map[item['mes'].month]}/{str(item['mes'].year)[2:]}")
            meses_data.append(item['total'])

        # Ultimas 10 atividades
        ultimas_notas = NotaFiscal.objects.order_by('-updated_at')[:10]
        atividades = []
        for nota in ultimas_notas:
            atividades.append({
                'numero': nota.numero,
                'status': nota.status,
                'updated_at': nota.updated_at.strftime('%d/%m/%Y %H:%M'),
            })

        # Alertas detalhados (top 5 mais antigas aguardando > 1 mes)
        alertas_notas = NotaFiscal.objects.filter(
            status=StatusNota.AGUARDANDO_CANHOTO,
            created_at__date__lte=um_mes_atras,
        ).order_by('created_at')[:5]
        alertas = []
        for nota in alertas_notas:
            dias = (hoje - nota.created_at.date()).days
            alertas.append({
                'numero': nota.numero,
                'dias': dias,
                'critico': dias >= 90,
                'created_at': nota.created_at.strftime('%d/%m/%Y'),
            })

        return JsonResponse({
            'kpis': {
                'total': total,
                'aguardando': aguardando,
                'finalizado': finalizado,
                'erro': erro,
                'aguardando_mais_1_mes': aguardando_mais_1_mes,
                'sem_correspondencia_3_meses': sem_correspondencia_3_meses,
                'canhotos_sem_nota': canhotos_sem_nota,
                'canhotos_alta': canhotos_alta,
                'canhotos_media': canhotos_media,
                'canhotos_baixa': canhotos_baixa,
                'tendencia': tendencia,
            },
            'chart_pizza': {
                'labels': ['Aguardando', 'Finalizado', 'Erro'],
                'data': [aguardando, finalizado, erro],
                'colors': ['#ffc107', '#198754', '#dc3545'],
            },
            'chart_barras': {
                'labels': meses_labels,
                'data': meses_data,
            },
            'atividades': atividades,
            'alertas': alertas,
        })
