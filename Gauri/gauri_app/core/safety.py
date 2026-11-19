"""Deterministic safety layer: Emergency Router, Input Quality Gate, and Output Guard."""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from gauri_app.core.schemas import InputPayload

logger = logging.getLogger(__name__)

MIN_TRANSCRIPTION_CONFIDENCE = 0.70

EMERGENCY_PATTERNS: dict[str, list[str]] = {
    "severe_bloating": [
        r"\bsevere\s+bloat(?:ing)?\b",
        r"\bbloat(?:ed|ing)\s+(?:badly|severely|like\s+a\s+drum)\b",
        r"\bstomach\s+(?:is\s+)?(?:blown\s+up|swollen\s+like\s+a\s+drum|very\s+tight|hard\s+like\s+a\s+drum)\b",
        r"\btympany\b",
    ],
    "heavy_bleeding": [
        r"\b(?:heavy|profuse|uncontrolled|severe)\s+bleeding\b",
        r"\bblood\s+(?:pouring|gushing|not\s+stopping)\b",
    ],
    "snakebite": [
        r"\bsnake\s*bite\b",
        r"\bbitten\s+by\s+a\s+snake\b",
        r"\bsnake\s+bit\b",
    ],
    "collapse_or_unconscious": [
        r"\b(?:collapsed|unconscious|seizures?|convulsions?|fitting)\b",
        r"\b(?:cannot|can't|unable\s+to)\s+stand\b",
    ],
    "choking_or_breathing_distress": [
        r"\bchoking\b",
        r"\b(?:cannot|can't|struggling\s+to)\s+breathe\b",
        r"\bgasping\s+for\s+air\b",
    ],
    "calving_emergency": [
        r"\bcalf\s+(?:is\s+)?stuck\b",
        r"\bdystocia\b",
        r"\bprolapse\b",
        r"\buterus\s+(?:coming|hanging)\s+out\b",
    ],
    "suspected_poisoning": [
        r"\b(?:ate|ingested|drank)\s+poison\b",
        r"\bpoisoning\b",
    ],
}

BLOCKED_MEDICATIONS: list[str] = [
    r"\bparacetamol\b",
    r"\bmeloxicam\b",
    r"\boxytetracycline\b",
    r"\bivermectin\b",
    r"\bpenicillin\b",
    r"\bamoxicillin\b",
    r"\benrofloxacin\b",
    r"\bdexamethasone\b",
    r"\bdiclofenac\b",
    r"\bflunixin\b",
    r"\bketoprofen\b",
    r"\bgentamicin\b",
    r"\bstreptomycin\b",
    r"\balbendazole\b",
    r"\bfenbendazole\b",
    r"\bcephalexin\b",
    r"\bceftriaxone\b",
    r"\bavilin\b",
    r"\bchlorpheniramine\b",
    r"\bcalcium\s+borogluconate\b",
]

DOSAGE_PATTERNS: list[str] = [
    r"\b\d+(?:\.\d+)?\s*(?:ml|mg|gm|g|cc|iu)\b",
    r"\b\d+(?:\.\d+)?\s*(?:tablets?|tabs?|capsules?|bolus|boli|drops?|injections?|shots?)\b",
    r"\b\d+\s*(?:times?\s+a\s+day|times?\s+daily)\b",
    r"\b(?:twice|thrice)\s+daily\b",
]

PRESCRIPTION_PATTERNS: list[str] = [
    r"\b(?:give|administer|inject|feed)\s+(?:her|him|the\s+(?:cow|buffalo|animal))\s+[^.]{0,40}\b(?:tablet|medicine|injection|antibiotic|painkiller|syrup|dose|bolus)\b",
    r"(?<!cannot\s)(?<!can't\s)(?<!never\s)(?<!not\s)\bprescribe\b",
]

