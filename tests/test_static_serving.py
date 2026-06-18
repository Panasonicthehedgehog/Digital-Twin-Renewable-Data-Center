from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.static_serving import mount_frontend


def test_mount_returns_false_when_dist_missing(tmp_path: Path) -> None:
    app = FastAPI()
    mounted = mount_frontend(app, tmp_path / "does_not_exist")
    assert mounted is False


def test_mount_serves_index_html(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>hello twin</html>", encoding="utf-8")

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mounted = mount_frontend(app, dist)
    assert mounted is True

    client = TestClient(app)
    # API/route still takes precedence over the static mount
    assert client.get("/health").json() == {"status": "ok"}
    # Root serves the built index.html
    root = client.get("/")
    assert root.status_code == 200
    assert "hello twin" in root.text
