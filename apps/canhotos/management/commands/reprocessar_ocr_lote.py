"""
Comando: reprocessar_ocr_lote

Reenfileira para reprocessamento OCR os canhotos já existentes que mais se
beneficiam do pré-processamento de imagem adicionado em ocr_service.py
(confiança BAIXA/MEDIA, sem número detectado, ou status ERRO/REVISAO) — sem
tocar nos que já foram lidos com sucesso e ALTA confiança.

Uso:
    # Lista quem seria reprocessado, sem enfileirar nada
    python manage.py reprocessar_ocr_lote --dry-run

    # Enfileira de verdade (fila 'prioridade', mesma usada pelo botão manual)
    python manage.py reprocessar_ocr_lote
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.canhotos.models import Canhoto, StatusProcessamento


class Command(BaseCommand):
    help = (
        'Reenfileira para reprocessamento OCR os canhotos com baixa/média confiança, '
        'sem número detectado, ou em ERRO/REVISAO — para se beneficiarem do novo '
        'pré-processamento de imagem sem reprocessar à toa quem já está correto.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Apenas lista os canhotos que seriam reprocessados, sem enfileirar.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        candidatos = Canhoto.objects.filter(
            Q(confianca_deteccao__in=['BAIXA', 'MEDIA'])
            | Q(numero_detectado='')
            | Q(status_processamento__in=[StatusProcessamento.ERRO, StatusProcessamento.REVISAO]),
        ).exclude(arquivo='')

        total = candidatos.count()
        self.stdout.write(self.style.HTTP_INFO(
            f'{total} canhoto(s) elegível(eis) para reprocessamento.'
        ))

        if dry_run:
            for canhoto in candidatos:
                self.stdout.write(
                    f'  [dry-run] canhoto {canhoto.id} '
                    f'(confiança={canhoto.confianca_deteccao or "—"}, '
                    f'status={canhoto.status_processamento}, '
                    f'numero={canhoto.numero_detectado or "—"})'
                )
            self.stdout.write(self.style.WARNING('Use sem --dry-run para enfileirar de verdade.'))
            return

        from tasks.ocr_tasks import reprocessar_canhoto

        total_enfileirados = 0
        for canhoto in candidatos:
            try:
                reprocessar_canhoto.apply_async(args=[canhoto.id], queue='prioridade')
                canhoto.status_processamento = StatusProcessamento.PENDENTE
                canhoto.erro_mensagem = ''
                canhoto.save(update_fields=['status_processamento', 'erro_mensagem', 'updated_at'])
                total_enfileirados += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  ✗ canhoto {canhoto.id} → erro: {exc}'))

        self.stdout.write(self.style.SUCCESS(
            f'Concluído: {total_enfileirados} canhoto(s) enfileirado(s) para reprocessamento.'
        ))
