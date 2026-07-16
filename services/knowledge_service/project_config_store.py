from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class ProjectConfigError(RuntimeError):
    """Raised when project NotebookLM config cannot be resolved."""


@dataclass(frozen=True)
class ProjectNotebookConfig:
    project_name: str
    notebook_env: str
    notebook_id: str
    notebooklm_auth_name: str
    created_at: str | None = None
    updated_at: str | None = None


class CollectionProtocol(Protocol):
    def create_index(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def find_one(self, filter: dict[str, Any], projection: dict[str, int] | None = None) -> dict[str, Any] | None:
        ...

    def find(self, filter: dict[str, Any], projection: dict[str, int] | None = None) -> Any:
        ...

    def update_one(self, filter: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> Any:
        ...

    def delete_one(self, filter: dict[str, Any]) -> Any:
        ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _serialize(document: dict[str, Any] | None) -> ProjectNotebookConfig | None:
    if not document:
        return None
    return ProjectNotebookConfig(
        project_name=document["project_name"],
        notebook_env=document["notebook_env"],
        notebook_id=document["notebook_id"],
        notebooklm_auth_name=document["notebooklm_auth_name"],
        created_at=document.get("created_at"),
        updated_at=document.get("updated_at"),
    )


class ProjectConfigStore:
    def __init__(self, collection: CollectionProtocol) -> None:
        self.collection = collection
        self.collection.create_index(
            [("project_name", 1), ("notebook_env", 1)],
            unique=True,
            name="project_env_unique_idx",
        )

    def upsert_config(
        self,
        project_name: str,
        notebook_env: str,
        notebook_id: str,
        notebooklm_auth_name: str,
    ) -> ProjectNotebookConfig:
        existing = self.collection.find_one(
            {"project_name": project_name, "notebook_env": notebook_env},
            {"_id": 0, "created_at": 1},
        )
        created_at = existing.get("created_at") if existing else _utc_now_iso()
        updated_at = _utc_now_iso()
        self.collection.update_one(
            {"project_name": project_name, "notebook_env": notebook_env},
            {
                "$set": {
                    "project_name": project_name,
                    "notebook_env": notebook_env,
                    "notebook_id": notebook_id,
                    "notebooklm_auth_name": notebooklm_auth_name,
                    "updated_at": updated_at,
                },
                "$setOnInsert": {"created_at": created_at},
            },
            upsert=True,
        )
        return ProjectNotebookConfig(
            project_name=project_name,
            notebook_env=notebook_env,
            notebook_id=notebook_id,
            notebooklm_auth_name=notebooklm_auth_name,
            created_at=created_at,
            updated_at=updated_at,
        )

    def get_config(self, project_name: str, notebook_env: str) -> ProjectNotebookConfig:
        config = _serialize(
            self.collection.find_one(
                {"project_name": project_name, "notebook_env": notebook_env},
                {"_id": 0},
            )
        )
        if not config:
            raise ProjectConfigError(
                f"Config not found for project_name='{project_name}' and notebook_env='{notebook_env}'."
            )
        return config

    def list_configs(self, project_name: str) -> list[ProjectNotebookConfig]:
        cursor = self.collection.find({"project_name": project_name}, {"_id": 0})
        configs = []
        for document in cursor:
            config = _serialize(document)
            if config is not None:
                configs.append(config)
        return configs

    def list_all_configs(self) -> list[ProjectNotebookConfig]:
        cursor = self.collection.find({}, {"_id": 0})
        configs = []
        for document in cursor:
            config = _serialize(document)
            if config is not None:
                configs.append(config)
        configs.sort(key=lambda config: (config.project_name, config.notebook_env))
        return configs

    def delete_config(self, project_name: str, notebook_env: str) -> bool:
        result = self.collection.delete_one({"project_name": project_name, "notebook_env": notebook_env})
        return bool(getattr(result, "deleted_count", 0))
