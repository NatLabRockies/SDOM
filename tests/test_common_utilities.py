"""Tests for shared utility helpers."""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from sdom.common.utilities import concatenate_dataframes, parse_finite_float


@pytest.mark.parametrize(("raw", "expected"), [(-3, -3.0), (0, 0.0), (4.5, 4.5), ("2.5", 2.5)])
def test_parse_finite_float_accepts_numeric_inputs_without_domain_bounds(raw, expected):
    assert parse_finite_float(raw, error_message="Invalid rate") == expected


@pytest.mark.parametrize("raw", [None, "", "nonnumeric", float("nan"), float("inf"), -float("inf")])
def test_parse_finite_float_rejects_invalid_inputs_with_caller_diagnostic(raw):
    message = "SolarCurtailmentCost must be numeric and finite."
    with pytest.raises(ValueError) as raised:
        parse_finite_float(raw, error_message=message)
    assert str(raised.value) == message


def test_concatenate_dataframes_empty_metric_returns_copy_without_warning():
    """Empty metrics should not trigger pandas concatenation dtype warnings."""
    summary_df = pd.DataFrame(
        [
            {
                "Metric": "Total cost",
                "Technology": None,
                "Run": 1,
                "Optimal Value": 1.0,
                "Unit": "$US",
            }
        ]
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        actual = concatenate_dataframes(summary_df, {}, metric="Capacity")

    pd.testing.assert_frame_equal(actual, summary_df)
    assert actual is not summary_df


def test_concatenate_dataframes_missing_value_retains_row_without_warning():
    """Unavailable metric values should retain their summary row without warnings."""
    summary_df = pd.DataFrame(
        [
            {
                "Metric": "Total cost",
                "Technology": None,
                "Run": 1,
                "Optimal Value": 1.0,
                "Unit": "$US",
            }
        ]
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        actual = concatenate_dataframes(
            summary_df, {"Thermal": None}, metric="Capacity"
        )

    assert actual.loc[1, "Technology"] == "Thermal"
    assert pd.isna(actual.loc[1, "Optimal Value"])