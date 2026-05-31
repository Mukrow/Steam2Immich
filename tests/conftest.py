from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from steam2immich.models import ScreenshotCandidate


@pytest.fixture
def fixture_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def steam_root(fixture_root: Path) -> Path:
    return fixture_root / "steam_root"


@pytest.fixture
def uncompressed_dir(fixture_root: Path) -> Path:
    return fixture_root / "uncompressed"


@pytest.fixture
def candidate_factory(tmp_path):
    def build(**overrides: Any) -> ScreenshotCandidate:
        chosen_path = overrides.pop("chosen_path", tmp_path / "shot.png")
        chosen_path.parent.mkdir(parents=True, exist_ok=True)
        if not chosen_path.exists():
            chosen_path.write_bytes(b"not a real image")

        values = {
            "app_id": "1086940",
            "game_name": "Baldur's Gate 3",
            "normal_path": chosen_path,
            "uncompressed_path": None,
            "chosen_path": chosen_path,
            "timestamp": datetime(2025, 1, 1, 1, 1, 1),
            "caption": "A dummy Steam screenshot",
        }
        values.update(overrides)
        return ScreenshotCandidate(**values)

    return build


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, text: str = "") -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, responses: dict[str, list[FakeResponse]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        return self.responses["get"].pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("post", url, kwargs))
        return self.responses["post"].pop(0)

    def put(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("put", url, kwargs))
        return self.responses["put"].pop(0)
