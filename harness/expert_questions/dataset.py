"""Parse the expert-level question set from the provided PDF."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections.abc import Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = ROOT / "100 Expert-Level Benchmark Questions for LLMs.pdf"


@dataclass(frozen=True)
class Question:
    number: int
    prompt: str
    answer: str


class _PDFParseError(RuntimeError):
    """Raised when the question PDF cannot be parsed correctly."""


def _iter_pdf_streams(data: bytes) -> Iterator[bytes]:
    pattern = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
    for match in pattern.finditer(data):
        raw = match.group(1)
        try:
            yield zlib.decompress(raw)
        except zlib.error:
            continue


def _build_cmap(streams: Iterable[bytes]) -> dict[bytes, str]:
    cmap: dict[bytes, str] = {}
    cmap_pattern = re.compile(rb"begincmap(.*?)endcmap", re.S)
    bfchar_pattern = re.compile(rb"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>")

    for stream in streams:
        for cmap_block_match in cmap_pattern.finditer(stream):
            block = cmap_block_match.group(1)
            for glyph_match in bfchar_pattern.finditer(block):
                src_hex, dst_hex = glyph_match.groups()
                if not src_hex or not dst_hex:
                    continue
                try:
                    src_bytes = bytes.fromhex(src_hex.decode())
                    dst_bytes = bytes.fromhex(dst_hex.decode())
                except ValueError:
                    continue
                if not dst_bytes:
                    continue
                if len(dst_bytes) % 2 != 0:
                    # fall back to latin-1 decode when pairs are not available
                    cmap[src_bytes] = dst_bytes.decode("latin-1")
                    continue
                chars: list[str] = []
                for index in range(0, len(dst_bytes), 2):
                    codepoint = int.from_bytes(dst_bytes[index : index + 2], "big")
                    if 0 <= codepoint <= 0x10FFFF:
                        chars.append(chr(codepoint))
                if chars:
                    cmap[src_bytes] = "".join(chars)
    return cmap


def _decode_text_objects(data: bytes, cmap: dict[bytes, str]) -> list[str]:
    texts: list[str] = []
    text_objects_pattern = re.compile(rb"BT(.*?)ET", re.S)
    array_pattern = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
    hex_pattern = re.compile(rb"<([0-9A-Fa-f]+)>")
    single_pattern = re.compile(rb"<([0-9A-Fa-f]+)>\s*Tj")

    def decode_hex_bytes(hex_bytes: bytes) -> str:
        raw = bytes.fromhex(hex_bytes.decode())
        if not raw:
            return ""
        step = 2 if len(raw) % 2 == 0 else 1
        decoded_parts: list[str] = []
        for index in range(0, len(raw), step):
            chunk = raw[index : index + step]
            mapped = cmap.get(chunk)
            if mapped is not None:
                decoded_parts.append(mapped)
                continue
            try:
                decoded_parts.append(chunk.decode("utf-8"))
            except UnicodeDecodeError:
                decoded_parts.append(chunk.decode("latin-1", errors="ignore"))
        return "".join(decoded_parts)

    for match in text_objects_pattern.finditer(data):
        block = match.group(1)
        for array_match in array_pattern.finditer(block):
            parts = hex_pattern.findall(array_match.group(1))
            if not parts:
                continue
            decoded = "".join(decode_hex_bytes(part) for part in parts)
            if decoded:
                texts.append(decoded)
        for single_match in single_pattern.finditer(block):
            decoded = decode_hex_bytes(single_match.group(1))
            if decoded:
                texts.append(decoded)
    return texts


def _extract_lines() -> list[str]:
    if not PDF_PATH.exists():
        raise _PDFParseError(f"Question source PDF not found at {PDF_PATH}")
    data = PDF_PATH.read_bytes()

    streams = list(_iter_pdf_streams(data))
    cmap = _build_cmap(streams)

    lines: list[str] = []
    for stream in streams:
        lines.extend(_decode_text_objects(stream, cmap))

    cleaned: list[str] = []
    for raw_line in lines:
        line = raw_line.replace("\xa0", " ")
        line = re.sub(r"<sup>(.*?)</sup>", lambda m: f"^{m.group(1)}", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        cleaned.append(line)
    return cleaned


_HEADINGS = {
    "100 Expert-Level Benchmark Questions for LLMs",
    "Logical Reasoning & Riddles",
    "Mathematical & Numerical Challenges",
    "Language & Word Puzzles",
    "Context Understanding & Coreference",
    "Pattern Recognition & Sequences",
    "Knowledge & Application",
    "Parsing & Miscellaneous",
}

_TRAILING_NOTES_PREFIX = "Each question above"


def _filter_lines(lines: Sequence[str]) -> list[str]:
    filtered: list[str] = []
    total = len(lines)
    for idx, line in enumerate(lines):
        if line in _HEADINGS:
            continue
        if line.startswith("Question") or line.startswith("Answer"):
            continue
        if line.startswith("[... omitted"):
            continue
        if line.startswith(_TRAILING_NOTES_PREFIX):
            break

        if line.isdigit():
            # Skip page markers like "1", "2" that sit between table sections.
            next_line = ""
            for j in range(idx + 1, total):
                candidate = lines[j].strip()
                if candidate:
                    next_line = candidate
                    break
            if next_line.startswith("Question") or next_line.startswith(_TRAILING_NOTES_PREFIX):
                continue
        filtered.append(line)
    return filtered


def _coalesce_questions(lines: Sequence[str]) -> list[Question]:
    questions: list[Question] = []
    i = 0
    total = len(lines)
    number_pattern = re.compile(r"^(\d{1,3})\.\s+(.*)$")

    while i < total:
        line = lines[i]
        match = number_pattern.match(line)
        if not match:
            i += 1
            continue

        number = int(match.group(1))
        question_parts: list[str] = []
        first_part = match.group(2).strip()
        if first_part:
            question_parts.append(first_part)
        i += 1

        buffer: list[str] = []
        while i < total:
            candidate = lines[i]
            if number_pattern.match(candidate):
                break
            buffer.append(candidate)
            i += 1

        if not buffer:
            raise _PDFParseError(f"Missing answer for question {number}")

        answer = buffer.pop().strip()
        question_parts.extend(part.strip() for part in buffer if part.strip())
        prompt = " ".join(question_parts).strip()
        questions.append(Question(number=number, prompt=prompt, answer=answer))

    if len(questions) != 100:
        raise _PDFParseError(f"Expected 100 questions, parsed {len(questions)}")

    return questions


@lru_cache(maxsize=1)
def load_questions() -> list[Question]:
    """Return the 100 expert-level questions and answers."""

    lines = _extract_lines()
    filtered = _filter_lines(lines)
    questions = _coalesce_questions(filtered)
    questions.sort(key=lambda q: q.number)
    return questions


__all__ = ["Question", "load_questions"]
