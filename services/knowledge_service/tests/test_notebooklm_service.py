import json
import subprocess

import pytest

from notebooklm_service import GROUNDING_PREAMBLE, NotebookLMError, NotebookLMService


def test_process_spreadsheet_runs_source_report_and_download(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"sources": []}), "")
        if command[1:4] == ["artifact", "list", "--type"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifacts": []}), "")
        if command[1:3] == ["source", "add-drive"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"source": {"id": "src-1"}}), "")
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-1"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{\"cookies\":[]}", runner=runner).process_spreadsheet(
        "spreadsheet-id", "sheet.md"
    )

    assert result.source_id == "src-1"
    assert result.artifact_id == "art-1"
    assert result.output_md == str(tmp_path / "sheet.md")
    assert calls[1][0:4] == ["notebooklm", "source", "add-drive", "spreadsheet-id"]
    assert calls[1][4:8] == ["sheet.md", "--mime-type", "google-sheets", "-n"]
    assert calls[-2][1:3] == ["artifact", "wait"]
    assert calls[-1][1:3] == ["download", "report"]


def test_process_spreadsheet_waits_for_task_id_response(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"sources": []}), "")
        if command[1:4] == ["artifact", "list", "--type"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifacts": []}), "")
        if command[1:3] == ["source", "add-drive"]:
            payload = {"source": {"id": "src-1"}}
        elif command[1:3] == ["generate", "report"]:
            payload = {"task_id": "task-1"}
        else:
            payload = None
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) if payload is not None else "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{\"cookies\":[]}", runner=runner).process_spreadsheet(
        "spreadsheet-id", "sheet.md"
    )

    assert result.artifact_id == "task-1"
    assert calls[-2][1:4] == ["artifact", "wait", "task-1"]


def test_process_spreadsheet_reuses_existing_source_and_artifact(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"sources": [{"id": "src-existing", "drive_id": "sheet-1"}]}), "")
        if command[1:4] == ["artifact", "list", "--type"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifacts": [{"id": "art-existing", "title": "sheet.md"}]}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).process_spreadsheet("sheet-1", "sheet.md")

    assert result.source_id == "src-existing"
    assert result.artifact_id == "art-existing"
    assert result.report_reused is True
    assert not any(call[1:3] == ["source", "add-drive"] for call in calls)
    assert not any(call[1:3] == ["generate", "report"] for call in calls)


def test_process_spreadsheet_passes_language_to_generate(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"sources": []}), "")
        if command[1:4] == ["artifact", "list", "--type"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifacts": []}), "")
        if command[1:3] == ["source", "add-drive"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"source": {"id": "src-1"}}), "")
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-1"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).process_spreadsheet(
        "spreadsheet-id", "sheet.md", language="vi"
    )

    generate_call = next(c for c in calls if c[1:3] == ["generate", "report"])
    assert generate_call[generate_call.index("--language") + 1] == "vi"
    assert result.report_reused is False


def test_process_spreadsheet_omits_language_flag_when_none(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"sources": []}), "")
        if command[1:4] == ["artifact", "list", "--type"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifacts": []}), "")
        if command[1:3] == ["source", "add-drive"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"source": {"id": "src-1"}}), "")
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-1"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).process_spreadsheet(
        "spreadsheet-id", "sheet.md"
    )

    generate_call = next(c for c in calls if c[1:3] == ["generate", "report"])
    assert "--language" not in generate_call


def test_generate_custom_report_runs_generate_wait_download(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-9"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).generate_custom_report(
        "Mô tả chi tiết logic hoạt động của button A", "button-a.md"
    )

    assert result.artifact_id == "art-9"
    assert result.output_md == str(tmp_path / "button-a.md")
    generate_call = next(c for c in calls if c[1:3] == ["generate", "report"])
    assert generate_call[3].startswith(GROUNDING_PREAMBLE)
    assert generate_call[3].endswith("Yêu cầu: Mô tả chi tiết logic hoạt động của button A")
    assert generate_call[generate_call.index("--format") + 1] == "custom"
    assert calls[-2][1:3] == ["artifact", "wait"]
    assert calls[-1][1:3] == ["download", "report"]


def test_generate_custom_report_passes_language_and_format(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-9"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).generate_custom_report(
        "Tóm tắt cho stakeholder", "summary.md", report_format="briefing-doc", language="vi", append="Ngắn gọn"
    )

    generate_call = next(c for c in calls if c[1:3] == ["generate", "report"])
    assert generate_call[generate_call.index("--format") + 1] == "briefing-doc"
    assert generate_call[generate_call.index("--language") + 1] == "vi"
    assert generate_call[generate_call.index("--append") + 1] == "Ngắn gọn"


def test_generate_custom_report_ignores_append_when_format_custom(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-9"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    NotebookLMService("nb-1", str(tmp_path), auth_json="{}", runner=runner).generate_custom_report(
        "Câu hỏi tự do", "free.md", report_format="custom", append="Không nên có tác dụng"
    )

    generate_call = next(c for c in calls if c[1:3] == ["generate", "report"])
    assert "--append" not in generate_call


def test_generate_custom_report_requires_prompt(tmp_path):
    with pytest.raises(NotebookLMError, match="prompt"):
        NotebookLMService("nb-1", str(tmp_path), auth_json="{}").generate_custom_report("  ", "out.md")


def test_generate_custom_report_requires_notebook_id():
    with pytest.raises(NotebookLMError, match="NOTEBOOKLM_NOTEBOOK_ID"):
        NotebookLMService(auth_json="{\"cookies\":[]}").generate_custom_report("prompt", "out.md")


def test_process_spreadsheet_requires_notebook_id():
    with pytest.raises(NotebookLMError, match="NOTEBOOKLM_NOTEBOOK_ID"):
        NotebookLMService(auth_json="{\"cookies\":[]}").process_spreadsheet("https://example.com/sheet", "sheet.md")


def test_process_spreadsheet_requires_auth_json():
    with pytest.raises(NotebookLMError, match="NOTEBOOKLM_AUTH_JSON"):
        NotebookLMService("nb-1").process_spreadsheet("https://example.com/sheet", "sheet.md")


def test_process_spreadsheet_rejects_empty_id():
    with pytest.raises(NotebookLMError, match="spreadsheet_id"):
        NotebookLMService("nb-1", auth_json="{\"cookies\":[]}").process_spreadsheet("  ", "sheet.md")
