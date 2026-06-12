"""
OCR Service for extracting invoice numbers from PDF/image files.

Architecture:
- pdf2image converts each PDF page to a PIL Image.
- pytesseract performs OCR with Portuguese language pack.
- Regex patterns (from settings.NOTA_NUMBER_PATTERNS) find the invoice number.
- Returns a structured result dict so callers do not need to handle raw exceptions.

Dependencies:
- tesseract-ocr + tesseract-ocr-por (installed in Dockerfile)
- poppler-utils (for pdf2image, installed in Dockerfile)
- Pillow, pdf2image, pytesseract (in requirements.txt)
"""
import logging
import re
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class OCRService:
    """
    Extracts text and Brazilian invoice numbers from PDF and image files via OCR.

    Usage:
        service = OCRService()
        result = service.processar_arquivo('/path/to/file.pdf')
        # result = {'texto': '...', 'numero_nota': '1234', 'sucesso': True, 'erro': None}
    """

    # Tesseract OCR configuration: Brazilian Portuguese + numeric-friendly PSM
    TESSERACT_CONFIG = '--oem 3 --psm 6 -l por+eng'

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Load patterns from Django settings; fall back to built-in defaults if not set
        self.patterns = getattr(
            settings,
            'NOTA_NUMBER_PATTERNS',
            [
                r'NOTA\s+FISCAL\s+(?:ELETR[OÔ]NICA\s+)?N[Oo°\.º]?\s*:?\s*(\d{1,6})',
                r'N[Oo°\.º]\s*:?\s*(\d{1,6})',
                r'NF\s*[-:]\s*(\d{1,6})',
                r'N[ÚúUu]MERO\s*(?:DA\s+NOTA)?\s*:?\s*(\d{1,6})',
                r'(?:^|\s)(\d{6})(?:\s|$)',
            ],
        )

    def extrair_texto_pdf(self, caminho_pdf: str) -> str:
        """
        Convert each page of a PDF to an image and run OCR on each page.

        Args:
            caminho_pdf: absolute path to the PDF file.

        Returns:
            Concatenated OCR text from all pages, with page breaks as '\n--- PÁGINA %d ---\n'.

        Raises:
            core.exceptions.OCRException: on pdf2image or tesseract failure.
        """
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
        import pytesseract
        from core.exceptions import OCRException

        try:
            self.logger.info('Convertendo PDF para imagens: %s', caminho_pdf)
            imagens = convert_from_path(
                caminho_pdf,
                dpi=300,
                fmt='png',
                thread_count=1,
            )
        except (PDFInfoNotInstalledError, PDFPageCountError, Exception) as exc:
            raise OCRException(
                f'Falha ao converter PDF para imagem: {exc}',
                caminho_arquivo=caminho_pdf,
            ) from exc

        if not imagens:
            raise OCRException(
                'Nenhuma página encontrada no PDF.',
                caminho_arquivo=caminho_pdf,
            )

        textos = []
        for i, imagem in enumerate(imagens, start=1):
            try:
                texto_pagina = pytesseract.image_to_string(
                    imagem,
                    config=self.TESSERACT_CONFIG,
                )
                textos.append(f'\n--- PÁGINA {i} ---\n{texto_pagina}')
                self.logger.debug('OCR página %d: %d caracteres extraídos', i, len(texto_pagina))
            except Exception as exc:
                self.logger.warning('Erro OCR na página %d: %s', i, exc)
                textos.append(f'\n--- PÁGINA {i} (ERRO OCR) ---\n')

        return '\n'.join(textos)

    def extrair_texto_imagem(self, caminho_imagem: str) -> str:
        """
        Run OCR directly on an image file (PNG, JPG, TIFF, etc.).

        Args:
            caminho_imagem: absolute path to the image file.

        Returns:
            OCR text string.

        Raises:
            core.exceptions.OCRException: on failure.
        """
        import pytesseract
        from PIL import Image
        from core.exceptions import OCRException

        try:
            self.logger.info('Executando OCR em imagem: %s', caminho_imagem)
            imagem = Image.open(caminho_imagem)
            texto = pytesseract.image_to_string(imagem, config=self.TESSERACT_CONFIG)
            self.logger.debug('OCR imagem: %d caracteres extraídos', len(texto))
            return texto
        except Exception as exc:
            raise OCRException(
                f'Falha no OCR da imagem: {exc}',
                caminho_arquivo=caminho_imagem,
            ) from exc

    def extrair_numero_nota(self, texto: str) -> Optional[str]:
        """
        Search OCR text for a Brazilian Nota Fiscal number using configured regex patterns.

        Tries each pattern in order (most specific first) and returns the first match.
        The matched number is normalized: stripped of leading zeros and whitespace.

        Args:
            texto: raw OCR text string.

        Returns:
            Normalized invoice number string, or None if no pattern matched.
        """
        if not texto:
            return None

        texto_upper = texto.upper()

        for pattern in self.patterns:
            try:
                matches = re.findall(pattern, texto_upper, re.MULTILINE | re.IGNORECASE)
                if matches:
                    numero_raw = matches[0].strip()
                    # Normalize: remove leading zeros
                    if numero_raw.isdigit():
                        numero = str(int(numero_raw))
                    else:
                        numero = numero_raw
                    self.logger.debug(
                        'Número encontrado com padrão "%s": %s (raw: %s)',
                        pattern, numero, numero_raw,
                    )
                    return numero
            except re.error as exc:
                self.logger.warning('Padrão regex inválido "%s": %s', pattern, exc)

        self.logger.info('Nenhum número de nota encontrado no texto OCR.')
        return None

    def processar_arquivo(self, caminho_arquivo: str) -> dict:
        """
        Main entry point: extract text and invoice number from a file.

        Determines whether the file is a PDF or image and dispatches accordingly.

        Args:
            caminho_arquivo: absolute path to the file to process.

        Returns:
            A dict with keys:
                - 'texto' (str): full OCR text extracted from the file.
                - 'numero_nota' (str|None): detected invoice number, or None.
                - 'sucesso' (bool): True if OCR completed without critical errors.
                - 'erro' (str|None): error message if sucesso is False, else None.
        """
        from core.exceptions import OCRException

        caminho = Path(caminho_arquivo)

        if not caminho.exists():
            return {
                'texto': '',
                'numero_nota': None,
                'sucesso': False,
                'erro': f'Arquivo não encontrado: {caminho_arquivo}',
            }

        extensao = caminho.suffix.lower()

        try:
            if extensao == '.pdf':
                texto = self.extrair_texto_pdf(str(caminho))
            elif extensao in {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}:
                texto = self.extrair_texto_imagem(str(caminho))
            else:
                return {
                    'texto': '',
                    'numero_nota': None,
                    'sucesso': False,
                    'erro': f'Tipo de arquivo não suportado: {extensao}',
                }

            numero_nota = self.extrair_numero_nota(texto)

            self.logger.info(
                'Arquivo processado: %s | numero_nota=%s | texto_chars=%d',
                caminho.name, numero_nota, len(texto),
            )

            return {
                'texto': texto,
                'numero_nota': numero_nota,
                'sucesso': True,
                'erro': None,
            }

        except OCRException as exc:
            self.logger.error('OCRException ao processar %s: %s', caminho_arquivo, exc)
            return {
                'texto': '',
                'numero_nota': None,
                'sucesso': False,
                'erro': str(exc),
            }
        except Exception as exc:
            self.logger.exception('Erro inesperado ao processar %s: %s', caminho_arquivo, exc)
            return {
                'texto': '',
                'numero_nota': None,
                'sucesso': False,
                'erro': f'Erro inesperado: {exc}',
            }
