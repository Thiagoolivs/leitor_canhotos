"""
Serviço de IA para análise de texto OCR incerto.

Usa Groq (Llama) como fallback quando o Tesseract retorna confiança BAIXA.
Envia o texto OCR bruto e pede para a IA extrair o número da nota fiscal.

Suporta múltiplas API keys (GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3)
com rotação automática para distribuir rate limits.
"""
import itertools
import json
import logging
import re
import threading
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_PROMPT_SISTEMA = (
    'Você é um assistente especializado em ler canhotos de notas fiscais '
    'brasileiras (DANFE). Você recebe texto extraído por OCR de scans físicos. '
    'O texto pode conter erros de OCR (letras trocadas, espaços extras, '
    'caracteres especiais, números cortados). Sua tarefa é encontrar o '
    'NÚMERO DA NOTA FISCAL no texto. Responda SEMPRE com JSON válido.'
)

_PROMPT_EXTRAIR = (
    'Extraia o número da nota fiscal do texto OCR abaixo.\n\n'
    'O número da NF geralmente tem entre 3 e 9 dígitos e aparece próximo a:\n'
    '- "N.", "Nº", "N°" seguido de dígitos (ex: "N. 000154108")\n'
    '- "NOTA FISCAL" seguido de número\n'
    '- "NF" ou "NF-e" seguido de número\n'
    '- "RECEBEMOS DE" — o canhoto do DANFE sempre tem esse texto\n'
    '- Pode ter zeros à esquerda: "000154108" = NF 154108\n\n'
    'IGNORE números que são CNPJ (XX.XXX.XXX/XXXX-XX), CEP, telefone, '
    'NCM (8 dígitos tipo 73101090), CFOP (4 dígitos tipo 5101/6102), '
    'ou códigos de barras (44 dígitos).\n\n'
    'Responda APENAS com JSON:\n'
    '{{"numero": "154108", "confianca": "ALTA", "motivo": "encontrado após Nº"}}\n\n'
    'Se não encontrar, responda:\n'
    '{{"numero": null, "confianca": "BAIXA", "motivo": "texto ilegível"}}\n\n'
    'Texto OCR:\n---\n{texto}\n---'
)

_PROMPT_CONFIRMAR = (
    'O OCR detectou o possível número de nota fiscal {numero_detectado} no texto '
    'abaixo, mas com baixa confiança.\n\n'
    'Analise o texto e responda:\n'
    '1. O número {numero_detectado} está correto? Confirme se aparece no contexto '
    'certo (próximo a "N.", "Nº", "NOTA FISCAL", "NF", "RECEBEMOS DE").\n'
    '2. Se o número estiver ERRADO, extraia o número correto.\n\n'
    'IGNORE CNPJ, CEP, NCM (73101090), CFOP (5101/6102), códigos de barras (44 dígitos).\n\n'
    'Responda APENAS com JSON:\n'
    '{{"numero": "154108", "confianca": "ALTA", "motivo": "confirmado no texto"}}\n\n'
    'Texto OCR:\n---\n{texto}\n---'
)

_lock = threading.Lock()
_key_cycle = None


def _carregar_chaves():
    """Carrega todas as API keys configuradas e retorna um itertools.cycle."""
    global _key_cycle
    chaves = []
    for attr in ('GROQ_API_KEY', 'GROQ_API_KEY_2', 'GROQ_API_KEY_3'):
        key = getattr(settings, attr, '')
        if key:
            chaves.append(key)
    if chaves:
        _key_cycle = itertools.cycle(chaves)
        logger.info('[IA] %d chave(s) Groq carregada(s)', len(chaves))
    return len(chaves)


def _proxima_chave() -> Optional[str]:
    """Retorna a próxima API key do ciclo (thread-safe)."""
    global _key_cycle
    if _key_cycle is None:
        if not _carregar_chaves():
            return None
    with _lock:
        return next(_key_cycle)


class AIService:
    """Analisa texto OCR incerto usando Groq (Llama) como fallback."""

    def __init__(self):
        self.model = getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile')
        primeira_chave = _proxima_chave()
        self.habilitado = bool(primeira_chave) and getattr(settings, 'AI_FALLBACK_HABILITADO', True)
        if self.habilitado:
            logger.info('[IA] Serviço iniciado: modelo=%s', self.model)
        else:
            logger.warning('[IA] Serviço DESABILITADO (sem API key ou desativado)')

    def analisar_texto_ocr(self, texto_ocr: str, numero_detectado: str = '') -> Optional[dict]:
        """
        Envia texto OCR para a IA e retorna o número da NF extraído.

        Args:
            texto_ocr: texto extraído pelo Tesseract.
            numero_detectado: número já detectado pelo OCR (para confirmar/corrigir).

        Returns:
            dict com {numero, confianca, motivo} ou None se falhar/desabilitado.
        """
        if not self.habilitado:
            logger.warning('[IA] Fallback desabilitado (sem API key ou desativado)')
            return None

        if not texto_ocr or len(texto_ocr.strip()) < 10:
            logger.warning('[IA] Texto OCR muito curto (%d chars)', len(texto_ocr) if texto_ocr else 0)
            return None

        texto_truncado = texto_ocr[:2000]
        api_key = _proxima_chave()

        if numero_detectado:
            prompt_user = _PROMPT_CONFIRMAR.format(
                texto=texto_truncado, numero_detectado=numero_detectado,
            )
        else:
            prompt_user = _PROMPT_EXTRAIR.format(texto=texto_truncado)

        try:
            logger.info('[IA] Enviando %d chars para Groq (%s, key=...%s, numero_atual=%s)...', len(texto_truncado), self.model, api_key[-4:], numero_detectado or 'nenhum')
            from groq import Groq
            client = Groq(api_key=api_key)

            response = client.chat.completions.create(
                model=self.model,
                max_tokens=200,
                temperature=0,
                messages=[
                    {'role': 'system', 'content': _PROMPT_SISTEMA},
                    {'role': 'user', 'content': prompt_user},
                ],
            )

            texto_resposta = response.choices[0].message.content.strip()
            logger.info('[IA] Resposta recebida: %s', texto_resposta[:100])

            resultado = self._parse_resposta(texto_resposta)
            if resultado:
                logger.info(
                    '[IA] Sucesso! numero=%s confianca=%s motivo=%s',
                    resultado.get('numero'), resultado.get('confianca'), resultado.get('motivo'),
                )
            else:
                logger.warning('[IA] Não conseguiu parsear resposta')
            return resultado

        except Exception as exc:
            logger.error('[IA] ERRO ao chamar Groq: %s', exc, exc_info=True)
            return None

    def _parse_resposta(self, texto: str) -> Optional[dict]:
        """Extrai o JSON da resposta da IA."""
        match = re.search(r'\{[^}]+\}', texto, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

        numero = data.get('numero')
        if numero is not None:
            numero = str(numero).strip()
            numero = re.sub(r'^0+', '', numero)
            if not numero or not numero.isdigit():
                numero = None

        return {
            'numero': numero,
            'confianca': data.get('confianca', 'MEDIA'),
            'motivo': data.get('motivo', ''),
        }
