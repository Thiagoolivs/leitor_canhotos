"""
URL patterns for Canhotos.

Provides list, detail, reprocess OCR, and manual link routes under /canhotos/ namespace.
"""
from django.urls import path

from apps.canhotos import views

app_name = 'canhotos'

urlpatterns = [
    path('', views.CanhotoListView.as_view(), name='lista'),
    path('revisao/', views.RevisaoListView.as_view(), name='revisao'),
    path('erros/', views.ErroListView.as_view(), name='erros'),
    path('processando/', views.ProcessandoListView.as_view(), name='processando'),
    path('<int:pk>/', views.CanhotoDetailView.as_view(), name='detalhe'),
    path('<int:pk>/arquivo/', views.ServirArquivoCanhotoView.as_view(), name='arquivo'),
    path('<int:pk>/reprocessar/', views.ReprocessarOCRView.as_view(), name='reprocessar'),
    path('<int:pk>/vincular/', views.VincularManualView.as_view(), name='vincular'),
    path('<int:pk>/corrigir/', views.CorrigirNumeroView.as_view(), name='corrigir'),
    path('<int:pk>/excluir/', views.ExcluirCanhotoView.as_view(), name='excluir'),
    path('<int:pk>/atribuir-notas/', views.AtribuirNotasDivisoriaView.as_view(), name='atribuir_notas'),
]
