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
    nota = forms.ModelChoiceField(
        queryset=NotaFiscal.objects.filter(status=StatusNota.AGUARDANDO_CANHOTO),
        label='Nota Fiscal',
        empty_label='Selecione uma Nota Fiscal...',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Apenas notas com status "Aguardando Canhoto" são exibidas.',
    )

    def clean_nota(self):
        nota = self.cleaned_data.get('nota')
        if nota is None:
            raise forms.ValidationError('Selecione uma nota fiscal válida.')
        # Check if nota already has a canhoto linked
        if hasattr(nota, 'canhoto') and nota.canhoto is not None:
            raise forms.ValidationError(
                f'A nota {nota.numero} já possui um canhoto vinculado (ID: {nota.canhoto.id}).'
            )
        return nota


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

    def filtrar_vinculo(self, queryset, name, value):
        if value == 'sim':
            return queryset.filter(nota__isnull=True)
        if value == 'nao':
            return queryset.filter(nota__isnull=False)
        return queryset

    class Meta:
        model = Canhoto
        fields = ['numero_detectado', 'status_processamento', 'sem_vinculo']
