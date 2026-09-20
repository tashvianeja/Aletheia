from __future__ import annotations

import unicodedata
from functools import lru_cache
from importlib.resources import files

# BERT uncased WordPiece, implemented here rather than pulled from `tokenizers` so the
# on-device encoder adds one wheel (onnxruntime) instead of two. Label text is short,
# so a pure-Python pass costs microseconds and never dominates the ONNX call.
UNK = "[UNK]"
CLS = "[CLS]"
SEP = "[SEP]"
PAD = "[PAD]"
MAX_CHARS_PER_WORD = 100


@lru_cache(maxsize=1)
def vocabulary() -> dict[str, int]:
    text = files("aletheia.data.models").joinpath("vocab.txt").read_text(encoding="utf-8")
    return {token: index for index, token in enumerate(text.split("\n")) if token}


def _is_punctuation(char: str) -> bool:
    code = ord(char)
    if (33 <= code <= 47) or (58 <= code <= 64) or (91 <= code <= 96) or (123 <= code <= 126):
        return True
    return unicodedata.category(char).startswith("P")


def _strip_accents(text: str) -> str:
    # Keeps "Teléfono" and "Telefono" on the same token path, which matters because form
    # labels arrive with whatever accents the site's author typed.
    return "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )


def basic_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    cleaned = "".join(
        " " if char in "\t\n\r" or unicodedata.category(char) in {"Zs", "Cc", "Cf"} else char
        for char in text
    )
    tokens: list[str] = []
    for chunk in cleaned.lower().split():
        chunk = _strip_accents(chunk)
        current = ""
        for char in chunk:
            if _is_punctuation(char):
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(char)
            else:
                current += char
        if current:
            tokens.append(current)
    return tokens


def wordpiece(token: str, vocab: dict[str, int]) -> list[str]:
    if len(token) > MAX_CHARS_PER_WORD:
        return [UNK]
    pieces: list[str] = []
    start = 0
    while start < len(token):
        end = len(token)
        found: str | None = None
        while start < end:
            candidate = token[start:end]
            if start > 0:
                candidate = "##" + candidate
            if candidate in vocab:
                found = candidate
                break
            end -= 1
        if found is None:
            return [UNK]
        pieces.append(found)
        start = end
    return pieces


def encode(text: str, max_length: int = 128) -> tuple[list[int], list[int]]:
    """Return (input_ids, attention_mask) for a single string."""
    vocab = vocabulary()
    pieces: list[str] = []
    for token in basic_tokens(text):
        pieces.extend(wordpiece(token, vocab))
        if len(pieces) >= max_length - 2:
            break
    pieces = pieces[: max_length - 2]
    ids = [vocab[CLS], *(vocab.get(piece, vocab[UNK]) for piece in pieces), vocab[SEP]]
    return ids, [1] * len(ids)


def encode_batch(
    texts: list[str], max_length: int = 128
) -> tuple[list[list[int]], list[list[int]]]:
    encoded = [encode(text, max_length) for text in texts]
    width = max((len(ids) for ids, _ in encoded), default=1)
    pad = vocabulary()[PAD]
    ids = [row + [pad] * (width - len(row)) for row, _ in encoded]
    mask = [row + [0] * (width - len(row)) for _, row in encoded]
    return ids, mask
