"""Tests for the DT-side Flex coordinate and instrument contracts."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from twin_core import (
    DeckPoint,
    FlexInstrumentNotFound,
    FlexLocationNotFound,
    FlexMount,
    StaticFlexDeckResolver,
    StaticFlexConfig,
    StaticFlexInstrumentResolver,
    WellAnchor,
)


def test_static_deck_resolver_applies_workflow_offsets() -> None:
    resolver = StaticFlexDeckResolver(
        anchors={
            ("reactor", "C5", WellAnchor.TOP): DeckPoint(
                x=100.0,
                y=200.0,
                z=30.0,
            )
        }
    )

    point = resolver.resolve(
        "reactor",
        "C5",
        WellAnchor.TOP,
        offset_x_mm=1.5,
        offset_y_mm=-2.0,
        offset_z_mm=4.0,
    )

    assert point == DeckPoint(x=101.5, y=198.0, z=34.0)


def test_static_deck_resolver_reports_missing_anchor() -> None:
    resolver = StaticFlexDeckResolver(anchors={})

    with pytest.raises(FlexLocationNotFound, match="reactor"):
        resolver.resolve("reactor", "C5", WellAnchor.BOTTOM)


def test_static_deck_resolver_exposes_tip_geometry() -> None:
    resolver = StaticFlexDeckResolver(
        anchors={},
        tip_lengths_mm={("tips", "A1"): 95.6},
    )

    assert resolver.tip_length_mm("tips", "A1") == pytest.approx(95.6)
    assert resolver.tip_length_mm("tips", "A2") is None


def test_deck_point_rejects_non_finite_coordinates() -> None:
    with pytest.raises(ValidationError):
        DeckPoint(x=math.nan, y=0.0, z=0.0)


def test_instrument_resolver_requires_explicit_alias() -> None:
    resolver = StaticFlexInstrumentResolver({"p1000_single_gen2": FlexMount.RIGHT})

    assert resolver.mount_for("p1000_single_gen2") is FlexMount.RIGHT
    with pytest.raises(FlexInstrumentNotFound, match="p300"):
        resolver.mount_for("p300")


def test_static_flex_config_builds_both_asset_resolvers(tmp_path) -> None:
    path = tmp_path / "flex.json"
    path.write_text(
        """{
          "anchors": [{
            "labware": "rack",
            "well": "A1",
            "anchor": "top",
            "point": {"x": 1, "y": 2, "z": 3},
            "tip_length_mm": 95.6
          }],
          "instruments": {"p1000": "RIGHT"}
        }"""
    )

    config = StaticFlexConfig.load_json(path)

    assert config.deck_resolver().resolve("rack", "A1", WellAnchor.TOP) == DeckPoint(
        x=1, y=2, z=3
    )
    assert config.deck_resolver().tip_length_mm("rack", "A1") == pytest.approx(95.6)
    assert config.instrument_resolver().mount_for("p1000") is FlexMount.RIGHT


def test_static_flex_config_rejects_duplicate_anchors() -> None:
    anchor = {
        "labware": "rack",
        "well": "A1",
        "anchor": "top",
        "point": {"x": 1, "y": 2, "z": 3},
    }

    with pytest.raises(ValidationError, match="duplicate Flex anchor"):
        StaticFlexConfig.model_validate(
            {"anchors": [anchor, anchor], "instruments": {}}
        )
