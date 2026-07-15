import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class NotebookLMError(RuntimeError):
    """Raised when a NotebookLM CLI operation fails."""


class NotebookLMRateLimitError(NotebookLMError):
    """Raised when NotebookLM throttles an RPC request."""


@dataclass(frozen=True)
class NotebookLMResult:
    output_md: str
    source_id: str | None
    artifact_id: str | None


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


class NotebookLMService:
    def __init__(
        self,
        notebook_id: str | None = None,
        output_dir: str | None = None,
        auth_json: str | None = None,
        cli: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.notebook_id = notebook_id or os.getenv("NOTEBOOKLM_NOTEBOOK_ID", "")
        self.output_dir = Path(output_dir or os.getenv("NOTEBOOKLM_OUTPUT_DIR", "/app/project_data/docs/imported"))
        self.auth_json = auth_json or os.getenv("NOTEBOOKLM_AUTH_JSON", "")
        self.cli = cli or os.getenv("NOTEBOOKLM_CLI", "notebooklm")
        self.runner = runner or _default_runner

    def _run(self, args: Sequence[str], *, json_output: bool = False) -> dict:
        command = [self.cli, *args]
        if json_output:
            command.append("--json")
        previous_auth_json = os.environ.get("NOTEBOOKLM_AUTH_JSON")
        try:
            if self.auth_json:
                os.environ["NOTEBOOKLM_AUTH_JSON"] = self.auth_json
            result = self.runner(command)
        finally:
            if self.auth_json:
                if previous_auth_json is None:
                    os.environ.pop("NOTEBOOKLM_AUTH_JSON", None)
                else:
                    os.environ["NOTEBOOKLM_AUTH_JSON"] = previous_auth_json
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            if "RateLimitError" in detail or "rate limit" in detail.lower():
                raise NotebookLMRateLimitError(detail or "NotebookLM rate limit reached.")
            raise NotebookLMError(detail or f"NotebookLM command failed: {' '.join(command)}")
        if not json_output:
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise NotebookLMError("NotebookLM returned invalid JSON.") from exc

    @staticmethod
    def _items(payload: dict, *keys: str) -> list[dict]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _find_source(self, spreadsheet_id: str) -> str | None:
        payload = self._run(["source", "list", "-n", self.notebook_id], json_output=True)
        needle = spreadsheet_id.lower()
        for item in self._items(payload, "sources", "items", "data"):
            serialized = json.dumps(item, ensure_ascii=False).lower()
            if needle in serialized:
                source_id = item.get("id") or item.get("source_id")
                if source_id:
                    return str(source_id)
        return None

    def _find_report(self, spreadsheet_id: str, output_name: str) -> str | None:
        payload = self._run(
            ["artifact", "list", "--type", "report", "-n", self.notebook_id],
            json_output=True,
        )
        needle_values = (spreadsheet_id.lower(), output_name.lower())
        for item in self._items(payload, "artifacts", "items", "data"):
            serialized = json.dumps(item, ensure_ascii=False).lower()
            if any(needle in serialized for needle in needle_values):
                artifact_id = item.get("id") or item.get("artifact_id")
                if artifact_id:
                    return str(artifact_id)
        return None

    def process_spreadsheet(self, spreadsheet_id: str, output_name: str) -> NotebookLMResult:
        if not self.notebook_id:
            raise NotebookLMError("NOTEBOOKLM_NOTEBOOK_ID is not configured.")
        if not self.auth_json:
            raise NotebookLMError("NOTEBOOKLM_AUTH_JSON is not configured.")
        if not spreadsheet_id.strip():
            raise NotebookLMError("spreadsheet_id must not be empty.")

        source_id = self._find_source(spreadsheet_id)
        if not source_id:
            source = self._run(
                [
                    "source",
                    "add-drive",
                    spreadsheet_id,
                    output_name,
                    "--mime-type",
                    "google-sheets",
                    "-n",
                    self.notebook_id,
                ],
                json_output=True,
            )
            source_id = source.get("source", {}).get("id")
        if source_id:
            self._run(["source", "wait", source_id, "--timeout", "120", "-n", self.notebook_id])

        artifact_id = self._find_report(spreadsheet_id, output_name)
        if not artifact_id:
            artifact = self._run(
                ["generate", "report", "--format", "briefing-doc", "-n", self.notebook_id, "--no-wait"],
                json_output=True,
            )
            artifact_id = (
                artifact.get("artifact", {}).get("id")
                or artifact.get("artifact_id")
                or artifact.get("task_id")
                or artifact.get("task", {}).get("id")
            )
        if not artifact_id:
            raise NotebookLMError("NotebookLM report response did not include an artifact id.")

        self._run(["artifact", "wait", artifact_id, "--timeout", "120", "-n", self.notebook_id])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / output_name
        self._run(
            ["download", "report", str(output_path), "-a", artifact_id, "-n", self.notebook_id]
        )
        return NotebookLMResult(str(output_path), source_id, artifact_id)
