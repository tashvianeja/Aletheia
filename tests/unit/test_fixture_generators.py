from __future__ import annotations

import json
import zipfile
from pathlib import Path

from privacy_guardian.analysis.pii.validators import passport_mrz
from tests.fixtures.generate.generate_corpora import generate as generate_corpora
from tests.fixtures.generate.generate_documents import generate as generate_documents
from tests.fixtures.generate.generate_documents import synthetic_mrz
from tests.fixtures.generate.generate_scenarios import (
    build_scenarios,
)
from tests.fixtures.generate.generate_scenarios import (
    generate as generate_scenarios,
)


def test_scenario_generator_produces_at_least_60_complete_cases(tmp_path: Path) -> None:
    paths = generate_scenarios(tmp_path)
    assert len(paths) >= 60
    scenario_ids: set[str] = set()
    outcomes: set[str] = set()
    for path in paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        scenario_ids.add(scenario["id"])
        outcomes.add(scenario["expected"]["outcome"])
        assert "raw_content" not in scenario["event"]
        assert scenario["event"]["data_categories"]
        assert len(scenario["expected"]["rationale_keywords"]) >= 2
    assert len(scenario_ids) == len(paths)
    assert outcomes == {"IGNORE", "INFORM", "INTERVENE"}


def test_scenario_matrix_covers_every_declared_pair() -> None:
    scenarios = build_scenarios()
    pairs = {
        (item["context"]["purpose"], item["event"]["data_categories"][0]) for item in scenarios
    }
    assert len(pairs) == len(scenarios)


def test_corpus_generator_produces_annotated_balanced_corpora(tmp_path: Path) -> None:
    terms, policies = generate_corpora(tmp_path)
    assert len(terms) >= 15
    assert len(policies) >= 15
    term_labels: set[str] = set()
    policy_purposes: set[str] = set()
    policy_shares: set[str] = set()
    for path in terms:
        annotation = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        assert annotation["synthetic"] is True
        assert annotation["clauses"]
        term_labels.update(annotation["clauses"])
    for path in policies:
        annotation = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        assert annotation["synthetic"] is True
        policy_purposes.update(annotation["purposes"])
        policy_shares.update(annotation["shares_with"])
    assert len(term_labels) >= 10
    assert len(policy_purposes) >= 6
    assert len(policy_shares) >= 6


def test_document_generator_outputs_parseable_formats(tmp_path: Path) -> None:
    generated = {path.name: path for path in generate_documents(tmp_path)}
    assert generated["passport_synthetic.pdf"].read_bytes().startswith(b"%PDF-")
    with zipfile.ZipFile(generated["financial_synthetic.docx"]) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        assert "SYNTHETIC TEST DOCUMENT" in document
        assert "4111111111111111" in document
    jpeg = generated["social_photo_gps_synthetic.jpg"].read_bytes()
    assert jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")


def test_synthetic_passport_mrz_has_valid_td3_check_digits() -> None:
    mrz = synthetic_mrz()
    assert passport_mrz(mrz)
    assert all(len(line) == 44 for line in mrz.splitlines())
