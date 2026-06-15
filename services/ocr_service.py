"""
OCR Service para extração de texto e dados de PDFs e imagens.

Estratégia em cascata:
1. PDFs digitais (DANFE gerado pelo ERP): pdfplumber extrai texto direto — sem OCR,
   sem Poppler, sem conversão para imagem. Resultado em < 1 segundo.
2. PDFs escaneados (canhotos físicos): se pdfplumber não retornar texto suficiente,
   pdf2image + Tesseract fazem OCR na imagem de cada página.
3. Imagens (PNG, JPG, etc.): Tesseract diretamente.

Divisão de PDFs multi-página:
- dividir_pdf_em_paginas(): usa pypdf para separar cada página em um PDF individual.
  Usado para canhotos onde cada página = um canhoto diferente.
"""
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex para campos do DANFE
# ---------------------------------------------------------------------------
# Usamos DOTALL+limite de chars para cobrir layouts onde cabeçalho e valor
# ficam em linhas diferentes (padrão de tabela do DANFE).
_RE_DATA_EMISSAO = re.compile(
    r'DATA\s+DE\s+EMISS[AÃ]O.{0,300}?(\d{2}/\d{2}/\d{4})',
    re.IGNORECASE | re.DOTALL,
)
_RE_DATA_RECEBIMENTO = re.compile(
    r'DATA\s+DE\s+RECEBIMENTO.{0,300}?(\d{2}/\d{2}/\d{2,4})',
    re.IGNORECASE | re.DOTALL,
)
# No DANFE o OCR/pdfplumber lê "NOME / RAZÃO SOCIAL  CNPJ / CPF  DATA DE EMISSÃO"
# em uma linha, e o nome real do destinatário aparece na linha seguinte.
_RE_DESTINATARIO = re.compile(
    r'NOME\s*/?\s*RAZ[AÃ]O\s+SOCIAL[^\n]*(?:CNPJ|CPF)[^\n]*\n\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][^\n]{5,120})',
    re.IGNORECASE,
)
_RE_VALOR_TOTAL = re.compile(
    r'VALOR\s+TOTAL\s+(?:DA\s+)?NOTA\s+FISCAL.{0,300}?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
    re.IGNORECASE | re.DOTALL,
)
_RE_VALOR_TOTAL_FALLBACK = re.compile(
    r'VALOR\s+TOTAL.{0,200}?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
    re.IGNORECASE | re.DOTALL,
)

# Mínimo de caracteres para considerar que pdfplumber extraiu texto útil do PDF
_MIN_CHARS_PDF_DIGITAL = 100


