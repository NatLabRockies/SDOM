"""Tests for zonal-network related constants in `sdom.constants`.

Locks the public contract of the new symbols introduced by the zonal
capacity-expansion feature so that downstream code (io_manager, model
builder, results collector) can rely on them.
"""

import pytest

from sdom.constants import (
    AREA_TAG_DELIMITER,
    DEFAULT_AREA_ID,
    DEFAULT_NETWORK_FORMULATION,
    VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP,
)


def test_valid_network_formulations_map_has_required_entries():
    """The two supported Network values are registered."""
    assert "CopperPlateNetwork" in VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP
    assert "AreaTransportationModelNetwork" in VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP


def test_valid_network_formulations_map_descriptions_are_strings():
    for key, description in VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP.items():
        assert isinstance(key, str) and key, "Network formulation keys must be non-empty strings"
        assert isinstance(description, str) and description, (
            f"Description for Network formulation '{key}' must be a non-empty string"
        )


def test_default_network_formulation_is_in_map():
    """The default must be a valid registered formulation."""
    assert DEFAULT_NETWORK_FORMULATION in VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP


def test_default_network_formulation_is_copper_plate():
    """Backward-compatibility guarantee: default behavior is the legacy single-area model."""
    assert DEFAULT_NETWORK_FORMULATION == "CopperPlateNetwork"


def test_default_area_id_is_reserved_string():
    assert isinstance(DEFAULT_AREA_ID, str) and DEFAULT_AREA_ID == "default"


def test_area_tag_delimiter_is_at_sign():
    """The wide-CSV header delimiter is '@'; entity/area names must not contain it."""
    assert AREA_TAG_DELIMITER == "@"


@pytest.mark.parametrize(
    "reserved_id",
    ["a@b", "@a", "a@", "default@", "@@"],
)
def test_area_tag_delimiter_collisions_are_detectable(reserved_id):
    """Sanity check: the delimiter is detectable by `in` on candidate names."""
    assert AREA_TAG_DELIMITER in reserved_id
