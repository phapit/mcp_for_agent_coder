import manifest


def test_hash_changes_with_content():
    assert manifest.compute_hash(b"abc") != manifest.compute_hash(b"abcd")
    assert manifest.compute_hash(b"abc") == manifest.compute_hash(b"abc")


def test_is_unchanged_tracks_recorded_hash():
    m = {}
    h = manifest.compute_hash(b"content")

    assert not manifest.is_unchanged(m, "file.xlsx", h)

    manifest.record_success(m, "file.xlsx", h, "out.md", 2)
    assert manifest.is_unchanged(m, "file.xlsx", h)

    other_hash = manifest.compute_hash(b"changed content")
    assert not manifest.is_unchanged(m, "file.xlsx", other_hash)


def test_save_and_load_manifest_roundtrip(tmp_path):
    out_dir = str(tmp_path)
    m = {"a.xlsx": {"hash": "x", "output_md": "a.md", "image_count": 1}}

    manifest.save_manifest(out_dir, m)
    loaded = manifest.load_manifest(out_dir)

    assert loaded == m


def test_load_manifest_returns_empty_dict_when_missing(tmp_path):
    assert manifest.load_manifest(str(tmp_path / "does_not_exist")) == {}
