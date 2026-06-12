"""
Forms for Notas Fiscais.

Includes:
- NotaFiscalForm: ModelForm for creating/editing notas.
- NotaFiscalFilterSet: django-filter FilterSet for list view filtering.
"""
import django_filters
from django import forms

from apps.notas.models import NotaFiscal, StatusNota


class NotaFiscalForm(forms.ModelForm):
    class Meta:
        model = NotaFiscal
        fields = ('numero', 'data_emissao', 'categoria', 'status')
        widgets = {
            'numero': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 001234',
            }),
            'data_emissao': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'categoria': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Materiais, Serviços...',
            }),
            'status': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def clean_numero(self):
        numero = self.cleaned_data.get('numero', '').strip()
        if not numero:
            raise forms.ValidationError('O número da nota é obrigatório.')
        # Normalize: remove leading zeros for storage, but keep original if not purely numeric
        if numero.isdigit():
            numero = str(int(numero))
        return numero


class NotaFiscalFilterSet(django_filters.FilterSet):
    numero = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Número',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buscar número...'}),
    )
    data_emissao__gte = django_filters.DateFilter(
        field_name='data_emissao',
        lookup_expr='gte',
        label='Data Emissão (de)',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    data_emissao__lte = django_filters.DateFilter(
        field_name='data_emissao',
        lookup_expr='lte',
        label='Data Emissão (até)',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    categoria = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Categoria',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Filtrar categoria...'}),
    )
    status = django_filters.ChoiceFilter(
        choices=[('', 'Todos')] + list(StatusNota.choices),
        label='Status',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label=None,
    )

    class Meta:
        model = NotaFiscal
        fields = ['numero', 'data_emissao__gte', 'data_emissao__lte', 'categoria', 'status']
