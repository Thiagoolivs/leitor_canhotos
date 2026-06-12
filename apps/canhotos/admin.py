"""
Admin configuration for Canhotos.

Provides:
- List display with processing status
- Inline preview link for the uploaded file
- Custom action to re-trigger OCR via Celery
- Filters and search
"""
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages

from apps.canhotos.models import Canhoto, StatusProcessamento


def _status_badge_html(status):
    colors = {
        StatusProcessamento.PENDENTE: ('#6c757d', '#fff'),
        StatusProcessamento.PROCESSANDO: ('#0d6efd', '#fff'),
        StatusProcessamento.SUCESSO: ('#198754', '#fff'),
        StatusProcessamento.ERRO: ('#dc3545', '#fff'),
    }
    bg, fg = colors.get(status, ('#6c757d', '#fff'))
    label = dict(StatusProcessamento.choices).get(status, status)
    return format_html(
        '<span style="background:{};color:{};padding:3px 8px;border-radius:4px;font-size:12px;">{}</span>',
        bg, fg, label,
    )


@admin.register(Canhoto)
class CanhotoAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'nome_arquivo_display', 'numero_detectado', 'status_badge',
        'nota_vinculada', 'created_at',
    )
    list_filter = ('status_processamento',)
    search_fields = ('numero_detectado', 'nota__numero', 'arquivo')
    readonly_fields = ('created_at', 'updated_at', 'arquivo_preview', 'erro_mensagem')
    list_per_page = 50
    ordering = ('-created_at',)
    raw_id_fields = ('nota',)

    fieldsets = (
        ('Arquivo', {
            'fields': ('arquivo', 'arquivo_preview'),
        }),
        ('OCR', {
            'fields': ('numero_detectado', 'status_processamento', 'erro_mensagem'),
        }),
        ('Vinculação', {
            'fields': ('nota',),
        }),
        ('Auditoria', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['acao_reprocessar_ocr', 'acao_marcar_pendente']

    @admin.display(description='Arquivo')
    def nome_arquivo_display(self, obj):
        if obj.arquivo:
            nome = obj.arquivo.name.split('/')[-1]
            return format_html('<a href="{}" target="_blank">{}</a>', obj.arquivo.url, nome)
        return '-'

    @admin.display(description='Status')
    def status_badge(self, obj):
        return _status_badge_html(obj.status_processamento)

    @admin.display(description='Nota Fiscal')
    def nota_vinculada(self, obj):
        if obj.nota:
            return format_html(
                '<a href="/admin/notas/notafiscal/{}/change/">{}</a>',
                obj.nota.id,
                obj.nota.numero,
            )
        return '-'

    @admin.display(description='Pré-visualização')
    def arquivo_preview(self, obj):
        if not obj.arquivo:
            return '-'
        url = obj.arquivo.url
        nome = obj.arquivo.name.lower()
        if nome.endswith('.pdf'):
            return format_html(
                '<iframe src="{}" width="600" height="400" style="border:1px solid #ccc;"></iframe>',
                url,
            )
        elif nome.endswith(('.png', '.jpg', '.jpeg', '.tiff', '.tif')):
            return format_html(
                '<img src="{}" style="max-width:600px;max-height:400px;border:1px solid #ccc;" />',
                url,
            )
        return format_html('<a href="{}" target="_blank">Abrir arquivo</a>', url)

    @admin.action(description='Reprocessar OCR via Celery')
    def acao_reprocessar_ocr(self, request, queryset):
        from tasks.ocr_tasks import reprocessar_canhoto
        count = 0
        for canhoto in queryset:
            reprocessar_canhoto.delay(canhoto.id)
            count += 1
        self.message_user(
            request,
            f'{count} canhoto(s) enviado(s) para reprocessamento OCR.',
            messages.SUCCESS,
        )

    @admin.action(description='Marcar como Pendente')
    def acao_marcar_pendente(self, request, queryset):
        updated = queryset.update(
            status_processamento=StatusProcessamento.PENDENTE,
            erro_mensagem='',
        )
        self.message_user(request, f'{updated} canhoto(s) marcado(s) como Pendente.', messages.SUCCESS)
