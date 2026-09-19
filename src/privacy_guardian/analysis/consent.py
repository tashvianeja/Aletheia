from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, Field


class ConsentButton(BaseModel):
    text: str = ""
    role: str = ""
    visible: bool = True
    area: float = 0
    contrast: float = 4.5
    layer: int = 1


class ConsentToggle(BaseModel):
    purpose: str
    enabled: bool = False
    optional: bool = True
    legitimate_interest: bool = False


class ConsentSnapshot(BaseModel):
    text: str = ""
    cmp: str = "unknown"
    selectors: list[str] = Field(default_factory=list)
    buttons: list[ConsentButton] = Field(default_factory=list)
    toggles: list[ConsentToggle] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    vendor_count: int = Field(default=0, ge=0)
    tcf_present: bool = False
    tcf_purpose_consents: dict[str, bool] = Field(default_factory=dict)
    tcf_vendor_count: int = Field(default=0, ge=0)
    fixed_or_sticky: bool = False
    reject_clicks: int = 1


class ConsentAnalysis(BaseModel):
    detected: bool = False
    cmp: str = "unknown"
    purposes: list[str] = Field(default_factory=list)
    vendor_count: int = 0
    dark_patterns: list[str] = Field(default_factory=list)
    recommendation: str = "reject_optional"
    reject_selectors: list[str] = Field(default_factory=list)
    manage_selectors: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def cmp_adapters() -> dict[str, dict[str, list[str]]]:
    value: dict[str, dict[str, list[str]]] = json.loads(
        files("privacy_guardian.data").joinpath("cmp_adapters.json").read_text()
    )
    return value


def analyze_consent(snapshot: ConsentSnapshot | dict[str, object]) -> ConsentAnalysis:
    if not isinstance(snapshot, ConsentSnapshot):
        snapshot = ConsentSnapshot.model_validate(snapshot)
    cmp = snapshot.cmp.lower()
    for name, adapter in cmp_adapters().items():
        if set(snapshot.selectors) & set(adapter["selectors"]):
            cmp = name
            break
    detected = (
        cmp in cmp_adapters()
        or snapshot.tcf_present
        or (
            snapshot.fixed_or_sticky
            and bool(snapshot.buttons)
            and bool(re.search(r"cookies?|consent|privacy preferences", snapshot.text, re.I))
        )
    )
    result = ConsentAnalysis(detected=detected, cmp=cmp, vendor_count=snapshot.vendor_count)
    if not detected:
        return result
    purposes = set(snapshot.purposes)
    tcf_categories = {
        "1": "necessary",
        "2": "advertising",
        "3": "profiling",
        "4": "advertising",
        "5": "profiling",
        "6": "profiling",
        "7": "analytics",
        "8": "analytics",
        "9": "analytics",
        "10": "analytics",
    }
    for purpose_id, enabled in snapshot.tcf_purpose_consents.items():
        if purpose_id in tcf_categories:
            purposes.add(tcf_categories[purpose_id])
            if enabled and purpose_id != "1":
                result.dark_patterns.append("preticked_optional")
    result.vendor_count = max(result.vendor_count, snapshot.tcf_vendor_count)
    categories = {
        "necessary": "necessary|essential|functional",
        "analytics": "analytics|statistics|measurement",
        "advertising": "advertis|marketing|personaliz|personalis",
        "profiling": "profil|cross.site",
    }
    for name, pattern in categories.items():
        if re.search(pattern, snapshot.text, re.I):
            purposes.add(name)
    # A toggle labelled "Targeted advertising" is the advertising purpose, not a fifth
    # one. Carrying both listed the same permission twice in the widget.
    for toggle in snapshot.toggles:
        matched = [
            name for name, pattern in categories.items() if re.search(pattern, toggle.purpose, re.I)
        ]
        purposes.update(matched or [toggle.purpose])
    result.purposes = sorted(purposes)
    accepts = [
        button
        for button in snapshot.buttons
        if button.visible
        and (
            button.role == "accept"
            or re.search(
                r"accept all|allow all|agree|alle akzeptieren|tout accepter|aceptar todo",
                button.text,
                re.I,
            )
        )
    ]
    rejects = [
        button
        for button in snapshot.buttons
        if button.visible
        and (
            button.role == "reject"
            or re.search(
                r"reject|decline|deny|necessary only|refuser|ablehnen|rechazar", button.text, re.I
            )
        )
    ]
    first_reject = [button for button in rejects if button.layer == 1]
    if accepts and not first_reject:
        result.dark_patterns.append("reject_absent_first_layer")
    if accepts and first_reject:
        accept, reject = accepts[0], first_reject[0]
        if (accept.area > 0 and reject.area < accept.area * 0.5) or (
            accept.contrast >= 4.5 and reject.contrast < 3
        ):
            result.dark_patterns.append("reject_visually_deemphasised")
    if any(
        toggle.optional and toggle.enabled and not toggle.legitimate_interest
        for toggle in snapshot.toggles
    ):
        result.dark_patterns.append("preticked_optional")
    if any(toggle.legitimate_interest and toggle.enabled for toggle in snapshot.toggles):
        result.dark_patterns.append("legitimate_interest_default_on")
    if re.search(
        r"no thanks.{0,30}(?:hate|boring|miss|worse)|don.t care about|prefer.{0,20}(?:bad|irrelevant)|reject.{0,20}(?:harm|lose)",
        snapshot.text,
        re.I,
    ):
        result.dark_patterns.append("confirmshaming")
    if snapshot.reject_clicks >= 2:
        result.dark_patterns.append("layered_rejection")
    adapter = cmp_adapters().get(cmp, {})
    result.reject_selectors = adapter.get("reject", [])
    result.manage_selectors = adapter.get("manage", [])
    result.dark_patterns = list(dict.fromkeys(result.dark_patterns))
    return result
