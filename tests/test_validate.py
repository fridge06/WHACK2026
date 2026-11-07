import copy
import json

import pytest

from pipeline import build, validate
from pipeline.config import ROOT, load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def built(cfg):
    if not (ROOT / cfg["paths"]["mock_dir"] / "games.csv").exists():
        pytest.skip("no mock data; run python -m pipeline.make_mock")
    return build.build(cfg, mock=True)


@pytest.fixture
def doc(built):
    return copy.deepcopy(built[0])


def errors_after(doc, mutate):
    mutate(doc)
    return validate.validate_output(doc)


def test_mock_output_is_valid(doc):
    assert validate.validate_output(doc) == []


def first_trading_anchor(g):
    return [m for m in g["market"] if m["d"] <= 0 and m["trading"]][-1]


@pytest.mark.parametrize("mutate, expect", [
    (lambda d: d["meta"].pop("placeholder"), "missing 'placeholder'"),
    (lambda d: d["meta"].update(generated_at="yesterday"), "generated_at"),
    (lambda d: d["meta"]["signals"].clear(), "signals"),
    (lambda d: d.update(extra=1), "top level"),
    (lambda d: d["games"].clear(), "non-empty"),
    (lambda d: d["games"].append(copy.deepcopy(d["games"][0])), "duplicate ids"),
    (lambda d: d["games"][0].update(launch="10/12/2020"), "launch"),
    (lambda d: d["games"][0].update(short=""), "short"),
    (lambda d: d["games"][0]["window"].update({"to": "2099-01-01"}), "window"),
    (lambda d: d["games"][0].update(signals_used=["nope"]), "not in meta.signals"),
    (lambda d: d["games"][0]["popularity"].pop(), "expected 10 months"),
    (lambda d: d["games"][0]["popularity"][3].update(value=99.0), "launch month value must be 100"),
    (lambda d: d["games"][0]["popularity"][1].update(mid="2000-01-01"), "mid"),
    (lambda d: d["games"][0]["popularity"][1].update(value="high"), "number or null"),
    (lambda d: d["games"][0]["market"].pop(40), "days"),
    (lambda d: d["games"][0]["market"][5].update(mv=-1), "positive number"),
    (lambda d: d["games"][0]["market"][5].update(trading="yes"), "boolean"),
    (lambda d: first_trading_anchor(d["games"][0]).update(implied=1e6), "implied must equal mv"),
    (lambda d: d["games"][0]["verdict"].update(day=7), "verdict.day"),
    (lambda d: d["games"][0]["verdict"].update(gap_gbp_bn=d["games"][0]["verdict"]["gap_gbp_bn"] + 0.5), "gap_gbp_bn"),
    (lambda d: d["games"][0]["verdict"].update(gap_pct=d["games"][0]["verdict"]["gap_pct"] + 1), "gap_pct"),
    (lambda d: d["games"][0]["verdict"].update(gap_pct=float("nan")), "not valid JSON"),
])
def test_contract_violations_are_reported(doc, mutate, expect):
    errors = errors_after(doc, mutate)
    assert errors, "expected a contract error"
    assert any(expect in e for e in errors), errors


def test_null_popularity_months_are_allowed(doc):
    doc["games"][0]["popularity"][0]["value"] = None
    assert validate.validate_output(doc) == []


def test_coverage_reports_gaps_and_exclusions(cfg, built):
    _, report = built
    expected = json.loads((ROOT / cfg["paths"]["mock_dir"] / "expected_issues.json").read_text())
    rows = {r["game_id"]: r for r in report["coverage"]}
    for gid, reason in report["excluded"].items():
        assert rows[gid]["included"] is False and rows[gid]["reason"] == reason
    for gid, notes in expected["gaps"].items():
        assert rows[gid]["included"] is True
        cells = rows[gid]["signals"]
        assert any(c["months"] < report["n_months"] for c in cells.values()), (gid, cells)
    no_base = next(g for g, why in expected["excluded"].items() if "base month" in why)
    assert not any(c["base"] for c in rows[no_base]["signals"].values())
    text = validate.format_coverage(report["coverage"], report["n_months"])
    assert "EXCLUDED" in text and "no base" in text


def test_excluded_reasons_are_clear(built):
    _, report = built
    reasons = " ".join(report["excluded"].values())
    assert "delisted" in reasons and "launch-month" in reasons


def test_build_fails_loudly_and_writes_nothing_on_contract_violation(monkeypatch, tmp_path, built, capsys):
    broken, report = copy.deepcopy(built[0]), built[1]
    broken["games"][0]["popularity"].pop()
    monkeypatch.setattr(build, "build", lambda cfg, mock: (broken, report))
    out = tmp_path / "games.json"
    assert build.main(["--mock", "--out", str(out)]) == 1
    assert not out.exists()
    assert "contract" in capsys.readouterr().err


def test_validate_cli(tmp_path, built, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(built[0]), encoding="utf-8")
    assert validate.main([str(good)]) == 0
    bad_doc = copy.deepcopy(built[0])
    bad_doc["meta"].pop("currency")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_doc), encoding="utf-8")
    assert validate.main([str(bad)]) == 1
    assert "currency" in capsys.readouterr().err
