import os
from types import SimpleNamespace

import excel_ingest


def test_extract_workbook_reads_rows_and_anchored_image(sample_xlsx_path):
    sheets, images = excel_ingest.extract_workbook(sample_xlsx_path)

    assert "Sheet1" in sheets
    row_texts = [text for (_, text) in sheets["Sheet1"]]
    assert any("REQ-1" in text for text in row_texts)
    assert any("REQ-2" in text for text in row_texts)

    assert len(images) == 1
    assert images[0]["sheet"] == "Sheet1"
    assert images[0]["anchor_row"] == 2
    assert images[0]["ext"] == "png"
    assert images[0]["data"]


def test_build_intermediate_places_image_after_its_anchor_row():
    sheets = {
        "Sheet1": [
            (1, "ID | Mo_ta"),
            (2, "REQ-1 | Doi mau nut dang nhap"),
            (3, "REQ-2 | Them truong ghi chu"),
        ]
    }
    images = [
        {
            "sheet": "Sheet1",
            "anchor_row": 2,
            "ext": "png",
            "caption": "Anh minh hoa nut dang nhap mau xanh",
            "rel_path": "images/img1.png",
        }
    ]

    md = excel_ingest.build_intermediate(sheets, images)

    assert "![Anh minh hoa nut dang nhap mau xanh](images/img1.png)" in md
    assert md.index("REQ-1") < md.index("images/img1.png") < md.index("REQ-2")


def test_build_intermediate_appends_unanchored_image_at_sheet_end():
    sheets = {"Sheet1": [(1, "ID | Mo_ta"), (2, "REQ-1 | Doi mau nut")]}
    images = [
        {"sheet": "Sheet1", "anchor_row": None, "ext": "png", "caption": "Anh chung", "rel_path": "images/img1.png"}
    ]

    md = excel_ingest.build_intermediate(sheets, images)

    assert "![Anh chung](images/img1.png)" in md
    assert md.index("REQ-1") < md.index("images/img1.png")


def test_process_excel_file_writes_markdown_and_images(monkeypatch, sample_xlsx_path, tmp_path):
    monkeypatch.setattr(excel_ingest.vision, "caption_image", lambda data, ext, context: "caption gia lap")

    def fake_create(model, messages):
        raw = messages[0]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"REFINED:\n{raw}"))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    output_dir = str(tmp_path / "output")
    result = excel_ingest.process_excel_file(sample_xlsx_path, output_dir, fake_client, "fake-model")

    assert os.path.exists(result["output_md"])
    assert result["image_count"] == 1

    with open(result["output_md"], "r", encoding="utf-8") as f:
        content = f.read()
    assert content.startswith("REFINED:")
    assert "images/img1.png" in content

    image_path = os.path.join(os.path.dirname(result["output_md"]), "images", "img1.png")
    assert os.path.exists(image_path)
