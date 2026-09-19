"""Tests for shared utility helpers."""

from __future__ import annotations

import warnings

import pandas as pd

from sdom.common.utilities import concatenate_dataframes


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