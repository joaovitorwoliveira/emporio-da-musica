import re
import unicodedata
from functools import cache
from pathlib import Path

from pypdf import PdfReader

from emporio.settings import POLICIES_PDF_PATH

PAGE_HEADER = "Empório da Música Manual de Políticas e Procedimentos"
PAGE_FOOTER_PATTERN = re.compile(r"Página \d+")
LIST_MARKER_PATTERN = re.compile(r"^(•|\d+\.)\s{2,}")
COLUMN_GAP_PATTERN = re.compile(r"\s{2,}")
COLUMN_SEPARATOR = " | "
BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
LAYOUT_EXTRACTION_MODE = "layout"


class PolicyError(Exception):
    pass


@cache
def load_policy_text(pdf_path: Path = POLICIES_PDF_PATH) -> str:
    if not pdf_path.is_file():
        raise PolicyError(f"Policy manual not found at {pdf_path}.")
    reader = PdfReader(pdf_path)
    pages = [
        page.extract_text(extraction_mode=LAYOUT_EXTRACTION_MODE) for page in reader.pages
    ]
    text = normalize_policy_text("\n\n".join(pages))
    if not text:
        raise PolicyError(f"No text could be extracted from the policy manual at {pdf_path}.")
    return text


def normalize_policy_text(raw_text: str) -> str:
    lines = [_normalize_line(line) for line in unicodedata.normalize("NFC", raw_text).splitlines()]
    kept = [line for line in lines if not _is_page_furniture(line)]
    compact = BLANK_LINES_PATTERN.sub("\n\n", "\n".join(_drop_table_row_gaps(kept)))
    return compact.strip()


def _normalize_line(line: str) -> str:
    stripped = line.strip()
    without_marker_padding = LIST_MARKER_PATTERN.sub(lambda m: m.group(1) + " ", stripped)
    return COLUMN_GAP_PATTERN.sub(COLUMN_SEPARATOR, without_marker_padding)


def _is_page_furniture(line: str) -> bool:
    return line == PAGE_HEADER or PAGE_FOOTER_PATTERN.fullmatch(line) is not None


def _drop_table_row_gaps(lines: list[str]) -> list[str]:
    result: list[str] = []
    for index, line in enumerate(lines):
        is_gap_between_rows = (
            line == ""
            and 0 < index < len(lines) - 1
            and COLUMN_SEPARATOR in lines[index - 1]
            and COLUMN_SEPARATOR in lines[index + 1]
        )
        if not is_gap_between_rows:
            result.append(line)
    return result
