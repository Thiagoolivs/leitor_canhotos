"""
Models for Notas Fiscais (Invoice stubs).

Architecture:
- Models only define data structure and simple property methods.
- Business logic lives in services/nota_service.py.
- Database access is abstracted in repositories/nota_repository.py.
"""
from django.db import models


class StatusNota(models.TextChoices):
    AGUARDANDO_CANHOTO = 'AGUARDANDO_CANHOTO', 'Aguardando Canhoto'
    FINALIZADO = 'FINALIZADO', 'Finalizado'
    ERRO = 'ERRO', 'Erro'


class NotaFiscal(models.Model):
    numero = models.CharField(max_length=50, unique=True, verbose_name='Número')
    data_emissao = models.DateField(null=True, blank=True, verbose_name='Data de Emissão')
    destinatario = models.CharField(max_length=200, blank=True, verbose_name='Destinatário')
    valor_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, verbose_name='Valor Total (R$)')
    categoria = models.CharField(max_length=100, blank=True, verbose_name='Categoria')
    status = models.CharField(
        max_length=30,
        choices=StatusNota.choices,
        default=StatusNota.AGUARDANDO_CANHOTO,
        verbose_name='Status',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Nota Fiscal'
        verbose_name_plural = 'Notas Fiscais'

    def __str__(self):
        return f'NF {self.numero}'

    @property
    def esta_finalizada(self):
        return self.status == StatusNota.FINALIZADO

    @property
    def aguardando_canhoto(self):
        return self.status == StatusNota.AGUARDANDO_CANHOTO
