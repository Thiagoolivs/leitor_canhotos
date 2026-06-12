"""
Custom exceptions for leitor_canhotos.

Hierarchy:
    LeitorCanhotosException (base)
    ├── OCRException          -- raised by OCRService when text extraction fails
    ├── ConciliacaoException  -- raised when linking canhoto <-> nota fails
    ├── ArquivoException      -- raised on file-system operations (move, access)
    └── NotaFiscalNaoEncontradaException  -- raised when a nota cannot be found by number
"""


class LeitorCanhotosException(Exception):
    """Base exception for all domain errors in leitor_canhotos."""

    def __init__(self, message: str = '', *args):
        self.message = message
        super().__init__(message, *args)

    def __str__(self):
        return self.message


class OCRException(LeitorCanhotosException):
    """
    Raised when the OCR pipeline fails to extract text from a file.

    Attributes:
        caminho_arquivo: path to the file that caused the error (optional).
    """

    def __init__(self, message: str = '', caminho_arquivo: str = ''):
        super().__init__(message)
        self.caminho_arquivo = caminho_arquivo

    def __str__(self):
        if self.caminho_arquivo:
            return f'OCRException [{self.caminho_arquivo}]: {self.message}'
        return f'OCRException: {self.message}'


class ConciliacaoException(LeitorCanhotosException):
    """
    Raised when the reconciliation (conciliação) between canhoto and nota fiscal fails.

    Attributes:
        canhoto_id: ID of the canhoto involved (optional).
        nota_numero: invoice number involved (optional).
    """

    def __init__(self, message: str = '', canhoto_id: int = 0, nota_numero: str = ''):
        super().__init__(message)
        self.canhoto_id = canhoto_id
        self.nota_numero = nota_numero

    def __str__(self):
        parts = ['ConciliacaoException']
        if self.canhoto_id:
            parts.append(f'canhoto_id={self.canhoto_id}')
        if self.nota_numero:
            parts.append(f'nota={self.nota_numero}')
        parts.append(self.message)
        return ' | '.join(parts)


class ArquivoException(LeitorCanhotosException):
    """
    Raised on file-system errors (file not found, permission denied, move failure).

    Attributes:
        caminho: the file path involved (optional).
    """

    def __init__(self, message: str = '', caminho: str = ''):
        super().__init__(message)
        self.caminho = caminho

    def __str__(self):
        if self.caminho:
            return f'ArquivoException [{self.caminho}]: {self.message}'
        return f'ArquivoException: {self.message}'


class NotaFiscalNaoEncontradaException(LeitorCanhotosException):
    """
    Raised when a Nota Fiscal cannot be found by its number or ID.

    Attributes:
        numero: the invoice number that was searched for (optional).
    """

    def __init__(self, message: str = '', numero: str = ''):
        super().__init__(message or f'Nota Fiscal não encontrada: {numero}')
        self.numero = numero

    def __str__(self):
        if self.numero:
            return f'NotaFiscalNaoEncontradaException: numero={self.numero} | {self.message}'
        return f'NotaFiscalNaoEncontradaException: {self.message}'
