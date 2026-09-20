from __future__ import annotations


def refine_public_profile(
    text: str, profile: dict[str, object], settings_value: object
) -> dict[str, object]:
    if (
        not isinstance(settings_value, dict)
        or not settings_value.get("enabled")
        or not settings_value.get("policy_refinement", True)
    ):
        return profile
    from aletheia.config import LLMSettings
    from aletheia.llm.client import LLMClient
    from aletheia.llm.schemas import RefinedClause, RefinedPolicy

    settings = LLMSettings.model_validate(settings_value)
    values = profile.get("clauses", [])
    clauses = (
        [
            RefinedClause.model_validate(
                {key: item[key] for key in ("category", "confidence", "citation")}
            )
            for item in values
            if isinstance(item, dict)
        ]
        if isinstance(values, list)
        else []
    )
    fallback = RefinedPolicy(clauses=clauses, summary="Local privacy analysis completed.")
    result = LLMClient(settings).complete(
        "policy_refinement",
        {"public_document": text},
        RefinedPolicy,
        fallback,
        stream=len(text) > 20_000,
    )
    if result.assisted and isinstance(result.value, RefinedPolicy):
        merged = {clause.category: clause.model_dump() for clause in clauses}
        for clause in result.value.clauses:
            if clause.category not in merged:
                merged[clause.category] = clause.model_dump()
        profile["clauses"] = list(merged.values())
        profile["summary"] = result.value.summary
        profile["llm_assisted"] = True
    return profile
