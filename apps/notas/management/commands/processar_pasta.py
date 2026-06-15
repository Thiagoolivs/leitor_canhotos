"""
Comando: processar_pasta

Varre uma pasta (ou as pastas configuradas) e enfileira no Celery todos os
arquivos que ainda não foram processados.

Uso:
    # Processa a pasta de notas configurada no .env (SCANNER_NOTA_DIRS)
    python manage.py processar_pasta --tipo nota

    # Processa a pasta de canhotos configurada no .env (SCANNER_CANHOTO_DIRS)
    python manage.py processar_pasta --tipo canhoto

    # Processa uma pasta específica como notas
    python manage.py processar_pasta --tipo nota --pasta "M:/Nota_Fiscal/NF"

    # Processa uma pasta específica como canhotos
    python manage.py processar_pasta --tipo canhoto --pasta "M:/Fatura/scaner_fat"

    # Modo dry-run: lista os arquivos sem enfileirar
    python manage.py processar_pasta --tipo nota --dry-run
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


EXTENSOES_SUPORTADAS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}


class Command(BaseCommand):
    help = 'Enfileira no Celery todos os arquivos de uma pasta de scanner para processamento OCR.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tipo',
            choices=['nota', 'canhoto'],
            required=True,
            help='Tipo de arquivo: "nota" (NF) ou "canhoto".',
        )
        parser.add_argument(
            '--pasta',
            type=str,
            default=None,
            help='Pasta a varrer. Se omitido, usa SCANNER_NOTA_DIRS / SCANNER_CANHOTO_DIRS do .env.',
        )
        parser.add_argument(
            '--ultimos',
            type=int,
            default=None,
            metavar='N',
            help='Processa apenas os N arquivos mais recentes (por data de modificação).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Apenas lista os arquivos sem enfileirar tarefas.',
        )

    def handle(self, *args, **options):
        tipo = options['tipo']
        dry_run = options['dry_run']
        pasta_arg = options['pasta']

        # Determina as pastas a varrer
        if pasta_arg:
            pastas = [Path(pasta_arg)]
        elif tipo == 'nota':
            pastas = [Path(p) for p in getattr(settings, 'SCANNER_NOTA_DIRS', [])]
        else:
            pastas = [Path(p) for p in getattr(settings, 'SCANNER_CANHOTO_DIRS', [])]

        if not pastas:
            self.stderr.write(self.style.ERROR(
                f'Nenhuma pasta configurada para tipo "{tipo}". '
                f'Defina SCANNER_{"NOTA" if tipo == "nota" else "CANHOTO"}_DIRS no .env '
                f'ou use --pasta.'
            ))
            return

        from tasks.ocr_tasks import processar_arquivo

        ultimos = options['ultimos']
        total_enfileirados = 0
        total_ignorados = 0

        for pasta in pastas:
            if not pasta.exists():
                self.stdout.write(self.style.WARNING(f'Pasta não encontrada, pulando: {pasta}'))
                continue

            # Ordena por data de modificação (mais recentes primeiro)
            arquivos = sorted(
                [f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in EXTENSOES_SUPORTADAS],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            if ultimos:
                arquivos = arquivos[:ultimos]
                # Inverte para processar em ordem cronológica (mais antigo → mais novo)
                arquivos = list(reversed(arquivos))

            descricao = f'{len(arquivos)} arquivo(s)' + (f' (últimos {ultimos})' if ultimos else '')
            self.stdout.write(self.style.HTTP_INFO(f'\n📂 {pasta} — {descricao}'))

            for arquivo in arquivos:
                if dry_run:
                    self.stdout.write(f'  [dry-run] {arquivo.name}')
                    total_enfileirados += 1
                else:
                    try:
                        fila = 'notas' if tipo == 'nota' else 'canhotos'
                        task = processar_arquivo.apply_async(
                            args=[str(arquivo), tipo], queue=fila
                        )
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ {arquivo.name} → task {task.id}')
                        )
                        total_enfileirados += 1
                    except Exception as exc:
                        self.stdout.write(
                            self.style.ERROR(f'  ✗ {arquivo.name} → erro: {exc}')
                        )
                        total_ignorados += 1

        prefixo = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write('\n' + self.style.SUCCESS(
            f'{prefixo}Concluído: {total_enfileirados} enfileirado(s), {total_ignorados} erro(s).'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING(
                'Use sem --dry-run para enfileirar de verdade.'
            ))
