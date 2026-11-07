"""Smoke tests for the project scaffold."""

import importlib

import pytest

from pipeline.config import load_config


@pytest.mark.parametrize(
    "module",
    ["loaders", "popularity", "market", "build", "validate", "make_mock"],
)
def test_pipeline_modules_import(module):
    importlib.import_module(f"pipeline.{module}")


def test_config_parses_with_plan_defaults():
    cfg = load_config()
    assert cfg["window"] == {"months_before": 3, "months_after": 6}
    assert cfg["verdict"]["day"] == 30
    assert cfg["site"]["games_per_view"] == 6
    assert isinstance(cfg["signals"], dict)
