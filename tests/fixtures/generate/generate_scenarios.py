from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "scenarios"

PURPOSE_CASES: tuple[dict[str, Any], ...] = (
    {"purpose": "image_tool", "requester": "image-compressor.test", "trust": "unknown"},
    {"purpose": "government", "requester": "government-visa.test", "trust": "known_trusted"},
    {"purpose": "recipe", "requester": "weeknight-recipes.test", "trust": "unknown"},
    {"purpose": "banking", "requester": "community-bank.test", "trust": "known_trusted"},
    {"purpose": "saas_b2b", "requester": "project-board.test", "trust": "known_trusted"},
    {"purpose": "social", "requester": "photo-sharing.test", "trust": "unknown"},
    {"purpose": "wallpaper_utility", "requester": "Simple Wallpaper App", "trust": "unknown"},
    {"purpose": "backup", "requester": "Backup Tool", "trust": "known_trusted"},
)

CATEGORY_CASES: tuple[dict[str, Any], ...] = (
    {"category": "government_id.passport", "sensitivity": 0.95},
    {"category": "medical.diagnosis", "sensitivity": 0.9},
    {"category": "financial.card_number", "sensitivity": 0.9},
    {"category": "credentials.password", "sensitivity": 1.0},
    {"category": "biometric_photo", "sensitivity": 0.9},
    {"category": "location_precise", "sensitivity": 0.5},
    {"category": "phone", "sensitivity": 0.5},
    {"category": "email", "sensitivity": 0.3},
)


NECESSITY: dict[str, tuple[str, ...]] = {
    "image_tool": (
        "red_flag",
        "red_flag",
        "red_flag",
        "red_flag",
        "reasonable",
        "unnecessary",
        "unnecessary",
        "unnecessary",
    ),
    "government": (
        "required",
        "red_flag",
        "red_flag",
        "red_flag",
        "required",
        "unnecessary",
        "reasonable",
        "reasonable",
    ),
    "recipe": (
        "red_flag",
        "red_flag",
        "red_flag",
        "red_flag",
        "unnecessary",
        "unnecessary",
        "unnecessary",
        "reasonable",
    ),
    "banking": (
        "required",
        "red_flag",
        "reasonable",
        "red_flag",
        "reasonable",
        "unnecessary",
        "reasonable",
        "reasonable",
    ),
    "saas_b2b": (
        "red_flag",
        "red_flag",
        "red_flag",
        "reasonable",
        "unnecessary",
        "unnecessary",
        "unnecessary",
        "reasonable",
    ),
    "social": (
        "red_flag",
        "red_flag",
        "red_flag",
        "red_flag",
        "reasonable",
        "unnecessary",
        "unnecessary",
        "reasonable",
    ),
    "wallpaper_utility": (
        "red_flag",
        "red_flag",
        "red_flag",
        "red_flag",
        "unnecessary",
        "unnecessary",
        "unnecessary",
        "unnecessary",
    ),
    "backup": (
        "red_flag",
        "red_flag",
        "red_flag",
        "red_flag",
        "unnecessary",
        "unnecessary",
        "unnecessary",
        "reasonable",
    ),
}

NECESSITY_WEIGHT = {"required": 0.2, "reasonable": 0.5, "unnecessary": 1.0, "red_flag": 1.3}


def expected_outcome(
    purpose: str, category_index: int, sensitivity: float
) -> tuple[str, float, str]:
    verdict = NECESSITY[purpose][category_index]
    risk = min(1.0, sensitivity * NECESSITY_WEIGHT[verdict])
    if risk < 0.25:
        outcome = "IGNORE"
    elif risk < 0.55:
        outcome = "INFORM"
    else:
        outcome = "INTERVENE"
    return outcome, risk, verdict


def build_scenarios() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for index, (purpose, category) in enumerate(product(PURPOSE_CASES, CATEGORY_CASES), start=1):
        category_index = CATEGORY_CASES.index(category)
        outcome, risk, verdict = expected_outcome(
            purpose["purpose"], category_index, category["sensitivity"]
        )
        website = ".test" in purpose["requester"]
        necessity_phrase = {
            "required": "is needed",
            "reasonable": "may reasonably",
            "unnecessary": "does not appear necessary",
            "red_flag": "unusually sensitive",
        }[verdict]
        keywords = [
            category["category"].split(".")[-1].replace("_", " "),
            purpose["purpose"].replace("_", " "),
            necessity_phrase,
        ]
        scenarios.append(
            {
                "id": f"engine-{index:03d}",
                "event": {
                    "event_type": "form_submit" if website else "system_access",
                    "source": "browser" if website else "os",
                    "requester": {
                        "kind": "website" if website else "application",
                        "display_name": purpose["requester"],
                        "origin": f"https://{purpose['requester']}" if website else "",
                        "purpose": purpose["purpose"],
                        "purpose_confidence": 1.0,
                        "trust_tier": purpose["trust"],
                    },
                    "data_categories": [category["category"]],
                },
                "context": {
                    "purpose": purpose["purpose"],
                    "purpose_confidence": 1.0,
                    "sensitivity": category["sensitivity"],
                    "necessity": verdict,
                    "consequence_factor": 1.0,
                    "tracking_boost": 0.0,
                    "expected_risk": round(risk, 4),
                },
                "preferences": {
                    "category": "ask",
                    "site_override": None,
                    "prior_consistent_allows": 0,
                },
                "expected": {"outcome": outcome, "rationale_keywords": keywords},
            }
        )
    return scenarios


def generate(output_dir: Path = SCENARIO_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for scenario in build_scenarios():
        path = output_dir / f"{scenario['id']}.yaml"
        path.write_text(json.dumps(scenario, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        generated.append(path)
    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=SCENARIO_DIR)
    args = parser.parse_args()
    print(f"generated {len(generate(args.output))} engine scenarios")


if __name__ == "__main__":
    main()
