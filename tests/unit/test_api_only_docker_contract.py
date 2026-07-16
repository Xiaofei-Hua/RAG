from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_only_image_keeps_versioned_domain_profiles() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "data" not in dockerignore
    assert "data/*" in dockerignore
    assert "!data/profiles/" in dockerignore
    assert "!data/profiles/**" in dockerignore

    workflow = (ROOT / ".github" / "workflows" / "docker-api-only.yml").read_text(encoding="utf-8")
    assert "/app/data/profiles/general.yaml" in workflow
    assert "/app/data/profiles/aviation_phm.yaml" in workflow
