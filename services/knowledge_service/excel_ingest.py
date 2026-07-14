import logging
import os

import openpyxl

import vision

logger = logging.getLogger(__name__)

CONTEXT_WINDOW = 2  # số dòng lân cận (trên/dưới) dùng làm ngữ cảnh khi caption ảnh

REFINE_PROMPT = (
    "Bạn là trợ lý chuẩn hóa tài liệu. Dưới đây là nội dung trích xuất từ một file Excel đặc tả, "
    "đã được ghép thành Markdown thô (bao gồm cả link ảnh dạng ![caption](đường dẫn)).\n\n"
    "Hãy định dạng lại cho rõ ràng, dễ đọc (dùng heading, bảng, danh sách khi phù hợp). "
    "TUYỆT ĐỐI KHÔNG được thêm, xóa, hay chỉnh sửa dữ liệu/số liệu, KHÔNG được xóa hay đổi bất kỳ "
    "link ảnh Markdown nào (giữ nguyên y hệt cú pháp ![...](...)). Chỉ được thay đổi cách trình bày.\n\n"
    "Nội dung thô:\n{raw}"
)


def extract_workbook(path: str):
    """Đọc cell text theo sheet + trích ảnh nhúng kèm vị trí neo (row gần nhất)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = {}
    images = []

    for ws in wb.worksheets:
        rows_text = []
        for row in ws.iter_rows():
            cells = [str(c.value) for c in row if c.value is not None]
            if cells:
                rows_text.append((row[0].row, " | ".join(cells)))
        sheets[ws.title] = rows_text

        for img in getattr(ws, "_images", []):
            anchor_row = None
            try:
                anchor_row = img.anchor._from.row + 1
            except Exception:
                logger.warning(f"Could not resolve anchor row for an image in sheet '{ws.title}'")

            fmt = (getattr(img, "format", None) or "png").lower()
            if fmt == "jpeg":
                fmt = "jpg"

            images.append(
                {
                    "sheet": ws.title,
                    "anchor_row": anchor_row,
                    "ext": fmt,
                    "data": img._data(),
                }
            )

    return sheets, images


def _context_for_image(sheets: dict, sheet_name: str, anchor_row: int) -> str:
    if anchor_row is None:
        return ""
    rows = sheets.get(sheet_name, [])
    nearby = [text for (idx, text) in rows if abs(idx - anchor_row) <= CONTEXT_WINDOW]
    return "\n".join(nearby)


def caption_images(sheets: dict, images: list) -> list:
    """Gọi vision LLM cho từng ảnh, trả về list ảnh kèm caption. Ném lỗi nếu provider không khả dụng."""
    captioned = []
    for img in images:
        context = _context_for_image(sheets, img["sheet"], img["anchor_row"])
        caption = vision.caption_image(img["data"], img["ext"], context)
        captioned.append({**img, "caption": caption})
    return captioned


def save_images(captioned_images: list, images_dir: str) -> list:
    """Ghi ảnh ra đĩa, trả về list kèm đường dẫn tương đối (dùng trong markdown)."""
    os.makedirs(images_dir, exist_ok=True)
    result = []
    for i, img in enumerate(captioned_images, start=1):
        filename = f"img{i}.{img['ext']}"
        with open(os.path.join(images_dir, filename), "wb") as f:
            f.write(img["data"])
        result.append({**img, "rel_path": f"images/{filename}"})
    return result


def build_intermediate(sheets: dict, images_with_path: list) -> str:
    """Ghép text sheet + ảnh (caption + link) theo đúng vị trí neo thành markdown thô."""
    images_by_sheet = {}
    for img in images_with_path:
        images_by_sheet.setdefault(img["sheet"], []).append(img)

    parts = []
    for sheet_name, rows in sheets.items():
        parts.append(f"## {sheet_name}\n")
        sheet_images = images_by_sheet.get(sheet_name, [])
        unanchored = [img for img in sheet_images if img["anchor_row"] is None]

        for row_idx, text in rows:
            parts.append(text)
            for img in sheet_images:
                if img["anchor_row"] == row_idx:
                    parts.append(f"\n![{img['caption']}]({img['rel_path']})\n")

        for img in unanchored:
            parts.append(f"\n![{img['caption']}]({img['rel_path']})\n")

        parts.append("")

    return "\n".join(parts)


def refine_with_llm(raw_markdown: str, client, model: str) -> str:
    """Làm sạch format bằng text LLM hiện có — không được thay đổi dữ liệu/link ảnh."""
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": REFINE_PROMPT.format(raw=raw_markdown)}],
    )
    return completion.choices[0].message.content


def process_excel_file(path: str, output_dir: str, refine_client, refine_model: str) -> dict:
    """Chạy toàn bộ pipeline cho 1 file Excel, ghi output_dir/<stem>.md + output_dir/images/*."""
    stem = os.path.splitext(os.path.basename(path))[0]
    file_output_dir = os.path.join(output_dir, stem)
    images_dir = os.path.join(file_output_dir, "images")

    sheets, images = extract_workbook(path)
    captioned = caption_images(sheets, images)
    images_with_path = save_images(captioned, images_dir)
    raw_markdown = build_intermediate(sheets, images_with_path)
    final_markdown = refine_with_llm(raw_markdown, refine_client, refine_model)

    md_path = os.path.join(file_output_dir, f"{stem}.md")
    os.makedirs(file_output_dir, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(final_markdown)

    return {"output_md": md_path, "image_count": len(images_with_path)}
