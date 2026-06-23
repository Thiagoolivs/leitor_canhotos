"""
Comando: revisar_com_ia

Pega todos os canhotos em REVISAO e envia o texto OCR para a IA (Groq)
tentar extrair o número da nota fiscal. Se a IA encontrar com confiança,
tenta vincular automaticamente.

Uso:
    # Ver quantos seriam revisados, sem alterar nada
    python manage.py revisar_com_ia --dry-run

    # Rodar a revisão de verdade
    python manage.py revisar_com_ia

    # Limitar a N canhotos (para testar)
    python manage.py revisar_com_ia --limite 10
"""
import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.canhotos.models import Canhoto, StatusProcessamento, TipoPagina


class Command(BaseCommand):
    help = (
        'Envia canhotos em REVISAO para a IA (Groq) tentar extrair o número '
        'da NF e vincular automaticamente.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Apenas lista os canhotos, sem chamar a IA.',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Limita a N canhotos (0 = todos).',
        )
        parser.add_argument(
            '--diagnostico',
            action='store_true',
            default=False,
            help='Mostra o texto OCR e a resposta da IA para cada canhoto.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limite = options['limite']
        diagnostico = options['diagnostico']

        from services.ai_service import AIService
        ai = AIService()

        if not ai.habilitado:
            self.stdout.write(self.style.ERROR(
                'IA desabilitada. Configure GROQ_API_KEY no .env.'
            ))
            return

        candidatos = (
            Canhoto.objects
            .filter(status_processamento=StatusProcessamento.REVISAO)
            .exclude(texto_ocr='')
            .exclude(tipo_pagina__in=[TipoPagina.DIVISORIA, TipoPagina.DIVISORIA_MISTA])
        )

        total = candidatos.count()
        self.stdout.write(f'{total} canhoto(s) em REVISAO com texto OCR.')

        if limite > 0:
            candidatos = candidatos[:limite]
            self.stdout.write(f'Limitado a {limite}.')

        if dry_run:
            for c in candidatos:
                self.stdout.write(
                    f'  [dry-run] id={c.id} numero_atual={c.numero_detectado or "—"} '
                    f'confianca={c.confianca_deteccao or "—"} '
                    f'texto={len(c.texto_ocr)} chars'
                )
            self.stdout.write(self.style.WARNING('Use sem --dry-run para rodar a IA.'))
            return

        from repositories.canhoto_repository import CanhotoRepository
        from services.conciliacao_service import ConciliacaoService

        repo = CanhotoRepository()
        conciliacao = ConciliacaoService()

        resolvidos = 0
        falhas_api = 0
        sem_numero = 0
        vinculacao_falhou = 0
        total_processados = 0

        for canhoto in candidatos:
            total_processados += 1
            self.stdout.write(
                f'[{total_processados}/{total}] Canhoto {canhoto.id} '
                f'(numero_atual={canhoto.numero_detectado or "—"})...',
                ending=' ',
            )

            if diagnostico:
                self.stdout.write('')
                self.stdout.write(f'  TEXTO OCR ({len(canhoto.texto_ocr)} chars):')
                self.stdout.write(f'  {canhoto.texto_ocr[:300]}')
                self.stdout.write(f'  ---')

            resultado = ai.analisar_texto_ocr(canhoto.texto_ocr, canhoto.numero_detectado or '')

            if diagnostico and resultado:
                self.stdout.write(f'  RESPOSTA IA: {resultado}')

            if not resultado or not resultado.get('numero'):
                self.stdout.write(self.style.WARNING('IA não encontrou número.'))
                sem_numero += 1
                continue

            numero_ia = resultado['numero']
            confianca_ia = resultado.get('confianca', 'MEDIA')
            motivo = resultado.get('motivo', '')

            if confianca_ia == 'BAIXA':
                self.stdout.write(self.style.WARNING(
                    f'IA retornou BAIXA: {numero_ia} ({motivo})'
                ))
                sem_numero += 1
                continue

            self.stdout.write(
                f'IA encontrou NF={numero_ia} [{confianca_ia}] ({motivo})',
                ending=' → ',
            )

            repo.atualizar(
                canhoto,
                numero_detectado=numero_ia,
                confianca_deteccao='MEDIA',
            )

            try:
                conciliacao.conciliar(canhoto.id, numero_ia)
                resolvidos += 1
                self.stdout.write(self.style.SUCCESS('VINCULADO!'))
            except Exception as exc:
                vinculacao_falhou += 1
                repo.atualizar(
                    canhoto,
                    status_processamento=StatusProcessamento.REVISAO,
                    erro_mensagem=f'IA encontrou NF={numero_ia}, mas vinculação falhou: {exc}',
                )
                self.stdout.write(self.style.ERROR(f'Falha: {exc}'))

            time.sleep(0.5)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'=== RESULTADO ==='))
        self.stdout.write(f'  Total processados: {total_processados}')
        self.stdout.write(self.style.SUCCESS(f'  Resolvidos (vinculados): {resolvidos}'))
        self.stdout.write(f'  IA não encontrou número: {sem_numero}')
        self.stdout.write(f'  Vinculação falhou (nota não existe): {vinculacao_falhou}')
        self.stdout.write(f'  Erros de API: {falhas_api}')
