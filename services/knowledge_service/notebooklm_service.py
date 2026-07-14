import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class NotebookLMError(RuntimeError):
    """Raised when a NotebookLM CLI operation fails."""


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
        cli: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.notebook_id = notebook_id or os.getenv("NOTEBOOKLM_NOTEBOOK_ID", "")
        self.output_dir = Path(output_dir or os.getenv("NOTEBOOKLM_OUTPUT_DIR", "/app/project_data/docs/imported"))
        self.cli = cli or os.getenv("NOTEBOOKLM_CLI", "notebooklm")
        self.runner = runner or _default_runner

    def _run(self, args: Sequence[str], *, json_output: bool = False) -> dict:
        command = [self.cli, *args]
        if json_output:
            command.append("--json")
        result = self.runner(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise NotebookLMError(detail or f"NotebookLM command failed: {' '.join(command)}")
        if not json_output:
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise NotebookLMError("NotebookLM returned invalid JSON.") from exc

    def process_spreadsheet(self, spreadsheet_url: str, output_name: str) -> NotebookLMResult:
        if not self.notebook_id:
            raise NotebookLMError("NOTEBOOKLM_NOTEBOOK_ID is not configured.")
        if not spreadsheet_url.startswith(("https://", "http://")):
            raise NotebookLMError("spreadsheet_url must be an HTTP(S) URL.")

        source = self._run(
            ["source", "add", spreadsheet_url, "-n", self.notebook_id],
            json_output=True,
        )
        source_id = source.get("source", {}).get("id")
        if source_id:
            self._run(["source", "wait", source_id, "-n", self.notebook_id])

        artifact = self._run(
            ["generate", "report", "--format", "briefing-doc", "-n", self.notebook_id],
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

        self._run(["artifact", "wait", artifact_id, "-n", self.notebook_id])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / output_name
        self._run(
            ["download", "report", str(output_path), "-a", artifact_id, "-n", self.notebook_id]
        )
        return NotebookLMResult(str(output_path), source_id, artifact_id)
