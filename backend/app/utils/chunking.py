import re

# Easy-to-change chunking settings (characters; ~4 chars per token, so 2000 chars ≈ 500 tokens).
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of at most `chunk_size` characters.

    Paragraphs are kept together where possible; oversized paragraphs are split at
    sentence, then word boundaries. Each chunk starts with the tail of the previous one.
    """
    if overlap < 0 or chunk_size <= overlap + 2:
        raise ValueError("chunk_size must be larger than overlap + 2")
    text = (text or "").strip()
    if not text:
        return []

    # Units are small enough that (overlap tail + unit) still fits in chunk_size.
    unit_limit = chunk_size - overlap - 2
    units = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if paragraph:
            units.extend(_split_long(paragraph, unit_limit))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + 2 + len(unit) <= chunk_size:
            current += "\n\n" + unit
        else:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            current = f"{tail}\n\n{unit}" if tail else unit
    if current.strip():
        chunks.append(current)
    return chunks


def _overlap_tail(chunk: str, overlap: int) -> str:
    if overlap == 0:
        return ""
    tail = chunk[-overlap:]
    # Don't start the overlap in the middle of a word.
    if len(chunk) > overlap and not chunk[-overlap - 1].isspace():
        match = re.search(r"\s", tail)
        if match:
            tail = tail[match.end():]
    return tail.strip()


def _split_long(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    pieces, current = [], ""
    for atom in _atoms(paragraph, limit):
        if not current:
            current = atom
        elif len(current) + 1 + len(atom) <= limit:
            current += " " + atom
        else:
            pieces.append(current)
            current = atom
    if current:
        pieces.append(current)
    return pieces


def _atoms(paragraph: str, limit: int):
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        if len(sentence) <= limit:
            yield sentence
        else:
            for word in sentence.split():
                for i in range(0, len(word), limit):
                    yield word[i:i + limit]
