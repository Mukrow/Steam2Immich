import sqlite3

from steam2immich.upload_state import UploadState


def test_upload_state_initializes_empty_sqlite_schema(tmp_path) -> None:
    # A fresh state database should initialize tables and schema metadata.
    path = tmp_path / "upload_state.sqlite"

    state = UploadState(path)

    assert state.records == {}
    with sqlite3.connect(path) as connection:
        schema_version = connection.execute(
            "SELECT value FROM state_metadata WHERE key = 'schema_version'"
        ).fetchone()
        uploads_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'uploads'"
        ).fetchone()

    assert schema_version == ("1",)
    assert uploads_table == ("uploads",)


def test_upload_state_records_saves_and_reloads(tmp_path, candidate_factory) -> None:
    # A recorded upload should persist and be visible after reopening the database.
    path = tmp_path / "upload_state.sqlite"
    candidate = candidate_factory()

    state = UploadState(path)
    state.record(
        "device-asset-id",
        "asset-id",
        candidate,
        "Steam Screenshots",
        ["Steam"],
    )
    state.save()

    reloaded = UploadState(path)
    assert reloaded.has("device-asset-id")
    assert reloaded.records["device-asset-id"]["asset_id"] == "asset-id"
    assert reloaded.records["device-asset-id"]["chosen_path"] == str(candidate.chosen_path)
    assert reloaded.records["device-asset-id"]["album_name"] == "Steam Screenshots"
    assert reloaded.records["device-asset-id"]["tag_names"] == ["Steam"]


def test_upload_state_marks_album_and_tags_added_persistently(
    tmp_path, candidate_factory
) -> None:
    # Follow-up flags should update and survive a new UploadState instance.
    path = tmp_path / "upload_state.sqlite"
    state = UploadState(path)
    state.record("device-asset-id", "asset-id", candidate_factory())

    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    reloaded = UploadState(path)
    assert reloaded.records["device-asset-id"]["album_added"] is True
    assert reloaded.records["device-asset-id"]["tags_added"] is True


def test_upload_state_resets_followups_when_targets_change(
    tmp_path, candidate_factory
) -> None:
    # Target changes should mark only the affected follow-up as pending.
    path = tmp_path / "upload_state.sqlite"
    state = UploadState(path)
    state.record(
        "device-asset-id",
        "asset-id",
        candidate_factory(),
        "Old Album",
        ["Steam"],
    )
    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    state.prepare_followups("device-asset-id", "New Album", ["Steam", "Steam/App"])

    reloaded = UploadState(path)
    assert reloaded.needs_album("device-asset-id") is True
    assert reloaded.needs_tags("device-asset-id") is True
    assert reloaded.records["device-asset-id"]["album_name"] == "New Album"
    assert reloaded.records["device-asset-id"]["tag_names"] == ["Steam", "Steam/App"]


def test_upload_state_detects_complete_current_targets(tmp_path, candidate_factory) -> None:
    # Completion should depend on both status flags and current desired targets.
    state = UploadState(tmp_path / "upload_state.sqlite")
    state.record(
        "device-asset-id",
        "asset-id",
        candidate_factory(),
        "Steam Screenshots",
        ["Steam"],
    )
    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    assert state.is_complete("device-asset-id", "Steam Screenshots", ["Steam"]) is True
    assert state.is_complete("device-asset-id", "Other", ["Steam"]) is False


def test_upload_state_records_errors_persistently(tmp_path) -> None:
    # Non-fatal follow-up failures should be persisted for diagnosis and retry.
    path = tmp_path / "upload_state.sqlite"
    state = UploadState(path)

    state.record_error("device-asset-id", "album: boom")

    reloaded = UploadState(path)
    assert reloaded.records["device-asset-id"]["last_error"] == "album: boom"
    assert "last_attempt_at" in reloaded.records["device-asset-id"]


def test_upload_state_clears_error_when_followups_complete(
    tmp_path, candidate_factory
) -> None:
    # A record's previous error should disappear once all follow-ups are complete.
    state = UploadState(tmp_path / "upload_state.sqlite")
    state.record("device-asset-id", "asset-id", candidate_factory())
    state.record_error("device-asset-id", "tags: boom")

    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    assert state.records["device-asset-id"]["last_error"] is None
    assert state.records["device-asset-id"]["last_attempt_at"] is None
