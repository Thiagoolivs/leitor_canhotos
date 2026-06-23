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

# ---------------------------------------------------------------------------
# Detecção de folhas divisórias (índices de controle dos canhotos)
# ---------------------------------------------------------------------------
# Uma folha divisória lista vários números de NF sequenciais (ex: 151211..151220),
# às vezes com canhotos recortados colados nela. Palavras-chave que indicam a
# presença de um canhoto físico colado (DANFE/recibo):
_RE_STUB_KEYWORDS = re.compile(
    r'RECEBEMOS\s+DE|DATA\s+DE\s+RECEBIMENTO|ASSINATURA\s+DO\s+RECEBEDOR|'
    r'IDENTIFICA[CÇ][AÃ]O\s+E\s+ASSINATURA',
    re.IGNORECASE,
)
# Número impresso do canhoto colado, ex: "N. 00015995 SÉRIE 3"
_RE_NUMERO_STUB = re.compile(r'N[º°.\s]+0*(\d{4,9})\s*S[ÉE]RIE', re.IGNORECASE)
# Número isolado de 5 a 9 dígitos (sem fazer parte de um número maior)
_RE_NUMERO_ISOLADO = re.compile(r'(?<!\d)(\d{5,9})(?!\d)')
# Mínimo de números consecutivos para classificar a página como divisória
_MIN_SEQUENCIA_DIVISORIA = 4


