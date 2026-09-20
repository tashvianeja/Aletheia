from __future__ import annotations

import pytest

from aletheia.analysis.policy import analyzer


class RecordingSegmenter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def segment(self, text: str) -> list[str]:
        self.calls.append(text)
        return [text]


def install_segmenter(
    monkeypatch: pytest.MonkeyPatch,
) -> RecordingSegmenter:
    segmenter = RecordingSegmenter()
    monkeypatch.setattr(analyzer, "_segmenter", lambda: segmenter)
    return segmenter


def test_duplicate_paragraph_is_segmented_once_but_keeps_each_current_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segmenter = install_segmenter(monkeypatch)
    paragraph = "We collect email information to deliver the requested service."
    text = f"Collection\n{paragraph}\nSharing\n{paragraph}"

    segmented = analyzer.sentences(text)

    occurrences = [item for item in segmented if item[0] == paragraph]
    assert occurrences == [(paragraph, "Collection"), (paragraph, "Sharing")]
    assert segmenter.calls.count(paragraph) == 1


def test_paragraphs_beyond_cache_entry_and_character_bounds_are_all_inspected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segmenter = install_segmenter(monkeypatch)
    paragraphs = [f"Clause {index} " + ("x" * 1_020) + "." for index in range(300)]
    assert sum(map(len, paragraphs)) > 262_144

    segmented = analyzer.sentences("\n".join(paragraphs))

    assert [sentence for sentence, _heading in segmented] == paragraphs
    assert segmenter.calls == paragraphs


def test_segmentation_cache_is_call_local_and_does_not_reuse_raw_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segmenter = install_segmenter(monkeypatch)
    paragraph = "We retain account records only until the user requests deletion."

    assert analyzer.sentences(paragraph) == [(paragraph, "")]
    assert analyzer.sentences(paragraph) == [(paragraph, "")]

    assert segmenter.calls == [paragraph, paragraph]
