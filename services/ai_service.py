"""
Serviço de IA para análise de texto OCR incerto.

Usa Groq (Llama) como fallback quando o Tesseract retorna confiança BAIXA.
Envia o texto OCR bruto e pede para a IA extrair o número da nota fiscal.
"""
import json
import logging
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_PROMPT_SISTEMA = (
    'Você é um assistente especializado em ler textos OCR de canhotos de notas '
    'fiscais brasileiras (DANFE). O texto vem de um scan físico e pode conter '
    'erros de OCR (letras trocadas, espaços extras, caracteres especiais). '
    'Sua tarefa é encontrar o NÚMERO DA NOTA FISCAL no texto.'
)

_PROMPT_USUARIO = (
    'Analise o texto OCR abaixo de um canhoto de nota fiscal e extraia o número '
    'da nota fiscal. O número geralmente tem entre 5 e 9 dígitos.\n\n'
    'Procure por padrões como:\n'
    '- "N." ou "Nº" seguido de dígitos\n'
    '- "NOTA FISCAL" seguido de número\n'
    '- "NF" ou "NF-e" seguido de número\n'
    '- Números isolados de 5 a 9 dígitos que pareçam ser o número da NF\n'
    '- Números com zeros à esquerda (ex: 000154108 = 154108)\n\n'
    'Responda APENAS com um JSON no formato:\n'
    '{{"numero": "123456", "confianca": "ALTA ou MEDIA ou BAIXA", '
    '"motivo": "breve explicação"}}\n\n'
    'Se não encontrar nenhum número de nota fiscal, responda:\n'
    '{{"numero": null, "confianca": "BAIXA", "motivo": "motivo"}}\n\n'
    'Texto OCR:\n---\n{texto}\n---'
)


class AIService:
    """Analisa texto OCR incerto usando Groq (Llama) como fallback."""

    def __init__(self):
        self.api_key = getattr(settings, 'GROQ_API_KEY', '')
        self.model = getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile')
        self.habilitado = bool(self.api_key) and getattr(settings, 'AI_FALLBACK_HABILITADO', True)
        if self.habilitado:
            logger.info('[IA] Serviço iniciado: modelo=%s, api_key_presente=%s', self.model, bool(self.api_key))
        else:
            logger.warning('[IA] Serviço DESABILITADO (api_key=%s, fallback_habilitado=%s)', bool(self.api_key), getattr(settings, 'AI_FALLBACK_HABILITADO', True))

    def analisar_texto_ocr(self, texto_ocr: str) -> Optional[dict]:
        """
        Envia texto OCR para a IA e retorna o número da NF extraído.

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

        try:
            logger.info('[IA] Enviando %d chars para Groq (%s)...', len(texto_truncado), self.model)
            from groq import Groq
            client = Groq(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                max_tokens=200,
                temperature=0,
                messages=[
                    {'role': 'system', 'content': _PROMPT_SISTEMA},
                    {'role': 'user', 'content': _PROMPT_USUARIO.format(texto=texto_truncado)},
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
