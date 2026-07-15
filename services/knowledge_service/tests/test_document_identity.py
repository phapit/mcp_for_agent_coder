from document_identity import chunk_id, content_hash, document_id, source_key


def test_document_id_is_stable_and_scoped():
    assert document_id("docs/a.md", "ProjectA") == document_id("docs\\a.md", "projecta")
    assert document_id("docs/a.md", "ProjectA") != document_id("docs/a.md", "ProjectB")


def test_content_and_chunk_ids_change_when_content_changes():
    assert content_hash(b"v1") != content_hash(b"v2")
    assert chunk_id("doc", 0, "v1") != chunk_id("doc", 0, "v2")


def test_source_key_normalizes_path_separators():
    assert source_key("/docs//imported/a.md") == "docs/imported/a.md"

