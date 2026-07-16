"""Export tài liệu: Excel → Markdown, NotebookLM (spreadsheet, custom report)
và CRUD cấu hình project notebook.

State (clients, config) sống ở main.py; truy cập qua `main.<attr>` tại thời
điểm request để test có thể monkeypatch trên main. Các thao tác dùng chung
với domain khác (auto-ingest, chọn chat client) gọi qua main để giữ một điểm
điều phối duy nhất.
"""

from __future__ import annotations

import glob
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

import excel_ingest
import manifest as manifest_store
import vision
from notebooklm_service import NotebookLMError, NotebookLMRateLimitError, NotebookLMService
from project_config_store import ProjectConfigError, ProjectConfigStore
from schemas import (
    IngestExcelRequest,
    IngestSpreadsheetRequest,
    NotebookReportRequest,
    ProjectNotebookConfigUpsertRequest,
    validate_auth_name,
    validate_storage_name,
)

import main

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_vision_available():
    if vision.VISION_PROVIDER == "anthropic" and not vision.anthropic_vision_client:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured (required for VISION_PROVIDER=anthropic).",
        )
    if vision.VISION_PROVIDER == "openai" and not vision.openai_vision_client:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured (required for VISION_PROVIDER=openai).",
        )


def _require_project_config_store() -> ProjectConfigStore:
    if main.project_config_store is None:
        raise HTTPException(status_code=503, detail="MongoDB project config store is not available.")
    return main.project_config_store


def _load_notebook_auth_json(auth_name: str) -> str:
    auth_name = validate_auth_name(auth_name)
    auth_path = Path(main.NOTEBOOKLM_AUTH_DIR) / auth_name
    if not auth_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"NotebookLM auth file '{auth_name}' was not found in auth directory.",
        )
    return auth_path.read_text(encoding="utf-8")


def _project_output_dir(project_name: str) -> str:
    return str(Path(main.NOTEBOOKLM_OUTPUT_DIR) / project_name)


@router.post("/ingest-excel")
def ingest_excel(request: IngestExcelRequest):
    """
    Quét EXCEL_SOURCE_DIR, convert từng file .xlsx chưa xử lý (hoặc đã đổi nội dung) thành
    Markdown trong EXCEL_OUTPUT_DIR, dùng vision LLM để caption ảnh nhúng và text LLM để làm sạch
    format cuối cùng.
    """
    _check_vision_available()
    client, model = main._select_chat_client(request.use_online_model)

    files = glob.glob(os.path.join(main.EXCEL_SOURCE_DIR, "*.xlsx"))
    if not files:
        raise HTTPException(status_code=404, detail=f"No .xlsx files found in '{main.EXCEL_SOURCE_DIR}'.")

    manifest = manifest_store.load_manifest(main.EXCEL_OUTPUT_DIR)
    processed, skipped, failed = [], [], []

    for path in files:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = f.read()
        content_hash = manifest_store.compute_hash(content)

        if not request.force and manifest_store.is_unchanged(manifest, name, content_hash):
            skipped.append(name)
            continue

        try:
            result = excel_ingest.process_excel_file(path, main.EXCEL_OUTPUT_DIR, client, model)
            manifest_store.record_success(manifest, name, content_hash, result["output_md"], result["image_count"])
            manifest_store.save_manifest(main.EXCEL_OUTPUT_DIR, manifest)
            processed.append({"file": name, **result})
        except Exception as e:
            logger.error(f"Failed to process '{name}': {e}", exc_info=True)
            failed.append({"file": name, "error": str(e)})

    auto_ingest = main._trigger_auto_ingest("excel_export") if processed else {"status": "skipped"}
    return {"processed": processed, "skipped": skipped, "failed": failed, "auto_ingest": auto_ingest}


