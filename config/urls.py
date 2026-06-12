"""
URL configuration for leitor_canhotos project.

Architecture:
- Notas Fiscais CRUD: /notas/
- Canhotos management: /canhotos/
- Django admin: /admin/
- Media files served by Django in development (use nginx in production)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('notas/', include('apps.notas.urls', namespace='notas')),
    path('canhotos/', include('apps.canhotos.urls', namespace='canhotos')),
    # Redirect root to dashboard
    path('', RedirectView.as_view(url='/notas/dashboard/', permanent=False), name='home'),
]

# Serve media files through Django in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Admin site customization
admin.site.site_header = 'Leitor de Canhotos'
admin.site.site_title = 'Leitor de Canhotos Admin'
admin.site.index_title = 'Gerenciamento do Sistema'