class OCRService:
    """
    Extrai texto e dados de NF de PDFs e imagens.

    Para PDFs, tenta primeiro extração digital (pdfplumber) e usa OCR como fallback.
    """

    TESSERACT_CONFIG = '--oem 3 --psm 6 -l por+eng'

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.patterns = getattr(
            settings,
            'NOTA_NUMBER_PATTERNS',
            [
                r'NOTA\s+FISCAL\s+(?:ELETR[OÔ]NICA\s+)?N[Oo°\.º]?\s*:?\s*(\d{1,9})',
                r'N[Oo°\.º]\s+NOTA\s+FISCAL\s*:?\s*(\d{1,9})',
                r'N[Oo°\.º\.]\s*:?\s*(\d{1,9})',
                r'NF[-\s]*[Ee]?\s*:?\s*(\d{1,9})',
                r'(?:^|\s)(\d{6,9})(?:\s|$)',
            ],
        )

    # ------------------------------------------------------------------
    # Extração de texto
    # ------------------------------------------------------------------

    def extrair_texto_pdf_digital(self, caminho_pdf: str) -> str:
        """
        Extrai texto de PDF digital (gerado por ERP) usando pdfplumber.
        Retorna string vazia se o PDF for escaneado (sem texto embutido).
        """
        try:
            import pdfplumber
        except ImportError:
            self.logger.warning('pdfplumber não instalado, pulando extração digital.')
            return ''

        textos = []
        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    texto = page.extract_text() or ''
                    textos.append(f'\n--- PÁGINA {i} ---\n{texto}')
                    self.logger.debug('pdfplumber página %d: %d chars', i, len(texto))
        except Exception as exc:
            self.logger.warning('pdfplumber falhou em %s: %s', caminho_pdf, exc)
            return ''

        return '\n'.join(textos)

    def extrair_texto_pdf(self, caminho_pdf: str) -> str:
        """
        Extrai texto de PDF: tenta pdfplumber primeiro (digital), OCR como fallback (scan).
        """
        # 1ª tentativa: extração digital (instantânea, sem Poppler/Tesseract)
        texto_digital = self.extrair_texto_pdf_digital(caminho_pdf)
        chars_uteis = len(texto_digital.replace('\n', '').replace(' ', '').replace('-', ''))
        if chars_uteis >= _MIN_CHARS_PDF_DIGITAL:
            self.logger.info(
                'PDF digital: texto extraído via pdfplumber (%d chars) em %s',
                len(texto_digital), Path(caminho_pdf).name,
            )
            return texto_digital

        # 2ª tentativa: OCR (para PDFs de scan físico)
        self.logger.info(
            'PDF escaneado (pdfplumber retornou %d chars), usando OCR: %s',
            chars_uteis, Path(caminho_pdf).name,
        )
        return self._extrair_texto_pdf_ocr(caminho_pdf)

    def _extrair_texto_pdf_ocr(self, caminho_pdf: str) -> str:
        """Converte PDF em imagens e roda Tesseract em cada página."""
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
        import pytesseract
        from core.exceptions import OCRException

        try:
            self.logger.info('Convertendo PDF para imagens: %s', caminho_pdf)
            poppler_path = getattr(settings, 'POPPLER_PATH', None)
            self.logger.info('POPPLER_PATH configurado: %r', poppler_path)
            convert_kwargs = dict(dpi=300, fmt='png', thread_count=1)
            if poppler_path:
                convert_kwargs['poppler_path'] = poppler_path
            imagens = convert_from_path(caminho_pdf, **convert_kwargs)
        except (PDFInfoNotInstalledError, PDFPageCountError, Exception) as exc:
            self.logger.error(
                'Erro ao converter PDF. POPPLER_PATH=%r.',
                getattr(settings, 'POPPLER_PATH', None),
            )
            raise OCRException(
                f'Falha ao converter PDF para imagem: {exc}',
                caminho_arquivo=caminho_pdf,
            ) from exc

        if not imagens:
            raise OCRException('Nenhuma página no PDF.', caminho_arquivo=caminho_pdf)

        textos = []
        for i, imagem in enumerate(imagens, start=1):
            try:
                texto_pagina = pytesseract.image_to_string(imagem, config=self.TESSERACT_CONFIG)
                textos.append(f'\n--- PÁGINA {i} ---\n{texto_pagina}')
                self.logger.debug('OCR página %d: %d chars extraídos', i, len(texto_pagina))
            except Exception as exc:
                self.logger.warning('Erro OCR página %d: %s', i, exc)
                textos.append(f'\n--- PÁGINA {i} (ERRO OCR) ---\n')

        return '\n'.join(textos)

    def extrair_texto_imagem(self, caminho_imagem: str) -> str:
        """OCR direto em arquivo de imagem (PNG, JPG, TIFF, etc.)."""
        import pytesseract
        from PIL import Image
        from core.exceptions import OCRException

        try:
            self.logger.info('OCR em imagem: %s', caminho_imagem)
            imagem = Image.open(caminho_imagem)
            texto = pytesseract.image_to_string(imagem, config=self.TESSERACT_CONFIG)
            self.logger.debug('OCR imagem: %d chars extraídos', len(texto))
            return texto
        except Exception as exc:
            raise OCRException(
                f'Falha no OCR da imagem: {exc}',
                caminho_arquivo=caminho_imagem,
            ) from exc

    # ------------------------------------------------------------------
    # Divisão de PDF multi-página (para canhotos)
    # ------------------------------------------------------------------

    @staticmethod
    def contar_paginas_pdf(caminho_pdf: str) -> int:
        """Retorna o número de páginas do PDF sem converter para imagem."""
        try:
            from pypdf import PdfReader
            return len(PdfReader(caminho_pdf).pages)
        except Exception as exc:
            logger.warning('Não foi possível contar páginas de %s: %s', caminho_pdf, exc)
            return 1

    @staticmethod
    def dividir_pdf_em_paginas(caminho_pdf: str, destino_dir: str) -> list:
        """
        Separa um PDF multi-página em arquivos de página única.

        Args:
            caminho_pdf: caminho absoluto do PDF original.
            destino_dir: diretório onde os arquivos de página serão salvos.

        Returns:
            Lista de caminhos absolutos dos PDFs individuais criados.
        """
        from pypdf import PdfReader, PdfWriter

        destino = Path(destino_dir)
        destino.mkdir(parents=True, exist_ok=True)

        stem = Path(caminho_pdf).stem
        reader = PdfReader(caminho_pdf)
        arquivos = []

        for i, page in enumerate(reader.pages, 1):
            writer = PdfWriter()
            writer.add_page(page)
            nome = f'{stem}_p{i:03d}.pdf'
            caminho_pagina = destino / nome
            with open(str(caminho_pagina), 'wb') as f:
                writer.write(f)
            arquivos.append(str(caminho_pagina))
            logger.debug('Página %d salva: %s', i, caminho_pagina.name)

        logger.info('PDF dividido em %d páginas: %s', len(arquivos), Path(caminho_pdf).name)
        return arquivos

    # ------------------------------------------------------------------
    # Leitura de código de barras / QR code
    # ------------------------------------------------------------------

    def _ler_barcode_imagem(self, imagem) -> Optional[str]:
        """
        Tenta ler o código de barras Code128 ou QR do DANFE numa imagem PIL.

        A chave de acesso da NF-e tem 44 dígitos. O número da NF ocupa as
        posições 25-33 (índice 0). Retorna None se pyzbar não estiver instalado
        ou nenhum código válido for encontrado.
        """
        try:
            from pyzbar.pyzbar import decode
        except ImportError:
            self.logger.debug('pyzbar não instalado — leitura de código de barras desativada.')
            return None

        try:
            decoded = decode(imagem)
            for d in decoded:
                data = d.data.decode('utf-8', errors='ignore').strip()
                # Chave de acesso NF-e: 44 dígitos numéricos
                if data.isdigit() and len(data) == 44:
                    numero_raw = data[25:34]  # posições 25-33 = nNF (9 dígitos)
                    numero = str(int(numero_raw)) if numero_raw.isdigit() else None
                    if numero:
                        self.logger.info(
                            'Código de barras lido: NF=%s (chave=%s...%s)',
                            numero, data[:6], data[-6:],
                        )
                        return numero
        except Exception as exc:
            self.logger.warning('Erro ao ler código de barras: %s', exc)
        return None

    def _obter_imagens_pagina(self, caminho: str) -> list:
        """Converte arquivo (PDF ou imagem) em lista de PIL Images."""
        ext = Path(caminho).suffix.lower()
        if ext == '.pdf':
            from pdf2image import convert_from_path
            poppler_path = getattr(settings, 'POPPLER_PATH', None)
            kwargs = dict(dpi=300, fmt='png', thread_count=1)
            if poppler_path:
                kwargs['poppler_path'] = poppler_path
            return list(convert_from_path(caminho, **kwargs))
        else:
            from PIL import Image
            return [Image.open(caminho)]

    # ------------------------------------------------------------------
    # Extração de múltiplos candidatos (redundância)
    # ------------------------------------------------------------------

    def extrair_todos_candidatos_nota(self, texto: str) -> list:
        """
        Retorna todos os candidatos a número de NF encontrados no texto,
        classificados por confiança (ALTA = padrão específico, BAIXA = número isolado).

        Cada item: {'numero': str, 'raw': str, 'confianca': str}
        """
        if not texto:
            return []

        texto_upper = texto.upper()
        candidatos = []
        vistos: set = set()

        # Confiança por índice de padrão (do mais ao menos específico)
        confiancas = ['ALTA', 'ALTA', 'MEDIA', 'MEDIA', 'BAIXA']

        for i, pattern in enumerate(self.patterns):
            conf = confiancas[i] if i < len(confiancas) else 'BAIXA'
            try:
                for raw in re.findall(pattern, texto_upper, re.MULTILINE | re.IGNORECASE):
                    raw = raw.strip()
                    numero = str(int(raw)) if raw.isdigit() else raw
                    if numero and numero not in vistos:
                        vistos.add(numero)
                        candidatos.append({'numero': numero, 'raw': raw, 'confianca': conf})
            except re.error:
                pass

        return candidatos

    def processar_pagina_canhoto(self, caminho: str) -> dict:
        """
        Processamento especializado para páginas de canhoto (PDF ou imagem).

        Converte para imagem UMA vez e roda em paralelo:
        - OCR (Tesseract) → todos os candidatos de NF
        - Barcode (pyzbar) → NF direto da chave de acesso de 44 dígitos

        Lógica de confiança:
        - Barcode + OCR concordam → ALTA
        - Dois padrões OCR distintos concordam → ALTA
        - Apenas barcode → MEDIA
        - Apenas OCR (1 padrão) → confiança do padrão
        - Nenhum → BAIXA
        """
        import pytesseract
        from core.exceptions import OCRException

        _vazio = {
            'texto': '', 'numero_nota': None, 'numero_barcode': None,
            'candidatos_ocr': [], 'confianca': 'BAIXA',
            'data_recebimento': None,
            'data_emissao': None, 'destinatario': '', 'valor_total': None,
        }

        try:
            imagens = self._obter_imagens_pagina(caminho)
        except Exception as exc:
            raise OCRException(f'Falha ao converter para imagem: {exc}', caminho_arquivo=caminho) from exc

        if not imagens:
            raise OCRException('Arquivo sem páginas.', caminho_arquivo=caminho)

        imagem = imagens[0]  # canhoto = página única

        # OCR
        try:
            texto = pytesseract.image_to_string(imagem, config=self.TESSERACT_CONFIG)
            self.logger.debug('OCR canhoto: %d chars', len(texto))
        except Exception as exc:
            texto = ''
            self.logger.warning('OCR falhou na página: %s', exc)

        # Barcode (na mesma imagem, sem recusar)
        numero_barcode = self._ler_barcode_imagem(imagem)

        # Candidatos OCR
        candidatos_ocr = self.extrair_todos_candidatos_nota(texto)
        numero_ocr = candidatos_ocr[0]['numero'] if candidatos_ocr else None

        # Reconciliação com redundância
        if numero_barcode and numero_ocr:
            if numero_barcode == numero_ocr:
                numero_final, confianca = numero_barcode, 'ALTA'
                self.logger.info('Barcode + OCR concordam: NF=%s [ALTA]', numero_final)
            else:
                numero_final, confianca = numero_barcode, 'MEDIA'
                self.logger.warning(
                    'Barcode e OCR divergem — barcode=%s ocr=%s — usando barcode [MEDIA]',
                    numero_barcode, numero_ocr,
                )
        elif numero_barcode:
            numero_final, confianca = numero_barcode, 'MEDIA'
            self.logger.info('Apenas barcode: NF=%s [MEDIA]', numero_final)
        elif numero_ocr:
            # Verifica se o mesmo número aparece em mais de um padrão (redundância OCR)
            ocorrencias_mesmo = sum(1 for c in candidatos_ocr if c['numero'] == numero_ocr)
            if ocorrencias_mesmo >= 2:
                confianca = 'ALTA'
                self.logger.info('OCR redundante (2+ padrões): NF=%s [ALTA]', numero_ocr)
            else:
                confianca = candidatos_ocr[0]['confianca']
                self.logger.info('Apenas OCR: NF=%s [%s]', numero_ocr, confianca)
            numero_final = numero_ocr
        else:
            numero_final, confianca = None, 'BAIXA'
            self.logger.warning('Nenhum número de NF detectado em %s', Path(caminho).name)

        self.logger.info(
            'Canhoto: %s | nf=%s | barcode=%s | confianca=%s | candidatos=%s',
            Path(caminho).name, numero_final, numero_barcode,
            confianca, [c['numero'] for c in candidatos_ocr],
        )

        return {
            **_vazio,
            'texto': texto,
            'numero_nota': numero_final,
            'numero_barcode': numero_barcode or '',
            'candidatos_ocr': candidatos_ocr,
            'confianca': confianca,
            'data_recebimento': self.extrair_data_recebimento(texto),
            'sucesso': True,
            'erro': None,
        }

    # ------------------------------------------------------------------
    # Extração de campos estruturados
    # ------------------------------------------------------------------

    def extrair_numero_nota(self, texto: str) -> Optional[str]:
        """Busca o número da NF no texto usando os padrões configurados."""
        if not texto:
            return None
        texto_upper = texto.upper()
        for pattern in self.patterns:
            try:
                matches = re.findall(pattern, texto_upper, re.MULTILINE | re.IGNORECASE)
                if matches:
                    numero_raw = matches[0].strip()
                    numero = str(int(numero_raw)) if numero_raw.isdigit() else numero_raw
                    self.logger.debug(
                        'Número encontrado com padrão "%s": %s (raw: %s)',
                        pattern, numero, numero_raw,
                    )
                    return numero
            except re.error as exc:
                self.logger.warning('Padrão regex inválido "%s": %s', pattern, exc)
        self.logger.info('Nenhum número de nota encontrado no texto.')
        return None

    def extrair_data_emissao(self, texto: str) -> Optional[date]:
        """Extrai data de emissão do texto DANFE."""
        m = _RE_DATA_EMISSAO.search(texto)
        return self._parse_date_br(m.group(1)) if m else None

    def extrair_data_recebimento(self, texto: str) -> Optional[date]:
        """Extrai data de recebimento do texto do canhoto."""
        m = _RE_DATA_RECEBIMENTO.search(texto)
        return self._parse_date_br(m.group(1)) if m else None

    def extrair_destinatario(self, texto: str) -> str:
        """Extrai nome do destinatário do DANFE."""
        m = _RE_DESTINATARIO.search(texto)
        if not m:
            return ''
        linha = m.group(1).strip()
        # Remove CNPJ e data que ficam na mesma linha após o nome
        linha = re.sub(r'\s+\d{2}\.\d{3}\.\d{3}.*$', '', linha).strip()
        return linha[:200] if linha else ''

    def extrair_valor_total(self, texto: str) -> Optional['Decimal']:
        """Extrai valor total da NF."""
        from decimal import Decimal, InvalidOperation
        for pattern in (_RE_VALOR_TOTAL, _RE_VALOR_TOTAL_FALLBACK):
            m = pattern.search(texto)
            if m:
                raw = m.group(1).strip()
                try:
                    return Decimal(raw.replace('.', '').replace(',', '.'))
                except InvalidOperation:
                    continue
        return None

    @staticmethod
    def _parse_date_br(texto_data: str) -> Optional[date]:
        """Converte DD/MM/YYYY ou DD/MM/YY em objeto date."""
        from datetime import datetime
        for fmt in ('%d/%m/%Y', '%d/%m/%y'):
            try:
                return datetime.strptime(texto_data.strip(), fmt).date()
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Ponto de entrada principal
    # ------------------------------------------------------------------

    def processar_arquivo(self, caminho_arquivo: str) -> dict:
        """
        Extrai texto e campos estruturados de um arquivo PDF ou imagem.

        Returns:
            dict com: texto, numero_nota, data_emissao, data_recebimento,
                      destinatario, valor_total, sucesso, erro.
        """
        from core.exceptions import OCRException

        caminho = Path(caminho_arquivo)
        _vazio = {
            'texto': '', 'numero_nota': None,
            'data_emissao': None, 'data_recebimento': None,
            'destinatario': '', 'valor_total': None,
        }

        if not caminho.exists():
            return {**_vazio, 'sucesso': False, 'erro': f'Arquivo não encontrado: {caminho_arquivo}'}

        extensao = caminho.suffix.lower()

        try:
            if extensao == '.pdf':
                texto = self.extrair_texto_pdf(str(caminho))
            elif extensao in {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}:
                texto = self.extrair_texto_imagem(str(caminho))
            else:
                return {**_vazio, 'sucesso': False, 'erro': f'Tipo não suportado: {extensao}'}

            numero_nota = self.extrair_numero_nota(texto)
            data_emissao = self.extrair_data_emissao(texto)
            data_recebimento = self.extrair_data_recebimento(texto)
            destinatario = self.extrair_destinatario(texto)
            valor_total = self.extrair_valor_total(texto)

            self.logger.info(
                'Arquivo processado: %s | nf=%s | emissao=%s | dest=%r | valor=%s | chars=%d',
                caminho.name, numero_nota, data_emissao, destinatario, valor_total, len(texto),
            )

            return {
                'texto': texto,
                'numero_nota': numero_nota,
                'data_emissao': data_emissao,
                'data_recebimento': data_recebimento,
                'destinatario': destinatario,
                'valor_total': valor_total,
                'sucesso': True,
                'erro': None,
            }

        except OCRException as exc:
            self.logger.error('OCRException: %s: %s', caminho_arquivo, exc)
            return {**_vazio, 'sucesso': False, 'erro': str(exc)}
        except Exception as exc:
            self.logger.exception('Erro inesperado: %s: %s', caminho_arquivo, exc)
            return {**_vazio, 'sucesso': False, 'erro': f'Erro inesperado: {exc}'}
