import sys
from pathlib import Path

from backend.paths import resource_path, project_root


def test_resource_path_in_dev_resolves_under_project_root() -> None:
    # In dev mode (not frozen) paths resolve relative to the project root,
    # i.e. the parent of the backend/ package.
    p = resource_path("config/default_config.yaml")
    assert p == project_root() / "config" / "default_config.yaml"
    assert p.exists()  # the file really is there in the repo


def test_resource_path_uses_meipass_when_frozen(monkeypatch) -> None:
    # Simulate a PyInstaller onefile bundle.
    fake_meipass = Path("/tmp/_MEIfake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    p = resource_path("data/all_power_plants_clean.csv")
    assert p == fake_meipass / "data" / "all_power_plants_clean.csv"
