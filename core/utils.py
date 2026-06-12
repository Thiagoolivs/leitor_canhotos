"""
Utility functions for leitor_canhotos.

Functions:
- sanitize_filename(filename) -> str: removes dangerous characters from filenames.
- mover_arquivo(origem, destino) -> Path: moves a file, handling conflicts.
- garantir_diretorios(*dirs) -> None: creates directories if they don't exist.
- formatar_numero_nota(numero) -> str: normalizes invoice numbers (strips zeros/spaces).
"""
import logging
import re
import shutil
from pathlib import Path

from core.exceptions import ArquivoException

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    """
    Remove or replace characters that are unsafe in file names.

    Keeps alphanumerics, dots, dashes, and underscores.
    Replaces spaces with underscores and strips path separators.

    Args:
        filename: the original file name (basename only, not a full path).

    Returns:
        A safe file name string.
    """
    if not filename:
        return 'arquivo_sem_nome'
    # Take only the basename in case a path was accidentally passed
    basename = Path(filename).name
    # Replace spaces with underscores
    safe = basename.replace(' ', '_')
    # Remove any character that is not alphanumeric, dot, dash, or underscore
    safe = re.sub(r'[^\w.\-]', '', safe)
    # Collapse multiple dots
    safe = re.sub(r'\.{2,}', '.', safe)
    # Strip leading/trailing dots or underscores
    safe = safe.strip('._')
    return safe or 'arquivo'


def mover_arquivo(origem: str, destino: str) -> Path:
    """
    Move a file from origem to destino.

    If destino is a directory, the file is moved into that directory keeping its name.
    If a file with the same name already exists at the destination, a numeric suffix
    is appended to avoid overwriting.

    Args:
        origem: source file path (string or Path).
        destino: destination path — can be a directory or a full target file path.

    Returns:
        The actual Path where the file was moved to.

    Raises:
        ArquivoException: if the source file does not exist or the move fails.
    """
    origem_path = Path(origem)
    destino_path = Path(destino)

    if not origem_path.exists():
        raise ArquivoException(
            f'Arquivo de origem não encontrado: {origem}',
            caminho=str(origem_path),
        )

    # If destino is a directory, construct the full target path
    if destino_path.is_dir():
        destino_path = destino_path / origem_path.name

    # Avoid overwriting existing files by appending a counter
    if destino_path.exists():
        stem = destino_path.stem
        suffix = destino_path.suffix
        parent = destino_path.parent
        counter = 1
        while destino_path.exists():
            destino_path = parent / f'{stem}_{counter}{suffix}'
            counter += 1

    try:
        destino_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origem_path), str(destino_path))
        logger.debug('Arquivo movido: %s -> %s', origem_path, destino_path)
        return destino_path
    except OSError as exc:
        raise ArquivoException(
            f'Falha ao mover arquivo: {exc}',
            caminho=str(origem_path),
        ) from exc


def garantir_diretorios(*dirs) -> None:
    """
    Create one or more directories (and any necessary parents) if they do not exist.

    Args:
        *dirs: directory paths as strings or Path objects.

    Raises:
        ArquivoException: if a directory cannot be created.
    """
    for d in dirs:
        path = Path(d)
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.debug('Diretório garantido: %s', path)
        except OSError as exc:
            raise ArquivoException(
                f'Não foi possível criar diretório {d}: {exc}',
                caminho=str(path),
            ) from exc


def formatar_numero_nota(numero: str) -> str:
    """
    Normalize a Brazilian invoice (Nota Fiscal) number.

    Strips leading zeros, surrounding whitespace, and common OCR artefacts.
    Returns the number as a plain string without leading zeros.

    Examples:
        '001234' -> '1234'
        ' 0042 ' -> '42'
        'NF-0099' -> '99'  (strips non-digit prefix)

    Args:
        numero: raw number string extracted from OCR or user input.

    Returns:
        Normalized number string, or the original stripped string if normalization
        produces an empty result (i.e., the input had no digits at all).
    """
    if not numero:
        return ''

    stripped = numero.strip()

    # Extract digits only
    digits_only = re.sub(r'\D', '', stripped)

    if not digits_only:
        # Return the stripped original if there are no digits (unexpected format)
        return stripped

    # Convert to int to drop leading zeros, then back to str
    return str(int(digits_only))
