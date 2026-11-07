"""Calendar helpers shared across the pipeline."""

from __future__ import annotations

import pandas as pd


def window_bounds(launch: pd.Timestamp, months_before: int, months_after: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Launch date minus/plus whole calendar months.

    Days that don't exist in the target month clamp to its last day
    (2023-05-31 + 6 months = 2023-11-30; 2024-02-29 - 3 months = 2023-11-29).
    """
    launch = pd.Timestamp(launch).normalize()
    return launch - pd.DateOffset(months=months_before), launch + pd.DateOffset(months=months_after)
