import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "edge"))
from detection import frame_key, is_candidate, motion_ratio, to_gray  # noqa: E402


def test_identical_frames_have_zero_motion():
    f = np.zeros((100, 100), dtype=np.uint8)
    assert motion_ratio(f, f) == 0.0


def test_fully_changed_frames_have_full_motion():
    a = np.zeros((100, 100), dtype=np.uint8)
    b = np.full((100, 100), 255, dtype=np.uint8)
    assert motion_ratio(a, b) == 1.0


def test_small_change_below_threshold_is_not_candidate():
    a = np.zeros((100, 100), dtype=np.uint8)
    b = a.copy()
    b[:5, :5] = 255  # 25 / 10000 = 0.25% changed
    assert not is_candidate(motion_ratio(a, b), threshold=0.02)


def test_large_change_above_threshold_is_candidate():
    a = np.zeros((100, 100), dtype=np.uint8)
    b = a.copy()
    b[:20, :20] = 255  # 400 / 10000 = 4% changed
    assert is_candidate(motion_ratio(a, b), threshold=0.02)


def test_pixel_delta_ignores_small_lighting_noise():
    a = np.zeros((100, 100), dtype=np.uint8)
    b = np.full((100, 100), 10, dtype=np.uint8)  # +10 everywhere, below default delta 25
    assert motion_ratio(a, b) == 0.0


def test_mismatched_shapes_raise():
    with pytest.raises(ValueError):
        motion_ratio(np.zeros((10, 10)), np.zeros((10, 20)))


def test_frame_key_format():
    assert frame_key("porch", 1787435042) == "frames/porch/1787435042.jpg"


def test_to_gray_from_bgr_uses_luminance_weights():
    bgr = np.zeros((4, 4, 3), dtype=np.uint8)
    bgr[..., 2] = 100  # red channel (BGR index 2)
    gray = to_gray(bgr)
    assert gray.shape == (4, 4)
    assert abs(float(gray[0, 0]) - 0.299 * 100) < 0.01