DIAGNOSIS_PATTERNS: list[str] = [
    r"\b(?:she|he|your\s+(?:cow|buffalo|animal))\s+(?:definitely\s+|clearly\s+)?has\s+(?:mastitis|fmd|foot\s+and\s+mouth|milk\s+fever|brucellosis|anthrax|black\s+quarter|hemorrhagic\s+septicemia|theileriosis|babesiosis|ketosis|acidosis)\b",
    r"\b(?:this\s+is|diagnosed\s+with|diagnosis\s+is)\s+(?:mastitis|fmd|foot\s+and\s+mouth|milk\s+fever|brucellosis|anthrax|ketosis)\b",
]


class EmergencyCheckResult(BaseModel):
    is_emergency: bool = False
    matched_categories: list[str] = Field(default_factory=list)
    matched_phrases: list[str] = Field(default_factory=list)


class InputSafetyResult(BaseModel):
    emergency: EmergencyCheckResult = Field(default_factory=EmergencyCheckResult)
    needs_clarification: bool = False
    clarification_reasons: list[str] = Field(default_factory=list)


class OutputGuardResult(BaseModel):
    is_safe: bool = True
    violations: list[str] = Field(default_factory=list)
    safe_fallback_message: Optional[str] = None


def check_emergency(english_text: str) -> EmergencyCheckResult:
    """Scan English input for deterministic emergency red flags."""
    text = english_text or ""
    matched_categories: list[str] = []
    matched_phrases: list[str] = []

    for category, patterns in EMERGENCY_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                if category not in matched_categories:
                    matched_categories.append(category)
                phrase = match.group(0)
                if phrase not in matched_phrases:
                    matched_phrases.append(phrase)

    is_emergency = len(matched_categories) > 0
    if is_emergency:
        logger.warning(
            "EMERGENCY_TRIGGERED categories=%s phrases=%s",
            matched_categories,
            matched_phrases,
        )
    return EmergencyCheckResult(
        is_emergency=is_emergency,
        matched_categories=matched_categories,
        matched_phrases=matched_phrases,
    )


def run_input_safety_checks(payload: InputPayload) -> InputSafetyResult:
    """Run pre-orchestration safety and input-quality checks."""
    emergency = check_emergency(payload.english_description)
    if emergency.is_emergency:
        return InputSafetyResult(emergency=emergency, needs_clarification=False)

    reasons: list[str] = []
    if payload.transcription_confidence < MIN_TRANSCRIPTION_CONFIDENCE:
        reasons.append(
            f"LOW_TRANSCRIPTION_CONFIDENCE ({payload.transcription_confidence:.2f} < {MIN_TRANSCRIPTION_CONFIDENCE})"
        )
    for issue in payload.flagged_issues:
        reasons.append(f"FLAGGED_ISSUE: {issue}")

    return InputSafetyResult(
        emergency=emergency,
        needs_clarification=len(reasons) > 0,
        clarification_reasons=reasons,
    )


def check_output_safety(response_text: str) -> OutputGuardResult:
    """Block medication names, dosages, prescriptions, and definitive diagnoses."""
    violations: list[str] = []

    checks = [
        ("BLOCKED_MEDICATION", BLOCKED_MEDICATIONS),
        ("BLOCKED_DOSAGE", DOSAGE_PATTERNS),
        ("BLOCKED_PRESCRIPTION", PRESCRIPTION_PATTERNS),
        ("BLOCKED_DIAGNOSIS", DIAGNOSIS_PATTERNS),
    ]

    for label, patterns in checks:
        for pattern in patterns:
            match = re.search(pattern, response_text, flags=re.IGNORECASE)
            if match:
                violations.append(f"{label}: '{match.group(0)}'")

    if violations:
        logger.error("OUTPUT_GUARD_BLOCKED violations=%s", violations)
        return OutputGuardResult(
            is_safe=False,
            violations=violations,
            safe_fallback_message=(
                "Gauri cannot recommend medicines, dosages, or provide a medical diagnosis. "
                "Please consult a qualified local veterinarian."
            ),
        )

    return OutputGuardResult(is_safe=True)
