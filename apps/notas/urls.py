"""
URL patterns for Notas Fiscais.

Provides full CRUD routes under /notas/ namespace.
"""
from django.urls import path

from apps.notas import views

app_name = 'notas'

urlpatterns = [
    path('', views.NotaFiscalListView.as_view(), name='lista'),
    path('nova/', views.NotaFiscalCreateView.as_view(), name='criar'),
    path('<int:pk>/', views.NotaFiscalDetailView.as_view(), name='detalhe'),
    path('<int:pk>/editar/', views.NotaFiscalUpdateView.as_view(), name='editar'),
]
