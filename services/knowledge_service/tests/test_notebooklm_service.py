import json
import subprocess

import pytest

from notebooklm_service import NotebookLMError, NotebookLMService


def test_process_spreadsheet_runs_source_report_and_download(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "add"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"source": {"id": "src-1"}}), "")
        if command[1:3] == ["generate", "report"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"artifact": {"id": "art-1"}}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{\"cookies\":[]}", runner=runner).process_spreadsheet(
        "https://docs.google.com/spreadsheets/d/example", "sheet.md"
    )

    assert result.source_id == "src-1"
    assert result.artifact_id == "art-1"
    assert result.output_md == str(tmp_path / "sheet.md")
    assert calls[0][0:4] == ["notebooklm", "source", "add", "https://docs.google.com/spreadsheets/d/example"]
    assert calls[-2][1:3] == ["artifact", "wait"]
    assert calls[-1][1:3] == ["download", "report"]


def test_process_spreadsheet_waits_for_task_id_response(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        if command[1:3] == ["source", "add"]:
            payload = {"source": {"id": "src-1"}}
        elif command[1:3] == ["generate", "report"]:
            payload = {"task_id": "task-1"}
        else:
            payload = None
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) if payload is not None else "", "")

    result = NotebookLMService("nb-1", str(tmp_path), auth_json="{\"cookies\":[]}", runner=runner).process_spreadsheet(
        "https://docs.google.com/spreadsheets/d/example", "sheet.md"
    )

    assert result.artifact_id == "task-1"
    assert calls[-2][1:4] == ["artifact", "wait", "task-1"]


def test_process_spreadsheet_requires_notebook_id():
    with pytest.raises(NotebookLMError, match="NOTEBOOKLM_NOTEBOOK_ID"):
        NotebookLMService(auth_json="{\"cookies\":[]}").process_spreadsheet("https://example.com/sheet", "sheet.md")


def test_process_spreadsheet_requires_auth_json():
    with pytest.raises(NotebookLMError, match="NOTEBOOKLM_AUTH_JSON"):
        NotebookLMService("nb-1").process_spreadsheet("https://example.com/sheet", "sheet.md")


def test_process_spreadsheet_rejects_non_http_url():
    with pytest.raises(NotebookLMError, match=r"HTTP\(S\) URL"):
        NotebookLMService("nb-1", auth_json="{\"cookies\":[]}").process_spreadsheet("file:///sheet", "sheet.md")
