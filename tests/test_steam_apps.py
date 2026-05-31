import json

from steam2immich import steam_apps


def test_load_name_overrides_reads_valid_json(tmp_path) -> None:
    # Valid override JSON should normalize app IDs and names to strings.
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"1086940": "Baldur's Gate 3"}), encoding="utf-8")

    assert steam_apps.load_name_overrides(path) == {"1086940": "Baldur's Gate 3"}


def test_load_name_overrides_ignores_malformed_json(tmp_path) -> None:
    # Malformed override JSON should be treated as an empty override file.
    path = tmp_path / "overrides.json"
    path.write_text("{", encoding="utf-8")

    assert steam_apps.load_name_overrides(path) == {}


def test_resolve_app_names_uses_expected_precedence(tmp_path, steam_root, monkeypatch) -> None:
    # Resolution should prefer overrides, shortcuts, local manifests, cache, then fallback.
    overrides_path = tmp_path / "overrides.json"
    cache_path = tmp_path / "cache.json"
    overrides_path.write_text(json.dumps({"1": "Override Name"}), encoding="utf-8")
    cache_path.write_text(json.dumps({"3": "Cached Name"}), encoding="utf-8")
    monkeypatch.setattr(steam_apps, "fetch_remote_app_name", lambda app_id: None)

    result = steam_apps.resolve_app_names(
        {"1", "2", "3", "4", "1086940"},
        steam_root=steam_root,
        cache_path=cache_path,
        overrides_path=overrides_path,
        shortcut_names={"2": "Shortcut Name"},
    )

    assert result.names == {
        "1": "Override Name",
        "2": "Shortcut Name",
        "3": "Cached Name",
        "4": "Steam App 4",
        "1086940": "Baldur's Gate 3",
    }
    assert result.override_hits == 1
    assert result.local_hits == 2
    assert result.cache_hits == 1
    assert result.fallbacks == 1
    assert result.unknown_app_ids == ["4"]
