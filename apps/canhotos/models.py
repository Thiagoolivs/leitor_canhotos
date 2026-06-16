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
    REVISAO = 'REVISAO', 'Revisão Manual'


class TipoPagina(models.TextChoices):
    CANHOTO = 'CANHOTO', 'Canhoto'
    DIVISORIA = 'DIVISORIA', 'Folha Divisória'
    DIVISORIA_MISTA = 'DIVISORIA_MISTA', 'Divisória com Canhotos'


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
    tipo_pagina = models.CharField(
        max_length=20,
        choices=TipoPagina.choices,
        default=TipoPagina.CANHOTO,
        verbose_name='Tipo de Página',
    )
    numeros_lista = models.TextField(
        blank=True,
        verbose_name='Números detectados na divisória',
        help_text='Lista de números sequenciais detectados em uma folha divisória.',
    )
    notas_atendidas = models.ManyToManyField(
        'notas.NotaFiscal',
        blank=True,
        related_name='canhotos_divisoria',
        verbose_name='Notas Fiscais Atendidas (Divisória)',
        help_text='Notas Fiscais cobertas por esta folha divisória, atribuídas manualmente.',
    )
    pagina_numero = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Página (PDF original)')
    numero_barcode = models.CharField(max_length=50, blank=True, verbose_name='Número via Código de Barras')
    confianca_deteccao = models.CharField(
        max_length=5, blank=True,
        choices=[('ALTA', 'Alta'), ('MEDIA', 'Média'), ('BAIXA', 'Baixa')],
        verbose_name='Confiança da Detecção',
    )
    data_recebimento = models.DateField(null=True, blank=True, verbose_name='Data de Recebimento')
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
    def is_divisoria(self):
        return self.tipo_pagina in (TipoPagina.DIVISORIA, TipoPagina.DIVISORIA_MISTA)

    @property
    def numeros_lista_items(self):
        """Retorna os números da divisória como lista de strings."""
        if not self.numeros_lista:
            return []
        return [n.strip() for n in self.numeros_lista.split(',') if n.strip()]

    @property
    def is_pdf(self):
        if self.arquivo:
            return self.arquivo.name.lower().endswith('.pdf')
        return False
