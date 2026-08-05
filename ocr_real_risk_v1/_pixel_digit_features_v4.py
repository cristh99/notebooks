"""Image cleaning, segmentation, and feature extraction for pixel digit v4."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from ._pixel_digit_contract_v4 import SegmentationPolicy

SHAPE = (64, 48)
HOG = cv2.HOGDescriptor(
    _winSize=(48, 64),
    _blockSize=(16, 16),
    _blockStride=(8, 8),
    _cellSize=(8, 8),
    _nbins=9,
)


def ink(image: Image.Image) -> np.ndarray:
    array = cv2.GaussianBlur(np.array(image.convert("L")), (3, 3), 0)
    _, binary = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    components, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), 8
    )
    cleaned = np.zeros_like(binary)
    minimum_area = max(2, int(binary.size * 0.0003))
    for component in range(1, components):
        if stats[component, cv2.CC_STAT_AREA] >= minimum_area:
            cleaned[labels == component] = 255
    rows, columns = np.where(cleaned > 0)
    if not len(columns):
        return np.zeros((1, 1), np.uint8)
    return cleaned[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]


def remove_punctuation(binary: np.ndarray, policy: SegmentationPolicy) -> np.ndarray:
    """Remove short low-area separators while retaining full-height digit 1."""

    components, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), 8
    )
    if components <= 2:
        return binary
    heights = [int(stats[index, cv2.CC_STAT_HEIGHT]) for index in range(1, components)]
    areas = [int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, components)]
    maximum_height = max(heights)
    reference_area = float(
        np.median(
            [
                area
                for height, area in zip(heights, areas, strict=True)
                if height >= maximum_height * 0.65
            ]
            or areas
        )
    )
    result = np.zeros_like(binary)
    kept = 0
    for component in range(1, components):
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        area = int(stats[component, cv2.CC_STAT_AREA])
        punctuation = bool(
            height < maximum_height * policy.punctuation_height_ratio
            and area < reference_area * policy.punctuation_area_ratio
        )
        if not punctuation:
            result[labels == component] = 255
            kept += 1
    if not kept:
        return binary
    rows, columns = np.where(result > 0)
    return result[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]


def normalize(binary: np.ndarray, shape: tuple[int, int] = SHAPE) -> np.ndarray:
    height, width = shape
    rows, columns = np.where(binary > 0)
    if not len(columns):
        return np.zeros(shape, np.uint8)
    binary = binary[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
    source_height, source_width = binary.shape
    scale = min((height - 10) / source_height, (width - 10) / source_width)
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    resized = cv2.resize(
        binary,
        (resized_width, resized_height),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    _, resized = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
    result = np.zeros(shape, np.uint8)
    y = (height - resized_height) // 2
    x = (width - resized_width) // 2
    result[y : y + resized_height, x : x + resized_width] = resized
    return result


def projection_cuts(binary: np.ndarray, length: int) -> tuple[int, ...]:
    _, width = binary.shape
    if length <= 1:
        return (0, width)
    projection = np.convolve(
        (binary > 0).sum(axis=0).astype(float), np.ones(3) / 3, mode="same"
    )
    expected_width = width / length
    cuts = [0]
    for index in range(1, length):
        center = index * expected_width
        low = max(cuts[-1] + 1, int(center - expected_width * 0.35))
        high = min(width - 1, int(center + expected_width * 0.35) + 1)
        cut = round(center) if low >= high else min(
            range(low, high),
            key=lambda column: (
                projection[column] + 0.15 * abs(column - center),
                abs(column - center),
                column,
            ),
        )
        cuts.append(cut)
    cuts.append(width)
    return tuple(cuts)


def segment(binary: np.ndarray, length: int) -> tuple[tuple[np.ndarray, ...], tuple[int, ...]]:
    cuts = projection_cuts(binary, length)
    patches: list[np.ndarray] = []
    for left, right in zip(cuts, cuts[1:]):
        patch = binary[:, left:right]
        rows, columns = np.where(patch > 0)
        if len(columns):
            patch = patch[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
        patches.append(patch)
    return tuple(patches), cuts


def feature(binary: np.ndarray) -> np.ndarray:
    normalized = normalize(binary)
    hog = HOG.compute(normalized).ravel().astype(np.float32)
    low_resolution = (
        cv2.resize(normalized, (12, 16), interpolation=cv2.INTER_AREA)
        .ravel()
        .astype(np.float32)
        / 255
    )
    horizontal = (normalized > 0).mean(axis=1).astype(np.float32)
    vertical = (normalized > 0).mean(axis=0).astype(np.float32)
    vector = np.concatenate(
        [hog, low_resolution * 0.8, horizontal * 0.5, vertical * 0.5]
    )
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector
