"""
Comando: corrigir_revisao_indevida

Move canhotos que foram indevidamente marcados como REVISAO de volta para ERRO.
Afeta apenas canhotos cujo erro indica que a nota não foi encontrada no sistema
ou que OCR/IA não detectaram número — esses não são revisão manual.

Uso:
    python manage.py corrigir_revisao_indevida --dry-run
    python manage.py corrigir_revisao_indevida
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.canhotos.models import Canhoto, StatusProcessamento


class Command(BaseCommand):
    help = 'Move canhotos indevidamente em REVISAO de volta para ERRO.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False)

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        indevidos = Canhoto.objects.filter(
            status_processamento=StatusProcessamento.REVISAO,
        ).filter(
            Q(erro_mensagem__icontains='não encontrada no sistema')
            | Q(erro_mensagem__icontains='não conseguiram detectar')
        )

        total = indevidos.count()
        self.stdout.write(f'{total} canhoto(s) em REVISAO indevidamente.')

        if dry_run:
            for c in indevidos[:20]:
                self.stdout.write(f'  id={c.id} erro="{c.erro_mensagem[:80]}"')
            self.stdout.write(self.style.WARNING('Use sem --dry-run para corrigir.'))
            return

        atualizado = indevidos.update(status_processamento=StatusProcessamento.ERRO)
        self.stdout.write(self.style.SUCCESS(f'{atualizado} canhoto(s) movidos de REVISAO → ERRO.'))
