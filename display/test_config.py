import json

from display.config import load_secrets


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_data_root_wins_over_repo_copy(tmp_path):
    data = _write(tmp_path / "data" / "secrets.local.json", {"openweathermap_api_key": "real"})
    repo = _write(tmp_path / "repo" / "secrets.local.json", {"openweathermap_api_key": "dev"})
    assert load_secrets((data, repo))["openweathermap_api_key"] == "real"


def test_falls_back_to_repo_copy_then_defaults(tmp_path):
    repo = _write(tmp_path / "repo" / "secrets.local.json", {"city": "Paris"})
    s = load_secrets((str(tmp_path / "missing.json"), repo))
    assert s["city"] == "Paris" and "ntp_server" in s
