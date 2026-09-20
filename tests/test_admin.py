"""Tests for the admin panel's taxonomy editing.

The thing these protect is simple and severe: `data/taxonomy.json` is what every
student form reads, so a bad write takes the whole product down. Most of these
check that a rejected edit changes nothing at all.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import taxonomy_loader
import taxonomy_store as store
from taxonomy_store import StoreError


@pytest.fixture()
def taxonomy(tmp_path, monkeypatch):
    """A scratch copy of the real taxonomy, so tests never touch the live file."""
    original = Path(__file__).resolve().parent.parent / "data" / "taxonomy.json"
    scratch = tmp_path / "taxonomy.json"
    shutil.copy2(original, scratch)

    monkeypatch.setattr(store, "TAXONOMY_PATH", scratch)
    monkeypatch.setattr(store, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(taxonomy_loader, "TAXONOMY_PATH", scratch)
    taxonomy_loader.load_taxonomy(force=True)
    yield scratch
    taxonomy_loader._taxonomy = None


def on_disk(path):
    return json.loads(path.read_text())


def digest(path):
    return json.dumps(on_disk(path), sort_keys=True)


# ------------------------------------------------------------------ create


def test_create_reaches_the_file_and_the_loader(taxonomy):
    skill = store.create_skill("Kafka", "technical", "Event streaming")
    vc = store.create_vc("api-development", "Stream events", "Publish domain events",
                         technical=[skill], transferable=["structured-thinking"])

    assert skill in on_disk(taxonomy)["skills"]
    loaded = taxonomy_loader.load_taxonomy(force=True)
    assert loaded.vcs[vc]["name"] == "Stream events"
    assert skill in taxonomy_loader.vc_skill_ids(loaded.vcs[vc])


def test_ids_are_readable_and_unique(taxonomy):
    first = store.create_skill("Message queues deluxe", "technical")
    second = store.create_skill("Message queues deluxe", "technical")
    assert first == "message-queues-deluxe"
    assert second != first and second.startswith("message-queues-deluxe")


def test_a_value_construct_id_is_prefixed(taxonomy):
    assert store.create_vc("api-development", "Retire an endpoint").startswith("vc-")


# ------------------------------------------------------ nothing broken ever


def test_an_invalid_skill_type_is_refused_and_the_file_is_untouched(taxonomy):
    vc = store.create_vc("api-development", "Temporary")
    before = digest(taxonomy)

    with pytest.raises(StoreError, match="transferable skill"):
        store.set_vc_skills(vc, ["structured-thinking"], [])

    assert digest(taxonomy) == before


def test_an_unknown_skill_is_refused_and_the_file_is_untouched(taxonomy):
    vc = store.create_vc("api-development", "Temporary")
    before = digest(taxonomy)

    with pytest.raises(StoreError, match="No skill with id"):
        store.set_vc_skills(vc, ["does-not-exist"], [])

    assert digest(taxonomy) == before


def test_a_skill_still_attached_cannot_be_deleted(taxonomy):
    before = digest(taxonomy)
    with pytest.raises(StoreError, match="still attached"):
        store.delete("skill", "sql")
    assert digest(taxonomy) == before


def test_editing_something_that_does_not_exist_is_refused(taxonomy):
    with pytest.raises(StoreError, match="No vc with id"):
        store.update("vc", "vc-imaginary", {"name": "Nope"})


# -------------------------------------------------------------- id safety


def test_renaming_never_changes_the_id(taxonomy):
    vc = store.create_vc("api-development", "Old name")
    store.update("vc", vc, {"name": "Completely different name"})

    loaded = taxonomy_loader.load_taxonomy(force=True)
    assert loaded.vcs[vc]["name"] == "Completely different name"
    assert vc in loaded.vcs


def test_changing_an_id_outright_is_refused(taxonomy):
    vc = store.create_vc("api-development", "Stable")
    with pytest.raises(StoreError, match="can't be changed"):
        store.update("vc", vc, {"id": "something-else"})


def test_a_skills_type_cannot_be_edited(taxonomy):
    """Flipping a type would silently invalidate every VC already using it."""
    skill = store.create_skill("Typed once", "technical")
    store.update("skill", skill, {"type": "transferable", "name": "Typed once"})
    assert on_disk(taxonomy)["skills"][skill]["type"] == "technical"


# ---------------------------------------------------------------- archiving


def test_archiving_hides_from_students_but_keeps_the_name(taxonomy):
    vc = store.create_vc("api-development", "Soon to retire")
    store.archive("vc", vc, True)

    loaded = taxonomy_loader.load_taxonomy(force=True)
    public = {v["id"] for r in loaded.public_dict()["roles"]
              for s in r["business_services"] for v in s["value_constructs"]}

    assert vc not in public, "an archived job must not be offered to a student"
    assert loaded.vcs[vc]["name"] == "Soon to retire", "old reports still need its name"


def test_archiving_a_service_hides_its_children_too(taxonomy):
    store.archive("service", "third-party-integrations", True)
    loaded = taxonomy_loader.load_taxonomy(force=True)
    public = {s["id"] for r in loaded.public_dict()["roles"] for s in r["business_services"]}
    assert "third-party-integrations" not in public
    assert loaded.active_services_of_role("backend-development")


def test_restore_puts_it_back(taxonomy):
    store.archive("service", "third-party-integrations", True)
    store.archive("service", "third-party-integrations", False)
    loaded = taxonomy_loader.load_taxonomy(force=True)
    public = {s["id"] for r in loaded.public_dict()["roles"] for s in r["business_services"]}
    assert "third-party-integrations" in public


def test_an_archived_skill_is_not_offered_but_still_resolves(taxonomy):
    store.archive("skill", "sql", True)
    loaded = taxonomy_loader.load_taxonomy(force=True)
    assert "sql" not in loaded.public_dict()["skills"]
    assert loaded.skill_name("sql") == "SQL"


# ------------------------------------------------------------- housekeeping


def test_an_unattached_skill_warns_rather_than_raising(taxonomy):
    """An admin creates a skill before attaching it. That must not be fatal."""
    store.create_skill("Floating", "technical")
    loaded = taxonomy_loader.load_taxonomy(force=True)
    assert any("floating" in warning for warning in loaded.warnings)


def test_every_write_bumps_the_version_and_leaves_a_backup(taxonomy):
    start = on_disk(taxonomy)["version"]
    store.create_skill("Versioned", "technical")
    store.create_skill("Versioned again", "technical")

    assert on_disk(taxonomy)["version"] == start + 2
    assert list((taxonomy.parent / "backups").glob("taxonomy-*.json"))


def test_usage_counts_come_back_empty_for_an_untouched_database(tmp_path):
    counts = db.taxonomy_usage(tmp_path / "probe.db")
    assert counts == {"roles": {}, "services": {}, "vcs": {}, "skills": {}}


def test_usage_counts_find_what_a_student_referenced(tmp_path):
    path = tmp_path / "probe.db"
    db.init_db(path)
    db.save_profile(
        {"identity": {"full_name": "A", "email": "a@b.edu"},
         "selections": {"role_id": "backend-development",
                        "service_ids": ["api-development"],
                        "vc_ids": ["vc-design-rest-apis"]},
         "ratings": {"sql": 4}},
        {"taxonomy_version": 1, "role_fit": {"score": 50}, "verdict": {"code": "early"}},
        path)

    counts = db.taxonomy_usage(path)
    assert counts["roles"]["backend-development"] == 1
    assert counts["services"]["api-development"] == 1
    assert counts["vcs"]["vc-design-rest-apis"] == 1
    assert counts["skills"]["sql"] == 1


# ------------------------------------------------------------------- auth


@pytest.fixture()
def admin_client(monkeypatch):
    import admin_app
    monkeypatch.setenv("CAARYA_ADMIN_USER", "boss")
    monkeypatch.setenv("CAARYA_ADMIN_PASSWORD", "s3cret-pass")
    monkeypatch.delenv("CAARYA_ADMIN_REQUIRE_AUTH", raising=False)
    return admin_app.app.test_client()


def _basic(user, password):
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.mark.parametrize("path", ["/", "/api/profiles", "/api/admin/taxonomy", "/students/1"])
def test_admin_requires_credentials(admin_client, path):
    response = admin_client.get(path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


def test_admin_rejects_wrong_credentials(admin_client):
    assert admin_client.get("/api/profiles", headers=_basic("boss", "nope")).status_code == 401
    assert admin_client.get("/api/profiles", headers=_basic("intruder", "s3cret-pass")).status_code == 401


def test_admin_accepts_correct_credentials(admin_client):
    assert admin_client.get("/api/profiles", headers=_basic("boss", "s3cret-pass")).status_code == 200


def test_admin_writes_are_gated_too(admin_client):
    assert admin_client.post("/api/admin/roles", json={"name": "x"}).status_code == 401


def test_admin_is_disabled_when_deployed_without_a_password(monkeypatch):
    import admin_app
    monkeypatch.delenv("CAARYA_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("CAARYA_ADMIN_REQUIRE_AUTH", "1")
    assert admin_app.app.test_client().get("/api/profiles").status_code == 503


def test_student_app_needs_no_credentials(admin_client):
    import app as student
    client = student.app.test_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
