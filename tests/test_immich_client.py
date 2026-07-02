from datetime import datetime

import pytest
from conftest import FakeResponse, FakeSession

from steam2immich.immich_client import (
    ImmichClient,
    ImmichClientError,
    album_name_for_candidate,
    build_device_asset_id,
    tag_names_for_candidate,
)


def _client_with_session(session: FakeSession) -> ImmichClient:
    client = object.__new__(ImmichClient)
    client.base_url = "https://immich.example/api"
    client.timeout = 5
    client.session = session
    client._album_cache = {}
    client._tag_cache = {}
    return client


def test_immich_helpers_build_album_tags_and_stable_asset_id(candidate_factory) -> None:
    # Helper functions should produce predictable album, tag, and local identity values.
    candidate = candidate_factory(timestamp=datetime(2025, 1, 1, 1, 1, 1))

    assert album_name_for_candidate(candidate, "per-game", "Steam Screenshots", "Steam -") == (
        "Steam - Baldur's Gate 3"
    )
    assert tag_names_for_candidate(candidate) == [
        "Steam",
        "Steam/Baldur's Gate 3",
        "Steam App/1086940",
    ]
    assert build_device_asset_id(candidate) == build_device_asset_id(candidate)


def test_get_or_create_album_reuses_existing_album() -> None:
    # Existing Immich albums should be reused without creating a duplicate.
    session = FakeSession(
        {"get": [FakeResponse([{"albumName": "Steam", "id": "album-id"}])], "post": [], "put": []}
    )
    client = _client_with_session(session)

    assert client.get_or_create_album("Steam") == "album-id"
    assert [call[0] for call in session.calls] == ["get"]


def test_get_or_create_tag_creates_missing_tag() -> None:
    # Missing Immich tags should be created and then cached by name.
    session = FakeSession(
        {
            "get": [FakeResponse([])],
            "post": [FakeResponse({"id": "tag-id"})],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_or_create_tag("Steam") == "tag-id"
    assert client.get_or_create_tag("Steam") == "tag-id"
    assert [call[0] for call in session.calls] == ["get", "post"]


def test_require_v3_accepts_major_version() -> None:
    # Version validation should allow Immich v3 before upload orchestration begins.
    session = FakeSession(
        {
            "get": [FakeResponse({"major": 3, "minor": 0, "patch": 0})],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    client.require_v3()

    assert session.calls == [
        ("get", "https://immich.example/api/server/version", {"timeout": 5})
    ]


def test_require_v3_accepts_version_string() -> None:
    # Version validation should tolerate alternate version response shapes.
    session = FakeSession(
        {"get": [FakeResponse({"version": "v3.0.0"})], "post": [], "put": []}
    )
    client = _client_with_session(session)

    client.require_v3()


def test_require_v3_rejects_v2() -> None:
    # Older Immich servers should fail before any upload work is attempted.
    session = FakeSession({"get": [FakeResponse({"major": 2})], "post": [], "put": []})
    client = _client_with_session(session)

    with pytest.raises(ImmichClientError, match="requires Immich v3"):
        client.require_v3()


def test_require_v3_rejects_malformed_payload() -> None:
    # Unknown version shapes should fail closed.
    session = FakeSession(
        {"get": [FakeResponse({"server": "immich"})], "post": [], "put": []}
    )
    client = _client_with_session(session)

    with pytest.raises(ImmichClientError, match="requires Immich v3"):
        client.require_v3()


def test_require_v3_rejects_http_error() -> None:
    # Version endpoint failures should stop the sync early.
    session = FakeSession(
        {
            "get": [FakeResponse({}, status_code=500, text="boom")],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    with pytest.raises(ImmichClientError, match="HTTP 500"):
        client.require_v3()


def test_upload_asset_uses_original_source_read_only(candidate_factory) -> None:
    # Uploads should read the chosen source file directly instead of a prepared copy.
    candidate = candidate_factory(timestamp=datetime(2025, 1, 1, 1, 1, 1))
    session = FakeSession(
        {
            "get": [],
            "post": [FakeResponse({"id": "asset-id", "status": "created"})],
            "put": [],
        }
    )
    client = _client_with_session(session)

    result = client.upload_asset(candidate, "legacy-device-asset-id")

    assert result.asset_id == "asset-id"
    assert result.duplicate is False
    method, url, kwargs = session.calls[0]
    uploaded_name, uploaded_file = kwargs["files"]["assetData"]
    assert method == "post"
    assert url == "https://immich.example/api/assets"
    assert kwargs["data"]["filename"] == candidate.chosen_path.name
    assert "fileCreatedAt" in kwargs["data"]
    assert "fileModifiedAt" in kwargs["data"]
    assert "deviceId" not in kwargs["data"]
    assert "deviceAssetId" not in kwargs["data"]
    assert uploaded_name == candidate.chosen_path.name
    assert uploaded_file.name == str(candidate.chosen_path)
    assert uploaded_file.mode == "rb"


def test_upload_asset_marks_duplicate(candidate_factory) -> None:
    # Immich v3 reports duplicates from the upload response.
    candidate = candidate_factory()
    session = FakeSession(
        {
            "get": [],
            "post": [FakeResponse({"id": "asset-id", "status": "duplicate"})],
            "put": [],
        }
    )
    client = _client_with_session(session)

    result = client.upload_asset(candidate, "legacy-device-asset-id")

    assert result.asset_id == "asset-id"
    assert result.duplicate is True
