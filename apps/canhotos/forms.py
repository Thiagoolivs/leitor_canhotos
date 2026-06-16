"""
Forms for Canhotos.

Includes:
- VincularManualForm: form to manually link a canhoto to a nota fiscal.
- CanhotoFilterSet: django-filter FilterSet for list view filtering.
"""
import django_filters
from django import forms

from apps.canhotos.models import Canhoto, StatusProcessamento
from apps.notas.models import NotaFiscal, StatusNota


class VincularManualForm(forms.Form):
    """
    Vínculo manual via busca numérica: o operador digita o número da NF em um
    campo de texto com autocomplete (JS), que preenche nota_id ao selecionar
    um resultado. Não usa dropdown/lista pois o volume de notas é grande.
    """
    nota_id = forms.IntegerField(
        label='Nota Fiscal',
        widget=forms.HiddenInput(),
        error_messages={'required': 'Pesquise e selecione uma Nota Fiscal antes de vincular.'},
    )

    def clean_nota_id(self):
        nota_id = self.cleaned_data.get('nota_id')
        try:
            nota = NotaFiscal.objects.get(pk=nota_id)
        except NotaFiscal.DoesNotExist:
            raise forms.ValidationError('Nota fiscal não encontrada.')
        if hasattr(nota, 'canhoto') and nota.canhoto is not None:
            raise forms.ValidationError(
                f'A nota {nota.numero} já possui um canhoto vinculado (ID: {nota.canhoto.id}).'
            )
        self.cleaned_data['nota'] = nota
        return nota_id


class CorrigirNumeroForm(forms.Form):
    """
    Form para validar/corrigir manualmente o(s) número(s) de um canhoto.

    Aceita um único número (vínculo normal) ou vários separados por vírgula
    (transforma o canhoto numa divisória que atende várias notas).
    """
    numero_detectado = forms.CharField(
        label='Número(s) Correto(s)',
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm flex-grow-1',
            'placeholder': 'Ex.: 12345  ou  12345, 12346, 12347',
        }),
    )

    def clean_numero_detectado(self):
        numero = self.cleaned_data.get('numero_detectado', '').strip()
        if not numero:
            raise forms.ValidationError('Informe um número válido.')
        return numero

    @property
    def numeros_list(self):
        """Lista de números individuais (separados por vírgula), já limpos."""
        bruto = self.cleaned_data.get('numero_detectado', '')
        return [n.strip() for n in bruto.split(',') if n.strip()]


SEM_VINCULO_CHOICES = [
    ('', 'Todos'),
    ('sim', 'Sem nota vinculada'),
    ('nao', 'Com nota vinculada'),
]


class CanhotoFilterSet(django_filters.FilterSet):
    numero_detectado = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Número Detectado',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buscar número...'}),
    )
    status_processamento = django_filters.ChoiceFilter(
        choices=[('', 'Todos')] + list(StatusProcessamento.choices),
        label='Status',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None,
    )
    sem_vinculo = django_filters.ChoiceFilter(
        choices=SEM_VINCULO_CHOICES,
        label='Vínculo',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None,
        method='filtrar_vinculo',
    )
    confianca_deteccao = django_filters.ChoiceFilter(
        choices=[('', 'Todas')] + [('ALTA', 'Alta'), ('MEDIA', 'Média'), ('BAIXA', 'Baixa')],
        label='Confiança',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None,
    )

    def filtrar_vinculo(self, queryset, name, value):
        if value == 'sim':
            return queryset.filter(nota__isnull=True)
        if value == 'nao':
            return queryset.filter(nota__isnull=False)
        return queryset

    class Meta:
        model = Canhoto
        fields = ['numero_detectado', 'status_processamento', 'sem_vinculo', 'confianca_deteccao']