@router.post("/ingest-excel/upload")
async def ingest_excel_upload(use_online_model: int = 0, file: UploadFile = File(...)):
    """Upload 1 file .xlsx ad-hoc và xử lý ngay (không qua manifest skip)."""
    content = await file.read(main.MAX_UPLOAD_BYTES + 1)
    if len(content) > main.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds the {main.MAX_UPLOAD_SIZE_MB} MB limit.",
        )

    _check_vision_available()
    client, model = main._select_chat_client(use_online_model)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = excel_ingest.process_excel_file(tmp_path, main.EXCEL_OUTPUT_DIR, client, model)
    except Exception as e:
        logger.error(f"Failed to process uploaded file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {e}")
    finally:
        os.remove(tmp_path)

    manifest = manifest_store.load_manifest(main.EXCEL_OUTPUT_DIR)
    content_hash = manifest_store.compute_hash(content)
    manifest_store.record_success(manifest, file.filename, content_hash, result["output_md"], result["image_count"])
    manifest_store.save_manifest(main.EXCEL_OUTPUT_DIR, manifest)

    return {"file": file.filename, **result, "auto_ingest": main._trigger_auto_ingest("excel_upload")}


@router.post("/ingest-spreadsheet")
def ingest_spreadsheet(request: IngestSpreadsheetRequest):
    """Resolve project NotebookLM config from MongoDB and export Markdown."""
    store = _require_project_config_store()
    try:
        config = store.get_config(request.project_name, request.notebook_env)
    except ProjectConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    auth_json = _load_notebook_auth_json(config.notebooklm_auth_name)
    output_dir = _project_output_dir(request.project_name)
    service = NotebookLMService(
        notebook_id=config.notebook_id,
        output_dir=output_dir,
        auth_json=auth_json,
    )
    try:
        result = service.process_spreadsheet(
            request.spreadsheet_id, request.output_name, language=request.language
        )
    except NotebookLMRateLimitError as exc:
        logger.warning("NotebookLM rate limit; job can be resumed without creating a duplicate: %s", exc)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotebookLMError as exc:
        logger.error("NotebookLM spreadsheet ingestion failed: %s", exc)
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    manifest = manifest_store.load_manifest(output_dir)
    manifest_store.record_success(
        manifest,
        request.spreadsheet_id,
        manifest_store.compute_hash(request.spreadsheet_id.encode("utf-8")),
        result.output_md,
        0,
        project_name=request.project_name,
        notebook_env=request.notebook_env,
        notebook_id=service.notebook_id,
        notebooklm_auth_name=config.notebooklm_auth_name,
        source_id=result.source_id,
        artifact_id=result.artifact_id,
        spreadsheet_id=request.spreadsheet_id,
    )
    manifest_store.save_manifest(output_dir, manifest)

    return {
        "project_name": request.project_name,
        "notebook_env": request.notebook_env,
        "spreadsheet_id": request.spreadsheet_id,
        "notebook_id": service.notebook_id,
        "source_id": result.source_id,
        "artifact_id": result.artifact_id,
        "output_md": result.output_md,
        "language": request.language,
        "report_reused": result.report_reused,
        "auto_ingest": main._trigger_auto_ingest("notebooklm_export"),
    }


