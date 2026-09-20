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
across each row and then down the column through each hit.

Three confirmed centres of a matching size then fix the symbol's square exactly: the
centres span the symbol less its two outer half-finders, so growing their box by
three and a half modules on every side gives the symbol itself. Which three go
together is settled by the shape they make — two of them the same distance from the
third and at a right angle to it — and not by how near to each other they lie. A
sheet that carries two codes, as an e-Aadhaar does, otherwise comes back as one
symbol spanning both, and the box that follows covers everything printed between
them.

Nothing here decodes anything. It locates, which is all a black box needs.
"""

from __future__ import annotations

import itertools
import math
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
# How far a trio may stray from the shape three finder patterns make: two of them the
# same distance from the third and at a right angle to it. Loose enough for a scan
# that sits slightly askew on the glass, tight enough that three hits scattered over
# a page do not pass for one symbol.
SHAPE_TOLERANCE = 0.2
# Every trio of centres is tried, so a page that returns hundreds of hits — a dense
# halftone, a photograph of a crowd — is cut down first. The largest modules are kept
# because they are the symbols worth covering.
MAX_CENTRES = 96
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


def _is_corner(
    corner: tuple[float, float, float],
    arm: tuple[float, float, float],
    other: tuple[float, float, float],
) -> bool:
    """Whether `corner` sits at the right angle between the other two centres.

    The three finder patterns of a symbol mark three corners of a square, so from the
    one between the other two they are the same distance away and at ninety degrees
    to each other. That is the whole test, and it holds however the page is turned.
    """
    first = (arm[0] - corner[0], arm[1] - corner[1])
    second = (other[0] - corner[0], other[1] - corner[1])
    reach = math.hypot(*first)
    span = math.hypot(*second)
    if reach <= 0 or span <= 0:
        return False
    if abs(reach - span) > SHAPE_TOLERANCE * max(reach, span):
        return False
    return abs(first[0] * second[0] + first[1] * second[1]) / (reach * span) <= SHAPE_TOLERANCE


def _fuse(boxes: list[Box]) -> list[Box]:
    """One box per symbol. Several trios of one symbol give boxes lying on each other."""
    fused: list[Box] = []
    for box in boxes:
        grown = box
        apart = []
        for other in fused:
            if (
                grown[0] < other[2]
                and other[0] < grown[2]
                and grown[1] < other[3]
                and other[1] < grown[3]
            ):
                grown = (
                    min(grown[0], other[0]),
                    min(grown[1], other[1]),
                    max(grown[2], other[2]),
                    max(grown[3], other[3]),
                )
            else:
                apart.append(other)
        fused = [*apart, grown]
    return fused


def _symbols(centres: list[tuple[float, float, float]]) -> list[Box]:
    """The square of every symbol whose three finder patterns are among `centres`.

    A symbol is read off the shape its finders make, not off how near to each other
    they happen to lie. Gathering whatever was within reach and calling the result one
    symbol is what let a card carrying two codes come back as a single enormous one:
    a stray hit in the white between them joined the two clusters, and the box that
    followed covered everything printed in between — on an Aadhaar, most of the card.
    Testing the shape costs a pass over the trios and cannot make that mistake, since
    two centres from one code and a third from the other are not a right angle.
    """
    boxes: list[Box] = []
    limited = sorted(centres, key=lambda item: -item[2])[:MAX_CENTRES]
    for trio in itertools.combinations(limited, 3):
        sizes = [item[2] for item in trio]
        # Finder patterns of one symbol are printed at one module size.
        if min(sizes) <= 0 or max(sizes) / min(sizes) > 1.33:
            continue
        module = sum(sizes) / 3
        for index in range(3):
            corner = trio[index]
            arm, other = (trio[position] for position in range(3) if position != index)
            reach = math.hypot(arm[0] - corner[0], arm[1] - corner[1]) / module
            if not (MIN_SEPARATION <= reach <= MAX_SEPARATION) or not _is_corner(
                corner, arm, other
            ):
                continue
            # The centres span the symbol less its two outer half-finders, so growing
            # their box by three and a half modules a side gives the symbol itself.
            margin = 3.5 * module
            boxes.append(
                (
                    min(item[0] for item in trio) - margin,
                    min(item[1] for item in trio) - margin,
                    max(item[0] for item in trio) + margin,
                    max(item[1] for item in trio) + margin,
                )
            )
            break
    return _fuse(boxes)


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
