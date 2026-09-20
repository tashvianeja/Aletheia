"""Where the QR codes are on a page, found by their finder patterns.

An Aadhaar card's QR code carries the whole record the card prints — name, date of
birth, gender, address, and in the secure version a photograph as well. Masking the
printed digits and leaving the square beside them is not a redaction: anything that
can hold a phone up to the copy reads back everything that was covered. So the
square has to go too, and finding it cannot depend on a decoder being installed.

Every QR symbol, whatever it holds, is built around three finder patterns: seven
modules square, concentric dark-light-dark, one at each corner but the bottom right.
Their giveaway is the run of dark and light along any line through the middle of
one, which is always 1:1:3:1:1. That ratio is what this module looks for, first
across each row and then down the column through each hit, and three confirmed
centres of a matching size fix the symbol's square exactly: the centres span the
symbol less its two outer half-finders, so growing their box by three and a half
modules on every side gives the symbol itself.

Nothing here decodes anything. It locates, which is all a black box needs.
"""

from __future__ import annotations

from typing import Any

import numpy as np

Box = tuple[float, float, float, float]
# Below this a "module" is more likely paper grain or the stem of a letter than a
# QR code, and a symbol that small holds nothing worth covering anyway.
MIN_MODULE = 2.0
# Two finder centres in one symbol sit (size - 7) modules apart, and a symbol runs
# from 21 modules square to 177, so anything outside this is not one pair.
MIN_SEPARATION = 12.0
MAX_SEPARATION = 180.0
# Working width for the scan. A symbol worth covering is a decent fraction of the
# page, so shrinking a large scan keeps the cost down without losing the pattern.
MAX_SCAN = 2000


def _threshold(gray: np.ndarray) -> float:
    """Otsu's split between ink and paper."""
    counts = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    levels = np.arange(256, dtype=np.float64)
    total = counts.sum()
    if total <= 0:
        return 128.0
    weight_low = np.cumsum(counts)
    weight_high = total - weight_low
    sum_low = np.cumsum(counts * levels)
    sum_high = sum_low[-1] - sum_low
    usable = (weight_low > 0) & (weight_high > 0)
    if not usable.any():
        return 128.0
    spread = np.zeros(256, dtype=np.float64)
    spread[usable] = (
        weight_low[usable]
        * weight_high[usable]
        * (sum_low[usable] / weight_low[usable] - sum_high[usable] / weight_high[usable]) ** 2
    )
    return float(np.argmax(spread))


def _centres(line: np.ndarray) -> list[tuple[float, float]]:
    """Every 1:1:3:1:1 dark-light-dark run along one row or column.

    Returns each hit's position along the line and the module size it implies.
    """
    if line.size < 7:
        return []
    changes = np.flatnonzero(np.diff(line)) + 1
    starts = np.concatenate(([0], changes))
    lengths = np.diff(np.concatenate((starts, [line.size]))).astype(np.float64)
    if lengths.size < 5:
        return []
    values = line[starts]
    windows = lengths.size - 4
    runs = np.stack([lengths[index : index + windows] for index in range(5)])
    module = runs.sum(axis=0) / 7.0
    tolerance = module / 2.0
    # The middle run is three modules wide, so it is allowed three times the slack.
    good = (
        (values[:windows] == 1)
        & (module >= MIN_MODULE)
        & (np.abs(runs[0] - module) < tolerance)
        & (np.abs(runs[1] - module) < tolerance)
        & (np.abs(runs[2] - 3 * module) < 3 * tolerance)
        & (np.abs(runs[3] - module) < tolerance)
        & (np.abs(runs[4] - module) < tolerance)
    )
    hits = np.flatnonzero(good)
    middle = starts[2 : 2 + windows][hits] + runs[2][hits] / 2.0
    return list(zip(middle.tolist(), module[hits].tolist(), strict=True))


def _finder_centres(dark: np.ndarray) -> list[tuple[float, float, float]]:
    """Confirmed finder-pattern centres, as (x, y, module).

    A run across a row only says a row passes through something shaped like a finder
    pattern; the column through that point has to show the same ratio before it
    counts, which is what rejects the horizontal bars of ordinary printed type.
    """
    found: list[tuple[float, float, float]] = []
    for y in range(dark.shape[0]):
        for x, module in _centres(dark[y]):
            column = dark[:, int(x)]
            for down, vertical in _centres(column):
                if abs(down - y) <= 2 * module and 0.5 <= vertical / module <= 2.0:
                    found.append((x, down, (module + vertical) / 2.0))
                    break
    merged: list[tuple[float, float, float]] = []
    for centre_x, centre_y, size in found:
        for index, (had_x, had_y, had_size) in enumerate(merged):
            if abs(had_x - centre_x) <= size and abs(had_y - centre_y) <= size:
                merged[index] = (
                    (had_x + centre_x) / 2,
                    (had_y + centre_y) / 2,
                    (had_size + size) / 2,
                )
                break
        else:
            merged.append((centre_x, centre_y, size))
    return merged


def _symbols(centres: list[tuple[float, float, float]]) -> list[Box]:
    """Group centres that belong to one symbol, and give each group its square."""
    remaining = list(centres)
    boxes: list[Box] = []
    while remaining:
        group = [remaining.pop()]
        changed = True
        while changed:
            changed = False
            for candidate in list(remaining):
                for member in group:
                    module = (candidate[2] + member[2]) / 2
                    gap = max(abs(candidate[0] - member[0]), abs(candidate[1] - member[1]))
                    if (
                        0.75 <= candidate[2] / member[2] <= 1.33
                        and MIN_SEPARATION * module <= gap <= MAX_SEPARATION * module
                    ):
                        group.append(candidate)
                        remaining.remove(candidate)
                        changed = True
                        break
        # Two corners leave the symbol's size a guess, and a box guessed too small is
        # worse than none: it would leave a readable code under a convincing bar.
        if len(group) < 3:
            continue
        module = sum(item[2] for item in group) / len(group)
        margin = 3.5 * module
        boxes.append(
            (
                min(item[0] for item in group) - margin,
                min(item[1] for item in group) - margin,
                max(item[0] for item in group) + margin,
                max(item[1] for item in group) + margin,
            )
        )
    return boxes


def find_qr_codes(image: Any) -> list[Box]:
    """The pixel box of every QR code on `image`, in its own coordinates.

    Never raises: a page this cannot read is a page with no boxes to report, and the
    caller says separately that the codes on it were not looked for.
    """
    try:
        from PIL import Image

        gray = image.convert("L")
        scale = 1.0
        if max(gray.size) > MAX_SCAN:
            scale = MAX_SCAN / max(gray.size)
            gray = gray.resize(
                (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
                Image.Resampling.BOX,
            )
        pixels = np.asarray(gray, dtype=np.uint8)
        dark = (pixels <= _threshold(pixels)).astype(np.int8)
        boxes = _symbols(_finder_centres(dark))
        return [(x0 / scale, y0 / scale, x1 / scale, y1 / scale) for x0, y0, x1, y1 in boxes]
    except Exception:
        return []
