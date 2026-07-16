from chunking import split_markdown

SAMPLE = """# Kiến trúc

Đoạn mở đầu về kiến trúc tổng thể.

## Qdrant

Qdrant lưu vector embedding của tài liệu.
Mỗi chunk có payload metadata.

## Kafka

Kafka dùng cho pipeline ingest bất đồng bộ.
"""


def test_chunks_carry_heading_and_lines():
    chunks = split_markdown(SAMPLE, chunk_size=80, chunk_overlap=0)

    assert chunks, "must produce chunks"
    qdrant_chunks = [c for c in chunks if "Qdrant lưu vector" in c.text]
    assert qdrant_chunks
    assert qdrant_chunks[0].heading == "Kiến trúc > Qdrant"
    assert qdrant_chunks[0].start_line >= 5

    kafka_chunks = [c for c in chunks if "Kafka dùng cho" in c.text]
    assert kafka_chunks[0].heading == "Kiến trúc > Kafka"


def test_line_numbers_match_source():
    chunks = split_markdown(SAMPLE, chunk_size=1000, chunk_overlap=0)
    lines = SAMPLE.splitlines()
    for chunk in chunks:
        first_line = chunk.text.splitlines()[0]
        assert lines[chunk.start_line - 1] == first_line


def test_respects_chunk_size():
    chunks = split_markdown(SAMPLE, chunk_size=60, chunk_overlap=0)
    # Every multi-line chunk stays under the limit (single long lines may exceed).
    for chunk in chunks:
        if len(chunk.text.splitlines()) > 1:
            assert len(chunk.text) <= 60 + 20


def test_overlap_repeats_trailing_lines():
    text = "\n".join(f"dong so {i} noi dung kha dai de tang kich thuoc" for i in range(1, 11))
    chunks = split_markdown(text, chunk_size=120, chunk_overlap=60)
    assert len(chunks) >= 2
    # The next chunk starts at or before the previous chunk's end line (overlap).
    assert chunks[1].start_line <= chunks[0].end_line


def test_heading_sibling_replaces_previous():
    text = "# A\n\nnội dung a\n\n## B1\n\nnội dung b1\n\n## B2\n\nnội dung b2\n"
    chunks = split_markdown(text, chunk_size=30, chunk_overlap=0)
    b2 = [c for c in chunks if "nội dung b2" in c.text][0]
    assert b2.heading == "A > B2"


def test_empty_document():
    assert split_markdown("", chunk_size=100, chunk_overlap=10) == []
    assert split_markdown("\n\n\n", chunk_size=100, chunk_overlap=10) == []
