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
    client._album_membership_cache = {}
    client._tag_cache = {}
    client._tag_cache_loaded = False
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


def test_get_asset_returns_asset_payload() -> None:
    session = FakeSession(
        {
            "get": [FakeResponse({"id": "asset-id", "tags": []})],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_asset("asset-id") == {"id": "asset-id", "tags": []}
    assert session.calls == [
        ("get", "https://immich.example/api/assets/asset-id", {"timeout": 5})
    ]


def test_get_asset_returns_none_for_missing_asset() -> None:
    session = FakeSession(
        {
            "get": [FakeResponse({"message": "not found"}, status_code=404)],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_asset("asset-id") is None


def test_get_asset_returns_none_for_immich_missing_asset_400() -> None:
    session = FakeSession(
        {
            "get": [
                FakeResponse(
                    {"message": "Not found or no asset.read access"},
                    status_code=400,
                    text='{"message":"Not found or no asset.read access"}',
                )
            ],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_asset("asset-id") is None


def test_album_contains_asset_uses_paginated_metadata_search() -> None:
    session = FakeSession(
        {
            "get": [
                FakeResponse([{"albumName": "Steam", "id": "album-id"}]),
            ],
            "post": [
                FakeResponse(
                    {
                        "assets": {
                            "items": [{"id": "asset-one"}],
                            "nextPage": "2",
                        }
                    }
                ),
                FakeResponse(
                    {
                        "assets": {
                            "items": [{"id": "asset-two"}],
                        }
                    }
                ),
            ],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.album_contains_asset("Steam", "asset-two") is True
    assert [call[1] for call in session.calls] == [
        "https://immich.example/api/albums",
        "https://immich.example/api/search/metadata",
        "https://immich.example/api/search/metadata",
    ]
    assert session.calls[1][2]["json"] == {
        "albumIds": ["album-id"],
        "page": 1,
        "size": 1000,
    }
    assert session.calls[2][2]["json"] == {
        "albumIds": ["album-id"],
        "page": 2,
        "size": 1000,
    }


def test_album_contains_asset_reuses_album_membership_cache() -> None:
    session = FakeSession(
        {
            "get": [FakeResponse([{"albumName": "Steam", "id": "album-id"}])],
            "post": [
                FakeResponse(
                    {
                        "assets": {
                            "items": [{"id": "asset-id"}],
                        }
                    }
                ),
            ],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.album_contains_asset("Steam", "asset-id") is True
    assert client.album_contains_asset("Steam", "missing-asset") is False
    assert [call[0] for call in session.calls] == ["get", "post"]


def test_album_contains_asset_returns_false_when_album_is_missing() -> None:
    session = FakeSession(
        {
            "get": [FakeResponse([])],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.album_contains_asset("Steam", "asset-id") is False
    assert session.calls == [
        ("get", "https://immich.example/api/albums", {"timeout": 5})
    ]


def test_add_assets_to_album_sends_multiple_ids() -> None:
    session = FakeSession({"get": [], "post": [], "put": [FakeResponse({})]})
    client = _client_with_session(session)

    client.add_assets_to_album("album-id", ["asset-1", "asset-2"])

    assert session.calls == [
        (
            "put",
            "https://immich.example/api/albums/album-id/assets",
            {"json": {"ids": ["asset-1", "asset-2"]}, "timeout": 5},
        )
    ]


def test_add_asset_to_album_wraps_single_id() -> None:
    session = FakeSession({"get": [], "post": [], "put": [FakeResponse({})]})
    client = _client_with_session(session)

    client.add_asset_to_album("album-id", "asset-1")

    assert session.calls[0][2]["json"] == {"ids": ["asset-1"]}


def test_asset_has_tags_matches_hierarchical_tag_paths() -> None:
    client = _client_with_session(FakeSession({"get": [], "post": [], "put": []}))
    asset = {
        "tags": [
            {"path": "Steam"},
            {"path": "Steam/Baldur's Gate 3"},
        ]
    }

    assert client.asset_has_tags(asset, ["Steam", "Steam/Baldur's Gate 3"]) is True
    assert client.asset_has_tags(asset, ["Steam", "Steam App/1086940"]) is False


def test_tag_assets_sends_multiple_ids() -> None:
    session = FakeSession({"get": [], "post": [], "put": [FakeResponse({})]})
    client = _client_with_session(session)

    client.tag_assets("tag-id", ["asset-1", "asset-2"])

    assert session.calls == [
        (
            "put",
            "https://immich.example/api/tags/tag-id/assets",
            {"json": {"ids": ["asset-1", "asset-2"]}, "timeout": 5},
        )
    ]


def test_tag_asset_wraps_single_id() -> None:
    session = FakeSession({"get": [], "post": [], "put": [FakeResponse({})]})
    client = _client_with_session(session)

    client.tag_asset("tag-id", "asset-1")

    assert session.calls[0][2]["json"] == {"ids": ["asset-1"]}


def test_get_tag_reuses_existing_tag_without_creating() -> None:
    # Existing Immich tags should be reused without creating a duplicate.
    session = FakeSession(
        {"get": [FakeResponse([{"name": "Steam", "id": "tag-id"}])], "post": [], "put": []}
    )
    client = _client_with_session(session)

    assert client.get_tag("Steam") == "tag-id"
    assert client.get_tag("Steam") == "tag-id"
    assert [call[0] for call in session.calls] == ["get"]


def test_get_tag_matches_hierarchical_tag_path() -> None:
    # Immich may expose hierarchical tags through a full path field.
    session = FakeSession(
        {
            "get": [FakeResponse([{"path": "Steam/Baldur's Gate 3", "name": "Baldur's Gate 3", "id": "tag-id"}])],
            "post": [],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_tag("Steam/Baldur's Gate 3") == "tag-id"
    assert [call[0] for call in session.calls] == ["get"]


def test_create_tag_recovers_when_immich_reports_existing_tag() -> None:
    # If a create races or lookup missed the response shape, refresh and reuse the existing tag.
    session = FakeSession(
        {
            "get": [
                FakeResponse([]),
                FakeResponse([{"path": "Steam", "id": "tag-id"}]),
            ],
            "post": [
                FakeResponse(
                    {"message": "A tag with that name already exists"},
                    status_code=400,
                    text='{"message":"A tag with that name already exists"}',
                )
            ],
            "put": [],
        }
    )
    client = _client_with_session(session)

    assert client.get_or_create_tag("Steam") == "tag-id"
    assert [call[0] for call in session.calls] == ["get", "post", "get"]


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
