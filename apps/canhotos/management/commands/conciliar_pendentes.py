"""
Comando: conciliar_pendentes

Drena as filas de REVISAO e ERRO usando a validação cruzada com a base de
notas: todo canhoto com numero_detectado que bate exatamente com uma
NotaFiscal AGUARDANDO_CANHOTO (sem canhoto vinculado) é conciliado
automaticamente — a mesma verificação que o operador faria manualmente.

Não usa IA nem OCR: é instantâneo e sem custo de API.

Uso:
    # Ver o que seria conciliado, sem alterar nada
    python manage.py conciliar_pendentes --dry-run

    # Rodar de verdade
    python manage.py conciliar_pendentes

    # Incluir também canhotos em PENDENTE
    python manage.py conciliar_pendentes --incluir-pendentes
"""
from django.core.management.base import BaseCommand

from apps.canhotos.models import Canhoto, StatusProcessamento, TipoPagina
from apps.notas.models import NotaFiscal, StatusNota


class Command(BaseCommand):
    help = (
        'Concilia canhotos presos em REVISAO/ERRO cujo número detectado bate '
        'com uma nota fiscal pendente na base.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='Apenas lista o que seria conciliado, sem alterar nada.',
        )
        parser.add_argument(
            '--incluir-pendentes', action='store_true', default=False,
            help='Inclui também canhotos com status PENDENTE.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        status_alvo = [StatusProcessamento.REVISAO, StatusProcessamento.ERRO]
        if options['incluir_pendentes']:
            status_alvo.append(StatusProcessamento.PENDENTE)

        candidatos = (
            Canhoto.objects
            .filter(status_processamento__in=status_alvo, nota__isnull=True)
            .exclude(numero_detectado='')
            .exclude(tipo_pagina__in=[TipoPagina.DIVISORIA, TipoPagina.DIVISORIA_MISTA])
            .order_by('created_at')
        )

        total = candidatos.count()
        self.stdout.write(f'{total} canhoto(s) em fila com número detectado.')

        from services.conciliacao_service import ConciliacaoService
        conciliacao = ConciliacaoService()

        conciliados = 0
        sem_nota = 0
        nota_ocupada = 0
        falhas = 0

        for canhoto in candidatos:
            nota = NotaFiscal.objects.filter(
                numero=canhoto.numero_detectado,
                status=StatusNota.AGUARDANDO_CANHOTO,
                canhoto__isnull=True,
            ).first()

            if nota is None:
                if NotaFiscal.objects.filter(numero=canhoto.numero_detectado).exists():
                    nota_ocupada += 1
                else:
                    sem_nota += 1
                continue

            if dry_run:
                conciliados += 1
                self.stdout.write(
                    f'  [dry-run] canhoto #{canhoto.pk} '
                    f'({canhoto.get_status_processamento_display()}) → NF {nota.numero}'
                )
                continue

            try:
                conciliacao.conciliar(canhoto.pk, nota.numero)
                conciliados += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  canhoto #{canhoto.pk} → NF {nota.numero} VINCULADO'
                ))
            except Exception as exc:
                falhas += 1
                self.stdout.write(self.style.ERROR(
                    f'  canhoto #{canhoto.pk} → NF {nota.numero} falhou: {exc}'
                ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=== RESULTADO ==='))
        acao = 'seriam conciliados' if dry_run else 'conciliados'
        self.stdout.write(self.style.SUCCESS(f'  {conciliados} canhoto(s) {acao}'))
        self.stdout.write(f'  {sem_nota} sem nota correspondente na base (aguardam cadastro da nota)')
        self.stdout.write(f'  {nota_ocupada} com nota já finalizada/vinculada a outro canhoto (possível duplicado)')
        if falhas:
            self.stdout.write(self.style.ERROR(f'  {falhas} falha(s)'))
        if dry_run:
            self.stdout.write(self.style.WARNING('Rode sem --dry-run para aplicar.'))
