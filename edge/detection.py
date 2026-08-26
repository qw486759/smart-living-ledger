"""Pure image-analysis helpers for the Edge Bridge — no camera or AWS I/O, so
they unit-test with plain numpy arrays.

This "gate" only decides whether a frame is worth sending to the cloud (is there
motion / a foreground object?). It does NOT identify Zeus — that is the cloud
vision step (see docs/adr/0005). Keeping it dumb is what makes it free to run.
"""
from __future__ import annotations

import numpy as np


def to_gray(frame: np.ndarray) -> np.ndarray:
    """Luminance of a BGR frame as float32 (stable for diffs). Accepts gray input."""
    if frame.ndim == 2:
        return frame.astype(np.float32)
    b, g, r = frame[..., 0], frame[..., 1], frame[..., 2]
    # Same weights as cv2.COLOR_BGR2GRAY.
    return (0.114 * b + 0.587 * g + 0.299 * r).astype(np.float32)


def motion_ratio(prev_gray: np.ndarray, curr_gray: np.ndarray, pixel_delta: int = 25) -> float:
    """Fraction of pixels that changed by more than `pixel_delta` between two
    frames. 0.0 = identical, 1.0 = every pixel changed."""
    if prev_gray.shape != curr_gray.shape:
        raise ValueError("frames must have the same shape")
    diff = np.abs(prev_gray.astype(np.float32) - curr_gray.astype(np.float32))
    changed = int(np.count_nonzero(diff > pixel_delta))
    return changed / diff.size


def is_candidate(ratio: float, threshold: float = 0.02) -> bool:
    """A frame is worth uploading if enough of it changed (default 2%)."""
    return ratio >= threshold


def frame_key(zone: str, ts) -> str:
    """S3 key for a candidate frame."""
    return f"frames/{zone}/{ts}.jpg"
