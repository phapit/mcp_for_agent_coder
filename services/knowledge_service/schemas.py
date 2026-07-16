"""Pydantic request models + validators dùng chung cho mọi endpoint.

Thuần túy dữ liệu — không import state/client nào của service.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

REPORT_FORMATS = ("briefing-doc", "study-guide", "blog-post", "custom")


def validate_storage_name(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty.")
    if any(char in value for char in ("/", "\\", "..")):
        raise ValueError(f"{label} must not contain path separators or '..'.")
    return value


def validate_output_name(value: str) -> None:
    if "/" in value or "\\" in value or not value.endswith(".md"):
        raise ValueError("output_name must be a plain .md filename.")


def validate_auth_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("notebooklm_auth_name must not be empty.")
    if any(char in value for char in ("/", "\\", "..")):
        raise ValueError("notebooklm_auth_name must not contain path separators or '..'.")
    if not value.endswith(".json"):
        raise ValueError("notebooklm_auth_name must end with .json.")
    return value


class SearchFilters(BaseModel):
    project: str | None = None
    environment: str | None = None
    document_type: str | None = None
    version: int | None = None


class SearchQuery(BaseModel):
    query: str
    limit: int = 3
    filters: SearchFilters | None = None


class AnswerQuery(BaseModel):
    question: str
    limit: int = 3
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online)
    filters: SearchFilters | None = None
    session_id: str | None = None  # bật hội thoại nhiều lượt khi client gửi kèm
    prompt_version: str | None = None  # mặc định theo PROMPT_VERSION (env)


class ClientRequestCreate(BaseModel):
    title: str
    description: str
    request_type: str = "feature"  # feature | bug
    project: str | None = None  # lọc đặc tả theo dự án nếu chỉ định
    requester: str | None = None
    limit: int = 8  # số trích đoạn đặc tả tối đa trong gói ngữ cảnh


class IngestRequest(BaseModel):
    force: bool = False  # re-embed even when content_hash is unchanged (also retries dead-lettered docs)
    prune: bool = True  # delete vectors whose source file no longer exists
    background: bool = False  # run in a worker thread; poll /ingest/status for the result


class IngestExcelRequest(BaseModel):
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online) cho bước refine
    force: bool = False


class IngestSpreadsheetRequest(BaseModel):
    project_name: str
    notebook_env: str
    spreadsheet_id: str
    output_name: str = "spreadsheet.md"
    language: str | None = None  # mã ngôn ngữ đầu ra khi generate report (vd: vi, en, ja); None = mặc định của NotebookLM

    @field_validator("project_name", "notebook_env")
    @classmethod
    def validate_scope_name(cls, value: str) -> str:
        return validate_storage_name(value, "scope")

    @field_validator("output_name")
    @classmethod
    def validate_output_name(cls, value: str) -> str:
        validate_output_name(value)
        return value


class NotebookReportRequest(BaseModel):
    project_name: str
    notebook_env: str
    prompt: str  # yêu cầu tự do, vd: "Mô tả chi tiết logic hoạt động của button A"
    output_name: str = "custom-report.md"
    format: str = "custom"  # briefing-doc | study-guide | blog-post | custom
    append: str | None = None  # chỉ áp dụng khi format != custom
    language: str | None = None  # mã ngôn ngữ đầu ra (vd: vi, en, ja); None = mặc định NotebookLM

    @field_validator("project_name", "notebook_env")
    @classmethod
    def validate_scope_name(cls, value: str) -> str:
        return validate_storage_name(value, "scope")

    @field_validator("output_name")
    @classmethod
    def validate_output_name(cls, value: str) -> str:
        validate_output_name(value)
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt must not be empty.")
        if len(value) > 1024:
            raise ValueError(f"prompt must not exceed 1024 characters (got {len(value)}).")
        return value

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if value not in REPORT_FORMATS:
            raise ValueError(f"format must be one of {list(REPORT_FORMATS)}.")
        return value


class ProjectNotebookConfigUpsertRequest(BaseModel):
    project_name: str
    notebook_env: str
    notebook_id: str
    notebooklm_auth_name: str

    @field_validator("project_name", "notebook_env")
    @classmethod
    def validate_scope_name(cls, value: str) -> str:
        return validate_storage_name(value, "scope")

    @field_validator("notebook_id")
    @classmethod
    def validate_notebook_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("notebook_id must not be empty.")
        return value

    @field_validator("notebooklm_auth_name")
    @classmethod
    def validate_auth_name(cls, value: str) -> str:
        return validate_auth_name(value)
