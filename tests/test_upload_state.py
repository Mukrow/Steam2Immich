from steam2immich.upload_state import UploadState


def test_upload_state_records_saves_and_reloads(tmp_path, candidate_factory) -> None:
    # A recorded upload should persist and be visible after reloading state from disk.
    path = tmp_path / "upload_state.json"
    candidate = candidate_factory()

    state = UploadState(path)
    state.record("device-asset-id", "asset-id", candidate)
    state.save()

    reloaded = UploadState(path)
    assert reloaded.has("device-asset-id")
    assert reloaded.records["device-asset-id"]["asset_id"] == "asset-id"
    assert reloaded.records["device-asset-id"]["chosen_path"] == str(candidate.chosen_path)
    assert "prepared_path" not in reloaded.records["device-asset-id"]


def test_upload_state_marks_album_and_tags_added(tmp_path, candidate_factory) -> None:
    # Follow-up flags should update an existing upload record in memory.
    state = UploadState(tmp_path / "upload_state.json")
    state.record("device-asset-id", "asset-id", candidate_factory())

    state.mark_album_added("device-asset-id")
    state.mark_tags_added("device-asset-id")

    assert state.records["device-asset-id"]["album_added"] is True
    assert state.records["device-asset-id"]["tags_added"] is True


def test_upload_state_ignores_malformed_json(tmp_path) -> None:
    # Invalid state JSON should load as an empty state instead of raising.
    path = tmp_path / "upload_state.json"
    path.write_text("{", encoding="utf-8")

    state = UploadState(path)

    assert state.records == {}
