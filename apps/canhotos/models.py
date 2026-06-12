"""
Models for Canhotos (scanned invoice return stubs).

Architecture:
- Models only define data structure.
- Business logic lives in services/canhoto_service.py and services/conciliacao_service.py.
- Database access is abstracted in repositories/canhoto_repository.py.
"""
from django.db import models


class StatusProcessamento(models.TextChoices):
    PENDENTE = 'PENDENTE', 'Pendente'
    PROCESSANDO = 'PROCESSANDO', 'Processando'
    SUCESSO = 'SUCESSO', 'Sucesso'
    ERRO = 'ERRO', 'Erro'


class Canhoto(models.Model):
    arquivo = models.FileField(upload_to='canhotos/', verbose_name='Arquivo')
    numero_detectado = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Número Detectado pelo OCR',
    )
    status_processamento = models.CharField(
        max_length=20,
        choices=StatusProcessamento.choices,
        default=StatusProcessamento.PENDENTE,
        verbose_name='Status de Processamento',
    )
    nota = models.OneToOneField(
        'notas.NotaFiscal',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='canhoto',
        verbose_name='Nota Fiscal Vinculada',
    )
    texto_ocr = models.TextField(blank=True, verbose_name='Texto Extraído pelo OCR')
    erro_mensagem = models.TextField(blank=True, verbose_name='Mensagem de Erro')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Canhoto'
        verbose_name_plural = 'Canhotos'

    def __str__(self):
        return f'Canhoto {self.id} - NF {self.numero_detectado or "N/A"}'

    @property
    def esta_vinculado(self):
        return self.nota_id is not None

    @property
    def nome_arquivo(self):
        if self.arquivo:
            return self.arquivo.name.split('/')[-1]
        return ''

    @property
    def is_pdf(self):
        if self.arquivo:
            return self.arquivo.name.lower().endswith('.pdf')
        return False