class OCRService:
    """
    Extrai texto e dados de NF de PDFs e imagens.

    Para PDFs, tenta primeiro extração digital (pdfplumber) e usa OCR como fallback.
    """

    TESSERACT_CONFIG = '--oem 3 --psm 6 -l por+eng'

    @staticmethod
    def _preprocessar_imagem(imagem):
        """
        Escala de cinza + autocontraste + nitidez antes do OCR.

        Scans físicos costumam vir com fundo amarelado/cinza e pouco contraste,
        o que confunde o Tesseract. autocontrast() estica o histograma (remove
        esse "véu" sem precisar de um threshold fixo, que erraria em scans com
        iluminação desigual) e SHARPEN realça as bordas dos caracteres.
        """
        from PIL import ImageFilter, ImageOps

        cinza = ImageOps.grayscale(imagem)
        contrastada = ImageOps.autocontrast(cinza, cutoff=1)
        return contrastada.filter(ImageFilter.SHARPEN)

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.patterns = getattr(
            settings,
            'NOTA_NUMBER_PATTERNS',
            [
                r'NOTA\s+FISCAL\s+(?:ELETR[OÔ]NICA\s+)?N[Oo°\.º]?\s*:?\s*(\d{4,9})',
                r'N[Oo°\.º]\s+NOTA\s+FISCAL\s*:?\s*(\d{4,9})',
                r'N[Oo°\.º\.]\s*:?\s*(\d{4,9})',
                r'NF[-\s]*[Ee]?\s*:?\s*(\d{4,9})',
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
                imagem_proc = self._preprocessar_imagem(imagem)
                texto_pagina = pytesseract.image_to_string(imagem_proc, config=self.TESSERACT_CONFIG)
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
            imagem_proc = self._preprocessar_imagem(imagem)
            texto = pytesseract.image_to_string(imagem_proc, config=self.TESSERACT_CONFIG)
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

        Tenta em ordem:
        1. zxing-cpp  — funciona no Windows sem DLLs externas (pip install zxing-cpp)
        2. pyzbar     — requer libzbar-64.dll no Windows (fallback)

        A chave de acesso NF-e tem 44 dígitos; o número da NF está nas pos. 25-33.
        Retorna None silenciosamente se nenhuma biblioteca estiver disponível.
        """
        chave = self._ler_chave_acesso_zxing(imagem) or self._ler_chave_acesso_pyzbar(imagem)
        if chave and chave.isdigit() and len(chave) == 44:
            numero_raw = chave[25:34]
            numero = str(int(numero_raw)) if numero_raw.isdigit() and int(numero_raw) > 0 else None
            if numero:
                self.logger.info('Barcode: NF=%s (chave=%s...%s)', numero, chave[:6], chave[-4:])
                return numero
        return None

    def _ler_chave_acesso_zxing(self, imagem) -> Optional[str]:
        """Lê código de barras usando zxing-cpp (sem DLL externa no Windows)."""
        try:
            import zxingcpp
            resultados = zxingcpp.read_barcodes(imagem)
            for r in resultados:
                texto = r.text.strip()
                if texto.isdigit() and len(texto) == 44:
                    return texto
        except Exception as exc:
            self.logger.debug('zxing-cpp indisponível (%s).', type(exc).__name__)
        return None

    def _ler_chave_acesso_pyzbar(self, imagem) -> Optional[str]:
        """Lê código de barras usando pyzbar (fallback; requer libzbar no Windows)."""
        try:
            from pyzbar.pyzbar import decode
            for d in decode(imagem):
                texto = d.data.decode('utf-8', errors='ignore').strip()
                if texto.isdigit() and len(texto) == 44:
                    return texto
        except Exception as exc:
            self.logger.debug('pyzbar indisponível (%s).', type(exc).__name__)
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

    # ------------------------------------------------------------------
    # Classificação de página: canhoto x folha divisória
    # ------------------------------------------------------------------

    def detectar_sequencia_numeros(self, texto: str, minimo: int = _MIN_SEQUENCIA_DIVISORIA) -> tuple:
        """
        Detecta um agrupamento de números de NF próximos (uma folha divisória).

        Folhas divisórias listam vários números de NF em ordem (ex: 151211..151220).
        Números próximos (diferença <= 3) são agrupados em um cluster, tolerando
        falhas de OCR e números cobertos por canhotos colados.

        Retorna uma tupla (completa, faltantes):
        - completa: lista contígua do menor ao maior número do cluster
                    (ex: [151991, 151992, ..., 152000])
        - faltantes: números dentro do intervalo que o OCR NÃO leu diretamente
                     (provavelmente cobertos por canhotos colados, ex: [151995, 151996])
        Retorna ([], []) se não houver cluster com pelo menos `minimo` números.
        """
        if not texto:
            return [], []
        numeros = sorted({int(m) for m in _RE_NUMERO_ISOLADO.findall(texto)})
        if len(numeros) < minimo:
            return [], []

        # Agrupa números próximos (gap <= 3) em clusters
        clusters: list = []
        atual = [numeros[0]]
        for n in numeros[1:]:
            if n - atual[-1] <= 3:
                atual.append(n)
            else:
                clusters.append(atual)
                atual = [n]
        clusters.append(atual)

        maior = max(clusters, key=len)
        if len(maior) < minimo:
            return [], []

        completa = list(range(maior[0], maior[-1] + 1))
        lidos = set(maior)
        faltantes = [n for n in completa if n not in lidos]
        return completa, faltantes

    def classificar_pagina(self, texto: str) -> dict:
        """
        Classifica a página a partir do texto OCR.

        Retorna dict com:
        - tipo_pagina: 'CANHOTO' | 'DIVISORIA' | 'DIVISORIA_MISTA'
        - numeros_sequencia: lista contígua de números da divisória (vazia se for canhoto)
        - numeros_faltantes: números do intervalo cobertos por canhotos colados
        - numeros_canhotos: números de canhotos colados detectados
        - canhotos_info: lista de dicts com {numero, confianca, origem} por canhoto
        """
        completa, faltantes = self.detectar_sequencia_numeros(texto)
        if not completa:
            return {
                'tipo_pagina': 'CANHOTO',
                'numeros_sequencia': [], 'numeros_faltantes': [], 'numeros_canhotos': [],
                'canhotos_info': [],
            }

        stubs_impressos = []
        vistos = set()
        for m in _RE_NUMERO_STUB.findall(texto or ''):
            num = str(int(m))
            if num not in vistos:
                vistos.add(num)
                stubs_impressos.append(num)

        tem_keyword = bool(_RE_STUB_KEYWORDS.search(texto or ''))

        if faltantes or stubs_impressos or tem_keyword:
            faltantes_str = set(str(n) for n in faltantes)
            stubs_set = set(stubs_impressos)

            canhotos_info = []
            for num in [str(n) for n in faltantes]:
                if num in stubs_set:
                    canhotos_info.append({'numero': num, 'confianca': 'ALTA', 'origem': 'gap+stub'})
                elif tem_keyword:
                    canhotos_info.append({'numero': num, 'confianca': 'MEDIA', 'origem': 'gap+keyword'})
                else:
                    canhotos_info.append({'numero': num, 'confianca': 'BAIXA', 'origem': 'gap'})

            for num in stubs_impressos:
                if num not in faltantes_str:
                    canhotos_info.append({'numero': num, 'confianca': 'MEDIA', 'origem': 'stub'})

            numeros_canhotos = [c['numero'] for c in canhotos_info]

            self.logger.info(
                'Folha DIVISÓRIA MISTA: %d números (%s..%s), %d canhoto(s): %s',
                len(completa), completa[0], completa[-1], len(canhotos_info),
                [(c['numero'], c['confianca']) for c in canhotos_info],
            )
            return {
                'tipo_pagina': 'DIVISORIA_MISTA',
                'numeros_sequencia': completa,
                'numeros_faltantes': faltantes,
                'numeros_canhotos': numeros_canhotos,
                'canhotos_info': canhotos_info,
            }

        self.logger.info(
            'Folha DIVISÓRIA PURA: %d números (%s..%s)',
            len(completa), completa[0], completa[-1],
        )
        return {
            'tipo_pagina': 'DIVISORIA',
            'numeros_sequencia': completa, 'numeros_faltantes': [], 'numeros_canhotos': [],
            'canhotos_info': [],
        }

    def analisar_divisoria_espacial(self, imagem_proc, texto: str, classificacao: dict) -> list:
        """
        Enriquece canhotos_info com análise espacial via image_to_data.

        Duas etapas:
        1. Para cada canhoto inferido por GAP, recorta a região entre os números
           impressos vizinhos e roda OCR focado para confirmar o número
           (gap + OCR concordam → ALTA).
        2. Detecta canhotos colados nas BORDAS — acima do primeiro ou abaixo do
           último número impresso. Esses cobrem números fora do intervalo
           [min, max] da sequência detectada, então não geram gap e seriam
           perdidos pela etapa 1.
        """
        import pytesseract

        canhotos_info = list(classificacao.get('canhotos_info', []))
        sequencia = classificacao.get('numeros_sequencia', [])
        if not sequencia:
            return canhotos_info

        largura, altura = imagem_proc.size

        try:
            data = pytesseract.image_to_data(
                imagem_proc, config=self.TESSERACT_CONFIG,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            self.logger.warning('image_to_data falhou na análise espacial: %s', exc)
            return canhotos_info

        # Mapeia a posição Y (centro) de cada número impresso da sequência
        seq_set = set(sequencia)
        y_por_numero = {}
        for i in range(len(data['text'])):
            texto_w = data['text'][i].strip()
            try:
                conf = int(data['conf'][i])
            except (ValueError, TypeError):
                continue
            if not texto_w or conf < 20:
                continue
            limpo = re.sub(r'[^\d]', '', texto_w)
            if 5 <= len(limpo) <= 9:
                try:
                    num = int(limpo)
                except ValueError:
                    continue
                if num in seq_set and num not in y_por_numero:
                    y_por_numero[num] = data['top'][i] + data['height'][i] // 2

        if len(y_por_numero) < 2:
            self.logger.debug('Análise espacial: poucos números posicionados (%d)', len(y_por_numero))
            return canhotos_info

        # Etapa 1: refina canhotos inferidos por gap
        resultado = [
            self._refinar_canhoto_gap(info, imagem_proc, sequencia, y_por_numero, largura, altura)
            for info in canhotos_info
        ]

        # Etapa 2: detecta canhotos nas bordas (fora do intervalo da sequência)
        numeros_ja = {c['numero'] for c in resultado}
        resultado += self._detectar_canhotos_borda(
            imagem_proc, sequencia, y_por_numero, largura, altura, numeros_ja,
        )

        alta = sum(1 for c in resultado if c['confianca'] == 'ALTA')
        self.logger.info(
            'Análise espacial concluída: %d canhoto(s), %d com confiança ALTA',
            len(resultado), alta,
        )
        return resultado

    def _refinar_canhoto_gap(self, info, imagem_proc, sequencia, y_por_numero, largura, altura):
        """
        Recorta a região do gap (entre os números impressos vizinhos legíveis)
        e roda OCR focado. Se o número lido confirma o inferido pelo gap, a
        confiança sobe para ALTA. Retorna o info (possivelmente atualizado).
        """
        import pytesseract

        if info['confianca'] == 'ALTA':
            return info
        try:
            num_int = int(info['numero'])
        except (ValueError, TypeError):
            return info
        if num_int not in sequencia:
            return info

        idx = sequencia.index(num_int)

        y_acima = 0
        for j in range(idx - 1, -1, -1):
            if sequencia[j] in y_por_numero:
                y_acima = y_por_numero[sequencia[j]]
                break

        y_abaixo = altura
        for j in range(idx + 1, len(sequencia)):
            if sequencia[j] in y_por_numero:
                y_abaixo = y_por_numero[sequencia[j]]
                break

        if y_abaixo <= y_acima + 30:
            return info

        margem = 10
        crop_box = (0, max(0, y_acima + margem), largura, min(altura, y_abaixo - margem))
        try:
            recorte = imagem_proc.crop(crop_box)
            texto_recorte = pytesseract.image_to_string(recorte, config=self.TESSERACT_CONFIG)

            numero_lido = None
            m_stub = _RE_NUMERO_STUB.search(texto_recorte)
            if m_stub:
                numero_lido = str(int(m_stub.group(1)))
            if not numero_lido:
                numero_lido = self.extrair_numero_nota(texto_recorte)

            tem_keyword_recorte = bool(_RE_STUB_KEYWORDS.search(texto_recorte))

            if numero_lido and numero_lido == info['numero']:
                self.logger.info('Análise espacial: NF %s confirmada por OCR de recorte [ALTA]', info['numero'])
                return {'numero': info['numero'], 'confianca': 'ALTA', 'origem': 'gap+ocr_recorte'}
            if numero_lido:
                return {'numero': numero_lido, 'confianca': 'MEDIA', 'origem': 'ocr_recorte'}
            if tem_keyword_recorte:
                return {'numero': info['numero'], 'confianca': 'MEDIA', 'origem': 'gap+keyword_recorte'}
            return info
        except Exception as exc:
            self.logger.debug('Falha no OCR de recorte para NF %s: %s', info['numero'], exc)
            return info

    def _detectar_canhotos_borda(self, imagem_proc, sequencia, y_por_numero, largura, altura, numeros_ja):
        """
        Detecta canhotos colados nas bordas da folha:
        - TOPO: acima do primeiro número impresso (cobrem números < min da sequência)
        - BASE: abaixo do último número impresso (cobrem números > max da sequência)

        Só dispara quando a região da borda contém palavras-chave de recibo
        ("RECEBEMOS"/"ASSINATURA"), evitando falsos positivos em cabeçalhos.
        Lê o número impresso no canhoto; se contíguo à sequência, confiança ALTA;
        se ilegível, registra o número inferido (min-1 / max+1) em BAIXA p/ revisão.
        """
        import pytesseract

        novos = []
        margem = 10
        y_first = min(y_por_numero.values())
        y_last = max(y_por_numero.values())
        minimo, maximo = min(sequencia), max(sequencia)

        # (nome, caixa_de_recorte, numero_inferido, faixa_contigua)
        bordas = []
        if y_first > 60:  # há espaço útil acima do primeiro número
            bordas.append((
                'topo',
                (0, 0, largura, max(1, y_first - margem)),
                minimo - 1,
                set(range(minimo - 3, minimo)),
            ))
        if altura - y_last > 60:  # há espaço útil abaixo do último número
            bordas.append((
                'base',
                (0, min(altura - 1, y_last + margem), largura, altura),
                maximo + 1,
                set(range(maximo + 1, maximo + 4)),
            ))

        for nome, crop_box, inferido, faixa_contigua in bordas:
            try:
                crop = imagem_proc.crop(crop_box)
                texto_borda = pytesseract.image_to_string(crop, config=self.TESSERACT_CONFIG)
            except Exception as exc:
                self.logger.debug('Falha ao recortar borda %s: %s', nome, exc)
                continue

            if not _RE_STUB_KEYWORDS.search(texto_borda):
                continue  # sem recibo na borda → nada a detectar

            numeros_borda = []
            for m in _RE_NUMERO_STUB.findall(texto_borda):
                num = str(int(m))
                if num not in numeros_borda:
                    numeros_borda.append(num)
            if not numeros_borda:
                n = self.extrair_numero_nota(texto_borda)
                if n:
                    numeros_borda.append(n)

            if numeros_borda:
                for num in numeros_borda:
                    if num in numeros_ja:
                        continue
                    numeros_ja.add(num)
                    try:
                        contiguo = int(num) in faixa_contigua
                    except ValueError:
                        contiguo = False
                    conf = 'ALTA' if contiguo else 'MEDIA'
                    novos.append({'numero': num, 'confianca': conf, 'origem': f'borda_{nome}'})
                    self.logger.info('Canhoto na borda %s: NF=%s [%s]', nome, num, conf)
            elif inferido > 0:
                inferido_str = str(inferido)
                if inferido_str not in numeros_ja:
                    numeros_ja.add(inferido_str)
                    novos.append({
                        'numero': inferido_str, 'confianca': 'BAIXA',
                        'origem': f'borda_{nome}_inferido',
                    })
                    self.logger.info(
                        'Canhoto na borda %s detectado, número ilegível (inferido %s) [BAIXA]',
                        nome, inferido_str,
                    )

        return novos

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
            'tipo_pagina': 'CANHOTO', 'numeros_sequencia': [],
            'numeros_faltantes': [], 'numeros_canhotos': [],
            'canhotos_info': [],
        }

        try:
            imagens = self._obter_imagens_pagina(caminho)
        except Exception as exc:
            raise OCRException(f'Falha ao converter para imagem: {exc}', caminho_arquivo=caminho) from exc

        if not imagens:
            raise OCRException('Arquivo sem páginas.', caminho_arquivo=caminho)

        imagem = imagens[0]  # canhoto = página única

        # OCR (o barcode abaixo usa a imagem original — colorida ajuda o zxing/pyzbar)
        try:
            imagem_proc = self._preprocessar_imagem(imagem)
            texto = pytesseract.image_to_string(imagem_proc, config=self.TESSERACT_CONFIG)
            self.logger.debug('OCR canhoto: %d chars', len(texto))
        except Exception as exc:
            texto = ''
            self.logger.warning('OCR falhou na página: %s', exc)

        # Classificação: a página é um canhoto normal ou uma folha divisória?
        classificacao = self.classificar_pagina(texto)
        if classificacao['tipo_pagina'] != 'CANHOTO':
            canhotos_info = classificacao.get('canhotos_info', [])
            if classificacao['tipo_pagina'] == 'DIVISORIA_MISTA':
                canhotos_info = self.analisar_divisoria_espacial(
                    imagem_proc, texto, classificacao,
                )
            return {
                **_vazio,
                'texto': texto,
                'tipo_pagina': classificacao['tipo_pagina'],
                'numeros_sequencia': classificacao['numeros_sequencia'],
                'numeros_faltantes': classificacao['numeros_faltantes'],
                'numeros_canhotos': (
                    [c['numero'] for c in canhotos_info]
                    if canhotos_info
                    else classificacao['numeros_canhotos']
                ),
                'canhotos_info': canhotos_info,
                'sucesso': True,
                'erro': None,
            }

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
