from PIL import Image

from steam2immich.metadata_writer import _description, _xp_string, prepare_upload_copy, write_metadata


def test_prepare_upload_copy_copies_image_and_leaves_original_unchanged(
    tmp_path, steam_root, candidate_factory
) -> None:
    # Upload preparation should metadata-enrich only the copied file, never the fixture original.
    original = (
        steam_root
        / "userdata/test-user/760/remote/999999/screenshots/20250102020202_1.png"
    )
    original_bytes = original.read_bytes()
    candidate = candidate_factory(app_id="999999", chosen_path=original, normal_path=original)

    prepared = prepare_upload_copy(candidate, tmp_path)

    assert prepared.prepared_path.exists()
    assert prepared.metadata_written is True
    assert original.read_bytes() == original_bytes
    with Image.open(prepared.prepared_path) as image:
        assert image.text["SteamAppID"] == "999999"


def test_write_metadata_returns_false_for_unsupported_suffix(tmp_path, candidate_factory) -> None:
    # Unsupported file types should be skipped without raising an exception.
    path = tmp_path / "notes.txt"
    path.write_text("not an image", encoding="utf-8")

    assert write_metadata(path, candidate_factory(chosen_path=path)) is False


def test_description_and_xp_string_format_metadata_values(candidate_factory) -> None:
    # Metadata helper values should combine captions and encode Windows XP fields.
    candidate = candidate_factory(game_name="Game", caption="Caption")

    assert _description(candidate) == "Game: Caption"
    assert _xp_string("Game") == "Game".encode("utf-16le") + b"\x00\x00"
