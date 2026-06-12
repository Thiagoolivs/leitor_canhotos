"""
Admin configuration for Notas Fiscais.

Provides full-featured admin panel with:
- List display with status badges
- Filters, search, date hierarchy
- Custom actions: reprocessar OCR, marcar como erro
- Read-only timestamp fields
"""
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages

from apps.notas.models import NotaFiscal, StatusNota


def _status_badge_html(status):
    colors = {
        StatusNota.AGUARDANDO_CANHOTO: ('#ffc107', '#000'),
        StatusNota.FINALIZADO: ('#198754', '#fff'),
        StatusNota.ERRO: ('#dc3545', '#fff'),
    }
    bg, fg = colors.get(status, ('#6c757d', '#fff'))
    label = dict(StatusNota.choices).get(status, status)
    return format_html(
        '<span style="background:{};color:{};padding:3px 8px;border-radius:4px;font-size:12px;">{}</span>',
        bg, fg, label,
    )


@admin.register(NotaFiscal)
class NotaFiscalAdmin(admin.ModelAdmin):
    list_display = ('numero', 'data_emissao', 'categoria', 'status_badge', 'canhoto_vinculado', 'created_at')
    list_filter = ('status', 'categoria', 'data_emissao')
    search_fields = ('numero', 'categoria')
    date_hierarchy = 'data_emissao'
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 50
    ordering = ('-created_at',)

    fieldsets = (
        ('Dados da Nota', {
            'fields': ('numero', 'data_emissao', 'categoria', 'status'),
        }),
        ('Auditoria', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['acao_aguardar_canhoto', 'acao_marcar_erro', 'acao_finalizar']

    @admin.display(description='Status')
    def status_badge(self, obj):
        return _status_badge_html(obj.status)

    @admin.display(description='Canhoto Vinculado', boolean=True)
    def canhoto_vinculado(self, obj):
        return hasattr(obj, 'canhoto') and obj.canhoto is not None

    @admin.action(description='Marcar como Aguardando Canhoto')
    def acao_aguardar_canhoto(self, request, queryset):
        updated = queryset.update(status=StatusNota.AGUARDANDO_CANHOTO)
        self.message_user(request, f'{updated} nota(s) marcada(s) como Aguardando Canhoto.', messages.SUCCESS)

    @admin.action(description='Marcar como Erro')
    def acao_marcar_erro(self, request, queryset):
        updated = queryset.update(status=StatusNota.ERRO)
        self.message_user(request, f'{updated} nota(s) marcada(s) como Erro.', messages.WARNING)

    @admin.action(description='Marcar como Finalizado')
    def acao_finalizar(self, request, queryset):
        updated = queryset.update(status=StatusNota.FINALIZADO)
        self.message_user(request, f'{updated} nota(s) marcada(s) como Finalizado.', messages.SUCCESS)