@router.post("/notebook-reports")
def generate_notebook_report(request: NotebookReportRequest):
    """Tạo tài liệu theo yêu cầu tự do của người dùng (prompt) từ các source
    đã có sẵn trong notebook của project — vd: "Mô tả chi tiết logic hoạt động
    của button A". Không thêm source mới; luôn generate report mới (không tái
    dùng report cũ vì mỗi prompt có thể cho nội dung khác nhau)."""
    store = _require_project_config_store()
    try:
        config = store.get_config(request.project_name, request.notebook_env)
    except ProjectConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    auth_json = _load_notebook_auth_json(config.notebooklm_auth_name)
    output_dir = _project_output_dir(request.project_name)
    service = NotebookLMService(
        notebook_id=config.notebook_id,
        output_dir=output_dir,
        auth_json=auth_json,
    )
    try:
        result = service.generate_custom_report(
            request.prompt,
            request.output_name,
            report_format=request.format,
            language=request.language,
            append=request.append,
        )
    except NotebookLMRateLimitError as exc:
        logger.warning("NotebookLM rate limit; can be retried without creating a duplicate: %s", exc)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotebookLMError as exc:
        logger.error("NotebookLM custom report generation failed: %s", exc)
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    manifest = manifest_store.load_manifest(output_dir)
    manifest_store.record_success(
        manifest,
        request.output_name,
        manifest_store.compute_hash(request.prompt.encode("utf-8")),
        result.output_md,
        0,
        project_name=request.project_name,
        notebook_env=request.notebook_env,
        notebook_id=service.notebook_id,
        notebooklm_auth_name=config.notebooklm_auth_name,
        artifact_id=result.artifact_id,
        prompt=request.prompt,
        format=request.format,
    )
    manifest_store.save_manifest(output_dir, manifest)

    return {
        "project_name": request.project_name,
        "notebook_env": request.notebook_env,
        "notebook_id": service.notebook_id,
        "artifact_id": result.artifact_id,
        "output_md": result.output_md,
        "format": request.format,
        "language": request.language,
        "auto_ingest": main._trigger_auto_ingest("notebooklm_custom_report"),
    }


@router.post("/project-notebook-configs")
def upsert_project_notebook_config(request: ProjectNotebookConfigUpsertRequest):
    store = _require_project_config_store()
    _load_notebook_auth_json(request.notebooklm_auth_name)
    config = store.upsert_config(
        request.project_name,
        request.notebook_env,
        request.notebook_id,
        request.notebooklm_auth_name,
    )
    return config.__dict__


@router.get("/project-notebook-configs")
def list_all_project_notebook_configs():
    store = _require_project_config_store()
    grouped: dict[str, list[dict]] = {}
    for config in store.list_all_configs():
        grouped.setdefault(config.project_name, []).append(config.__dict__)
    return [
        {"project_name": project_name, "config_count": len(configs), "configs": configs}
        for project_name, configs in grouped.items()
    ]


@router.get("/project-notebook-configs/{project_name}")
def list_project_notebook_configs(project_name: str):
    store = _require_project_config_store()
    try:
        project_name = validate_storage_name(project_name, "project_name")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [config.__dict__ for config in store.list_configs(project_name)]


@router.get("/project-notebook-configs/{project_name}/{notebook_env}")
def get_project_notebook_config(project_name: str, notebook_env: str):
    store = _require_project_config_store()
    try:
        project_name = validate_storage_name(project_name, "project_name")
        notebook_env = validate_storage_name(notebook_env, "notebook_env")
        config = store.get_config(project_name, notebook_env)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return config.__dict__


@router.put("/project-notebook-configs/{project_name}/{notebook_env}")
def update_project_notebook_config(
    project_name: str,
    notebook_env: str,
    request: ProjectNotebookConfigUpsertRequest,
):
    store = _require_project_config_store()
    try:
        project_name = validate_storage_name(project_name, "project_name")
        notebook_env = validate_storage_name(notebook_env, "notebook_env")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.project_name != project_name or request.notebook_env != notebook_env:
        raise HTTPException(
            status_code=422,
            detail="Path project_name/notebook_env must match request body.",
        )
    _load_notebook_auth_json(request.notebooklm_auth_name)
    config = store.upsert_config(
        project_name,
        notebook_env,
        request.notebook_id,
        request.notebooklm_auth_name,
    )
    return config.__dict__


@router.delete("/project-notebook-configs/{project_name}/{notebook_env}")
def delete_project_notebook_config(project_name: str, notebook_env: str):
    store = _require_project_config_store()
    try:
        project_name = validate_storage_name(project_name, "project_name")
        notebook_env = validate_storage_name(notebook_env, "notebook_env")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deleted = store.delete_config(project_name, notebook_env)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Config not found for project_name='{project_name}' and notebook_env='{notebook_env}'.",
        )
    return {"deleted": True, "project_name": project_name, "notebook_env": notebook_env}
