from __future__ import annotations

import json
from importlib.resources import files

from aletheia.core.events import DataCategory
from aletheia.engine.classifier import load_sensitivities
from aletheia.engine.necessity import load_matrix


def test_necessity_matrix_covers_every_purpose_category_pair() -> None:
    matrix = load_matrix()
    assert len(matrix) >= 40
    expected_categories = {category.value for category in DataCategory}
    for purpose, entry in matrix.items():
        assert set(entry["categories"]) == expected_categories, purpose
        assert set(entry["categories"].values()) <= {
            "required",
            "reasonable",
            "unnecessary",
            "red_flag",
        }
        assert entry["justification"].strip()


def test_sensitivity_table_has_no_orphans_or_missing_categories() -> None:
    sensitivities = load_sensitivities()
    assert set(sensitivities) == {category.value for category in DataCategory}
    assert all(0 <= score <= 1 for score in sensitivities.values())
    assert sensitivities[DataCategory.CREDENTIALS_PASSWORD.value] == 1.0
    assert sensitivities[DataCategory.GOVERNMENT_ID_PASSPORT.value] >= 0.9


def test_known_site_seed_has_at_least_300_valid_entries() -> None:
    sites = json.loads(files("aletheia.data").joinpath("known_sites.yaml").read_text())
    assert len(sites) >= 300
    for domain, entry in sites.items():
        assert "." in domain
        assert "://" not in domain
        assert entry["purpose"] in load_matrix()
