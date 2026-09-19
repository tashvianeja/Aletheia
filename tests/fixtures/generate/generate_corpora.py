from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

TERMS_CLAUSES: tuple[tuple[str, str], ...] = (
    ("third_party_sharing", "We may share account details with selected service providers."),
    ("data_sale", "We may sell demographic information to advertising partners."),
    (
        "content_licence_to_provider",
        "You grant Synthetic Cloud a worldwide licence to host submitted content.",
    ),
    (
        "training_on_user_content",
        "Submitted content may be used to train our machine learning models.",
    ),
    ("retention_after_deletion", "Backups may retain account data after you delete your account."),
    (
        "arbitration_or_class_waiver",
        "Disputes must be resolved by binding arbitration and not a class action.",
    ),
    ("unilateral_change_of_terms", "We may change these terms at any time without prior notice."),
    ("automatic_renewal", "The subscription renews automatically until cancelled."),
    (
        "governing_law_foreign",
        "These terms are governed by the laws of the fictional state of Northland.",
    ),
    ("liability_cap", "Our total liability is limited to the fees paid during the previous month."),
    ("minimum_age", "You must be at least 16 years old to use the service."),
    ("account_termination_without_notice", "We may terminate an account without notice."),
    (
        "cross_border_transfer",
        "Information may be transferred to and processed in other countries.",
    ),
)

POLICY_FACTS: tuple[tuple[str, str, str], ...] = (
    ("analytics", "We use service activity to measure analytics.", "purpose"),
    ("personalised_ads", "We use browsing activity for personalised advertising.", "purpose"),
    ("marketing_email", "We use your email address to send marketing messages.", "purpose"),
    ("research", "Aggregated information is used for research.", "purpose"),
    ("security", "Device information helps us prevent fraud and protect security.", "purpose"),
    ("product_improvement", "Usage information helps improve the product.", "purpose"),
    ("ai_training", "Uploaded content may improve and train our AI models.", "purpose"),
    (
        "service_providers",
        "We share information with service providers that host the service.",
        "share",
    ),
    ("advertising_partners", "Identifiers are shared with advertising partners.", "share"),
    ("analytics_providers", "Activity is shared with analytics providers.", "share"),
    ("affiliates", "Information may be shared with companies in our corporate family.", "share"),
    ("data_brokers", "Demographic attributes may be shared with data brokers.", "share"),
    (
        "law_enforcement",
        "We disclose information to law enforcement when legally required.",
        "share",
    ),
    (
        "buyers_on_acquisition",
        "Account information may transfer to a buyer during an acquisition.",
        "share",
    ),
)


def _write_record(path: Path, text: str, annotations: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(annotations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def generate_terms(output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for index in range(15):
        selected = [
            TERMS_CLAUSES[index % len(TERMS_CLAUSES)],
            TERMS_CLAUSES[(index + 3) % len(TERMS_CLAUSES)],
        ]
        if index % 3 == 0:
            selected.append(TERMS_CLAUSES[(index + 6) % len(TERMS_CLAUSES)])
        negative_key, negative_text = TERMS_CLAUSES[(index + 8) % len(TERMS_CLAUSES)]
        negative_text = {
            "data_sale": "We do not sell personal information.",
            "training_on_user_content": "We never use submitted content to train machine learning models.",
            "automatic_renewal": "Subscriptions do not renew automatically.",
            "retention_after_deletion": "Account information is deleted when the account is deleted.",
            "third_party_sharing": "We do not share account information with advertisers.",
        }.get(negative_key, f"This agreement does not include {negative_key.replace('_', ' ')}.")
        text = (
            "Synthetic Terms of Service. "
            + " ".join(item[1] for item in selected)
            + " "
            + negative_text
        )
        path = output_dir / f"terms_{index + 1:02d}.txt"
        _write_record(
            path,
            text,
            {
                "clauses": sorted({item[0] for item in selected}),
                "negated_clauses": [negative_key],
                "synthetic": True,
            },
        )
        paths.append(path)
    return paths


def generate_policies(output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for index in range(15):
        selected = [
            POLICY_FACTS[index % len(POLICY_FACTS)],
            POLICY_FACTS[(index + 5) % len(POLICY_FACTS)],
        ]
        if index % 2 == 0:
            selected.append(POLICY_FACTS[(index + 9) % len(POLICY_FACTS)])
        negative_key, _, negative_kind = POLICY_FACTS[(index + 7) % len(POLICY_FACTS)]
        negative_text = (
            f"We do not use information for {negative_key.replace('_', ' ')}."
            if negative_kind == "purpose"
            else f"We do not share information with {negative_key.replace('_', ' ')}."
        )
        text = (
            "Synthetic Privacy Policy. We collect email and device information. "
            + " ".join(item[1] for item in selected)
            + " "
            + negative_text
        )
        annotations = {
            "collects": ["email", "device_identifiers"],
            "purposes": sorted({item[0] for item in selected if item[2] == "purpose"}),
            "shares_with": sorted({item[0] for item in selected if item[2] == "share"}),
            "negated": {negative_kind: [negative_key]},
            "synthetic": True,
        }
        path = output_dir / f"policy_{index + 1:02d}.txt"
        _write_record(path, text, annotations)
        paths.append(path)
    return paths


def generate(root: Path = ROOT) -> tuple[list[Path], list[Path]]:
    return generate_terms(root / "corpora" / "terms"), generate_policies(
        root / "corpora" / "policies"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    terms, policies = generate(args.output)
    print(f"generated {len(terms)} terms and {len(policies)} policies")


if __name__ == "__main__":
    main()
