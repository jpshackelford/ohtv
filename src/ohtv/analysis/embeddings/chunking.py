"""Text chunking utilities for embedding large content."""

from .text_builders import TextChunk

CHUNK_SIZE = 1000  # Target tokens per chunk
CHUNK_OVERLAP = 100  # Overlap between chunks


def estimate_tokens(text: str) -> int:
    """Rough estimate of token count for text.

    Uses 1.3 words per token as a rough estimate.
    """
    return int(len(text.split()) * 1.3)


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split text into overlapping chunks.

    Args:
        text: Text to chunk
        chunk_size: Target tokens per chunk
        overlap: Token overlap between chunks

    Returns:
        List of TextChunk objects
    """
    if not text or not text.strip():
        return []

    estimated_tokens = estimate_tokens(text)
    if estimated_tokens <= chunk_size:
        return [TextChunk(text=text, chunk_index=0, estimated_tokens=estimated_tokens)]

    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk: list[str] = []
    current_tokens = 0
    chunk_index = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        if para_tokens > chunk_size:
            if current_chunk:
                chunk_text_str = "\n\n".join(current_chunk)
                chunks.append(TextChunk(
                    text=chunk_text_str,
                    chunk_index=chunk_index,
                    estimated_tokens=current_tokens,
                ))
                chunk_index += 1
                current_chunk = []
                current_tokens = 0

            sentences = para.replace(". ", ".\n").split("\n")
            for sentence in sentences:
                sent_tokens = estimate_tokens(sentence)
                if current_tokens + sent_tokens > chunk_size and current_chunk:
                    chunk_text_str = " ".join(current_chunk)
                    chunks.append(TextChunk(
                        text=chunk_text_str,
                        chunk_index=chunk_index,
                        estimated_tokens=current_tokens,
                    ))
                    chunk_index += 1
                    overlap_text = " ".join(current_chunk[-2:]) if len(current_chunk) > 2 else ""
                    current_chunk = [overlap_text] if overlap_text else []
                    current_tokens = estimate_tokens(overlap_text) if overlap_text else 0

                current_chunk.append(sentence)
                current_tokens += sent_tokens

        elif current_tokens + para_tokens > chunk_size and current_chunk:
            chunk_text_str = "\n\n".join(current_chunk)
            chunks.append(TextChunk(
                text=chunk_text_str,
                chunk_index=chunk_index,
                estimated_tokens=current_tokens,
            ))
            chunk_index += 1

            overlap_para = current_chunk[-1] if current_chunk else ""
            current_chunk = [overlap_para, para] if overlap_para else [para]
            current_tokens = estimate_tokens(overlap_para) + para_tokens if overlap_para else para_tokens
        else:
            current_chunk.append(para)
            current_tokens += para_tokens

    if current_chunk:
        chunk_text_str = "\n\n".join(current_chunk)
        chunks.append(TextChunk(
            text=chunk_text_str,
            chunk_index=chunk_index,
            estimated_tokens=current_tokens,
        ))

    return chunks
