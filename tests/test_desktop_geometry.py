"""Window positioning fits the work area without opening a GUI."""

import pytest

from zhijing.desktop_panel import _fit_panel_geometry


def test_companion_starts_compact_next_to_default_mascot():
    geometry = _fit_panel_geometry((0, 0, 1920, 1040))
    assert (geometry["width"], geometry["height"]) == (480, 700)
    assert geometry["min_size"] == (380, 520)
    assert geometry["x"] > 1920 / 2
    assert geometry["y"] > 0
    assert geometry["x"] + geometry["width"] <= 1920 - 92
    assert geometry["y"] + geometry["height"] < 1040


@pytest.mark.parametrize("bounds", [(0, 0, 420, 560), (-800, -600, 0, 0), (0, 0, 320, 400)])
def test_companion_fits_small_and_offset_work_areas(bounds):
    geometry = _fit_panel_geometry(bounds)
    left, top, right, bottom = bounds
    assert left <= geometry["x"] < geometry["x"] + geometry["width"] <= right
    assert top <= geometry["y"] < geometry["y"] + geometry["height"] <= bottom
    assert 0 < geometry["min_size"][0] <= geometry["width"] <= 480
    assert 0 < geometry["min_size"][1] <= geometry["height"] <= 700
