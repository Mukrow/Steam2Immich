import json

from steam2immich.upload_state import UploadState


def test_upload_state_records_saves_and_reloads(tmp_path, candidate_factory) -> None:
    # A recorded upload should persist and be visible after reloading state from disk.
    path = tmp_path / "upload_state.json"
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
    assert "prepared_path" not in reloaded.records["device-asset-id"]


def test_upload_state_marks_album_and_tags_added(tmp_path, candidate_factory) -> None:
    # Follow-up flags should update an existing upload record in memory.
    state = UploadState(tmp_path / "upload_state.json")
    state.record("device-asset-id", "asset-id", candidate_factory())

    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    assert state.records["device-asset-id"]["album_added"] is True
    assert state.records["device-asset-id"]["tags_added"] is True


def test_upload_state_resets_followups_when_targets_change(tmp_path, candidate_factory) -> None:
    # Target changes should mark only the affected follow-up as pending.
    state = UploadState(tmp_path / "upload_state.json")
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

    assert state.needs_album("device-asset-id") is True
    assert state.needs_tags("device-asset-id") is True
    assert state.records["device-asset-id"]["album_name"] == "New Album"
    assert state.records["device-asset-id"]["tag_names"] == ["Steam", "Steam/App"]


def test_upload_state_detects_complete_current_targets(tmp_path, candidate_factory) -> None:
    # Completion should depend on both status flags and current desired targets.
    state = UploadState(tmp_path / "upload_state.json")
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


def test_upload_state_records_errors(tmp_path) -> None:
    # Non-fatal follow-up failures should be persisted for diagnosis and retry.
    state = UploadState(tmp_path / "upload_state.json")

    state.record_error("device-asset-id", "album: boom")

    assert state.records["device-asset-id"]["last_error"] == "album: boom"
    assert "last_attempt_at" in state.records["device-asset-id"]


def test_upload_state_loads_old_format_records(tmp_path, candidate_factory) -> None:
    # Existing upload_state.json files without target fields should remain usable.
    path = tmp_path / "upload_state.json"
    candidate = candidate_factory()
    path.write_text(
        json.dumps(
            {
                "device-asset-id": {
                    "asset_id": "asset-id",
                    "chosen_path": str(candidate.chosen_path),
                    "album_added": True,
                    "tags_added": True,
                }
            }
        ),
        encoding="utf-8",
    )

    state = UploadState(path)
    state.prepare_followups("device-asset-id", "Steam Screenshots", ["Steam"])

    assert state.get_asset_id("device-asset-id") == "asset-id"
    assert state.needs_album("device-asset-id") is True
    assert state.needs_tags("device-asset-id") is True


def test_upload_state_ignores_malformed_json(tmp_path) -> None:
    # Invalid state JSON should load as an empty state instead of raising.
    path = tmp_path / "upload_state.json"
    path.write_text("{", encoding="utf-8")

    state = UploadState(path)

    assert state.records == {}
