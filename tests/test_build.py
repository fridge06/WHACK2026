import json

import pytest

from pipeline import build
from pipeline.config import ROOT, load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def mock_build(cfg):
    if not (ROOT / cfg["paths"]["mock_dir"] / "games.csv").exists():
        pytest.skip("no mock data; run python -m pipeline.make_mock")
    return build.build(cfg, mock=True)


def test_mock_build_excludes_exactly_the_broken_games(cfg, mock_build):
    _, report = mock_build
    expected = json.loads((ROOT / cfg["paths"]["mock_dir"] / "expected_issues.json").read_text())
    assert set(report["excluded"]) == set(expected["excluded"])


def test_mock_build_output_shape(mock_build):
    doc, _ = mock_build
    assert doc["meta"]["placeholder"] is True
    assert doc["meta"]["verdict_phrase"] == "In its first month"
    assert sum(s["weight"] for s in doc["meta"]["signals"]) == pytest.approx(1, abs=1e-3)
    for g in doc["games"]:
        assert len(g["popularity"]) == 10
        anchor = [m for m in g["market"] if m["d"] <= 0 and m["trading"]][-1]
        assert anchor["mv"] == anchor["implied"]
        launch = next(p for p in g["popularity"] if p["m"] == 0)
        assert launch["value"] == 100


def test_main_writes_json(tmp_path):
    out = tmp_path / "games.json"
    assert build.main(["--mock", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["games"]


def test_real_build_without_signals_fails_clearly(cfg, capsys):
    if cfg.get("signals"):
        pytest.skip("real signals are configured")
    assert build.main(["--out", "unused.json"]) == 1
    assert "no popularity signals configured" in capsys.readouterr().err
