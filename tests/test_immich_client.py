from datetime import datetime

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


def test_check_existing_assets_posts_device_asset_ids() -> None:
    # Existing-asset checks should ask Immich which local device asset IDs it already has.
    session = FakeSession(
        {
            "get": [],
            "post": [FakeResponse({"existingIds": ["device-id-1"]})],
            "put": [],
        }
    )
    client = _client_with_session(session)

    existing_ids = client.check_existing_assets(["device-id-1", "device-id-2"])

    assert existing_ids == {"device-id-1"}
    method, url, kwargs = session.calls[0]
    assert method == "post"
    assert url == "https://immich.example/api/assets/exist"
    assert kwargs["json"] == {
        "deviceAssetIds": ["device-id-1", "device-id-2"],
        "deviceId": "steam2immich",
    }


def test_check_existing_assets_rejects_invalid_payload() -> None:
    # Existing-asset responses must include an existingIds list.
    session = FakeSession(
        {
            "get": [],
            "post": [FakeResponse({"existingIds": "device-id-1"})],
            "put": [],
        }
    )
    client = _client_with_session(session)

    try:
        client.check_existing_assets(["device-id-1"])
    except ImmichClientError as error:
        assert "existingIds" in str(error)
    else:
        raise AssertionError("Expected ImmichClientError")
