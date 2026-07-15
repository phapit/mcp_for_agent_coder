from project_config_store import ProjectConfigError, ProjectConfigStore


class FakeDeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self):
        self.documents = {}
        self.indexes = []

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    def find_one(self, filter, projection=None):
        document = self.documents.get((filter["project_name"], filter["notebook_env"]))
        if document is None:
            return None
        return _project(document, projection)

    def find(self, filter, projection=None):
        items = []
        for document in self.documents.values():
            if document["project_name"] == filter["project_name"]:
                items.append(_project(document, projection))
        return items

    def update_one(self, filter, update, upsert=False):
        key = (filter["project_name"], filter["notebook_env"])
        current = self.documents.get(key, {})
        current.update(update.get("$setOnInsert", {}))
        current.update(update.get("$set", {}))
        self.documents[key] = current

    def delete_one(self, filter):
        key = (filter["project_name"], filter["notebook_env"])
        deleted = 1 if key in self.documents else 0
        self.documents.pop(key, None)
        return FakeDeleteResult(deleted)


def _project(document, projection):
    if projection is None:
        return dict(document)
    return {key: value for key, value in document.items() if projection.get(key, 1)}


def test_upsert_and_get_config():
    store = ProjectConfigStore(FakeCollection())

    saved = store.upsert_config("project-a", "env-a", "nb-1", "team-a.json")
    loaded = store.get_config("project-a", "env-a")

    assert saved.project_name == "project-a"
    assert loaded.notebook_id == "nb-1"
    assert loaded.notebooklm_auth_name == "team-a.json"


def test_list_configs_by_project():
    store = ProjectConfigStore(FakeCollection())
    store.upsert_config("project-a", "env-a", "nb-1", "team-a.json")
    store.upsert_config("project-a", "env-b", "nb-2", "team-b.json")
    store.upsert_config("project-b", "env-a", "nb-3", "team-c.json")

    configs = store.list_configs("project-a")

    assert len(configs) == 2
    assert sorted(config.notebook_env for config in configs) == ["env-a", "env-b"]


def test_get_config_raises_when_missing():
    store = ProjectConfigStore(FakeCollection())

    try:
        store.get_config("project-a", "missing")
    except ProjectConfigError as exc:
        assert "Config not found" in str(exc)
    else:
        raise AssertionError("Expected ProjectConfigError")


def test_delete_config_returns_status():
    store = ProjectConfigStore(FakeCollection())
    store.upsert_config("project-a", "env-a", "nb-1", "team-a.json")

    assert store.delete_config("project-a", "env-a") is True
    assert store.delete_config("project-a", "env-a") is False
