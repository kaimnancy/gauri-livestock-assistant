"""Deterministic storage and Markdown renderer for household animal records."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

DEFAULT_DATA_DIR = Path("data/animals")

YesNoUnknown = Literal["yes", "no", "unknown"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return cleaned.strip("_") or "unknown"


class VaccinationEntry(BaseModel):
    date: str
    vaccine_name: str = "Unspecified"
    notes: str = ""
    source: str = "OWNER_REPORTED"
    recorded_at: str = Field(default_factory=_utc_now)


class HealthConditionEntry(BaseModel):
    timestamp: str = Field(default_factory=_utc_now)
    summary: str
    status: str = "active"
    source: str = "OWNER_REPORTED"


class HealthRecordEntry(BaseModel):
    timestamp: str = Field(default_factory=_utc_now)
    context_update: str
    source: str = "OWNER_REPORTED"


class ImageMetadataEntry(BaseModel):
    image_path: str
    description: str = "Identification photo"
    uploaded_at: str = Field(default_factory=_utc_now)


class AnimalRecord(BaseModel):
    """Canonical structured record for one dairy animal."""

    user_id: str
    animal_id: str
    pashuadhan_id_exists: YesNoUnknown = "unknown"
    pashuadhan_id: Optional[str] = None
    insurance_taken: YesNoUnknown = "unknown"
    insurance_info: Optional[str] = None
    local_name: Optional[str] = None
    species_or_breed: Optional[str] = None
    last_vaccinated: Optional[str] = None
    health_condition: Optional[str] = None
    local_vet_number: Optional[str] = None
    image_metadata: list[ImageMetadataEntry] = Field(default_factory=list)

    vaccination_table: list[VaccinationEntry] = Field(default_factory=list)
    health_condition_table: list[HealthConditionEntry] = Field(default_factory=list)
    health_record_table: list[HealthRecordEntry] = Field(default_factory=list)

    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


def _md_cell(text: Optional[str]) -> str:
    if not text:
        return "-"
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render_animal_markdown(rec: AnimalRecord) -> str:
    lines: list[str] = [
        f"# Animal Record: {rec.local_name or 'Unnamed Animal'} (`{rec.animal_id}`)",
        "",
        "## Key Profile Information",
        f"- **User ID:** {rec.user_id}",
        f"- **Animal ID:** `{rec.animal_id}`",
        f"- **Pashudhan / Govt ID Exists:** {rec.pashuadhan_id_exists}",
        f"- **Pashudhan / Govt ID:** {rec.pashuadhan_id or 'Not provided'}",
        f"- **Insurance Taken:** {rec.insurance_taken}",
        f"- **Insurance Information:** {rec.insurance_info or 'Not provided'}",
        f"- **Local Name:** {rec.local_name or 'Not provided'}",
        f"- **Species / Breed:** {rec.species_or_breed or 'Not provided'}",
        f"- **Last Vaccinated:** {rec.last_vaccinated or 'Not recorded'}",
        f"- **Current Health Condition:** {rec.health_condition or 'Not recorded'}",
        f"- **Local Vet Number:** {rec.local_vet_number or 'Not provided'}",
        f"- **Last Updated:** {rec.updated_at}",
        "",
        "## Image Metadata (Identification)",
    ]

    if rec.image_metadata:
        lines.append("| Uploaded At | Image Path | Description |")
        lines.append("| :--- | :--- | :--- |")
        for img in rec.image_metadata:
            lines.append(
                f"| {_md_cell(img.uploaded_at)} | `{_md_cell(img.image_path)}` | {_md_cell(img.description)} |"
            )
    else:
        lines.append("_No identification images uploaded yet._")

    lines.extend(["", "## Vaccination Table"])
    if rec.vaccination_table:
        lines.append("| Date | Vaccine | Notes | Source | Recorded At |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for v in rec.vaccination_table:
            lines.append(
                f"| {_md_cell(v.date)} | {_md_cell(v.vaccine_name)} | {_md_cell(v.notes)} | {_md_cell(v.source)} | {_md_cell(v.recorded_at)} |"
            )
    else:
        lines.append("_No vaccination entries logged yet._")

    lines.extend(["", "## Health Condition Table"])
    if rec.health_condition_table:
        lines.append("| Timestamp | Condition Summary | Status | Source |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for hc in rec.health_condition_table:
            lines.append(
                f"| {_md_cell(hc.timestamp)} | {_md_cell(hc.summary)} | {_md_cell(hc.status)} | {_md_cell(hc.source)} |"
            )
    else:
        lines.append("_No health condition updates logged yet._")

    lines.extend(["", "## Health Record Table (Conversation Log)"])
    if rec.health_record_table:
        lines.append("| Timestamp | Context Update | Source |")
        lines.append("| :--- | :--- | :--- |")
        for hr in rec.health_record_table:
            lines.append(
                f"| {_md_cell(hr.timestamp)} | {_md_cell(hr.context_update)} | {_md_cell(hr.source)} |"
            )
    else:
        lines.append("_No health record entries logged yet._")

    lines.append("")
    return "\n".join(lines)


def get_missing_key_fields(rec: AnimalRecord) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []

    if not rec.local_name:
        missing.append({
            "field": "local_name",
            "priority": "high",
            "prompt_hint": "Ask what local name the family calls this animal.",
        })
    if not rec.local_vet_number:
        missing.append({
            "field": "local_vet_number",
            "priority": "high",
            "prompt_hint": "Ask for their local veterinarian's phone number for emergencies.",
        })
    if not rec.last_vaccinated:
        missing.append({
            "field": "last_vaccinated",
            "priority": "high",
            "prompt_hint": "Ask when this animal was last vaccinated (e.g., FMD/HS).",
        })
    if rec.pashuadhan_id_exists == "unknown":
        missing.append({
            "field": "pashuadhan_id_exists",
            "priority": "medium",
            "prompt_hint": "Ask if the animal has a Pashudhan / Pashu Aadhaar ear-tag government ID.",
        })
    elif rec.pashuadhan_id_exists == "yes" and not rec.pashuadhan_id:
        missing.append({
            "field": "pashuadhan_id",
            "priority": "medium",
            "prompt_hint": "Ask for the Pashudhan / government ID number.",
        })
    if rec.insurance_taken == "unknown":
        missing.append({
            "field": "insurance_taken",
            "priority": "medium",
            "prompt_hint": "Ask whether livestock insurance has been taken for this animal.",
        })
    elif rec.insurance_taken == "yes" and not rec.insurance_info:
        missing.append({
            "field": "insurance_info",
            "priority": "medium",
            "prompt_hint": "Ask for the insurance policy details (provider or policy number).",
        })
    if not rec.image_metadata:
        missing.append({
            "field": "image_metadata",
            "priority": "low",
            "prompt_hint": "Optionally remind them they can send a photo for easy identification.",
        })

    return missing


class AnimalDocStore:
    """Deterministic file-backed store for animal records organized by user_id."""

    def __init__(self, base_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: str) -> Path:
        path = self.base_dir / _safe_slug(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _paths(self, user_id: str, animal_id: str) -> tuple[Path, Path]:
        udir = self._user_dir(user_id)
        slug = _safe_slug(animal_id)
        return udir / f"{slug}.json", udir / f"{slug}.md"

    def generate_animal_id(self, user_id: str, pashuadhan_id: Optional[str] = None) -> str:
        if pashuadhan_id and pashuadhan_id.strip():
            return _safe_slug(pashuadhan_id)
        return f"{_safe_slug(user_id)}_{uuid4().hex[:6]}"

    def save_record(self, rec: AnimalRecord) -> tuple[Path, Path]:
        rec.updated_at = _utc_now()
        json_path, md_path = self._paths(rec.user_id, rec.animal_id)
        json_path.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
        md_path.write_text(render_animal_markdown(rec), encoding="utf-8")
        return json_path, md_path

    def load_record(self, user_id: str, animal_id: str) -> Optional[AnimalRecord]:
        json_path, _ = self._paths(user_id, animal_id)
        if not json_path.exists():
            return None
        return AnimalRecord.model_validate_json(json_path.read_text(encoding="utf-8"))

    def read_markdown(self, user_id: str, animal_id: str) -> Optional[str]:
        _, md_path = self._paths(user_id, animal_id)
        if not md_path.exists():
            return None
        return md_path.read_text(encoding="utf-8")

    def list_user_animals(self, user_id: str) -> list[AnimalRecord]:
        udir = self._user_dir(user_id)
        records: list[AnimalRecord] = []
        for jf in sorted(udir.glob("*.json")):
            records.append(AnimalRecord.model_validate_json(jf.read_text(encoding="utf-8")))
        return records

    def find_animals(self, user_id: str, query: str) -> list[AnimalRecord]:
        q = (query or "").strip().lower()
        if not q:
            return []

        records = self.list_user_animals(user_id)
        exact: list[AnimalRecord] = []
        partial: list[AnimalRecord] = []

        stop_words = {
            "my", "the", "a", "an", "our", "her", "his", "this", "that",
            "one", "first", "second", "user", "users", "owner", "owners",
            "farmer", "family", "named", "names", "called", "animal", "s",
        }
        q_tokens = [t for t in re.findall(r"[a-z0-9_-]+", q) if t not in stop_words]

        for rec in records:
            id_match = q == rec.animal_id.lower() or (
                rec.pashuadhan_id and q == rec.pashuadhan_id.lower()
            )
            name_match = rec.local_name and q == rec.local_name.lower()
            if id_match or name_match:
                exact.append(rec)
                continue

            if rec.local_name and re.search(rf"\b{re.escape(rec.local_name.lower())}\b", q):
                exact.append(rec)
                continue

            searchable = " ".join(
                filter(None, [rec.local_name, rec.species_or_breed])
            ).lower()
            if (q and q in searchable) or (q_tokens and any(tok in searchable for tok in q_tokens)):
                partial.append(rec)

        return exact if exact else partial

    def migrate_animal_id(self, user_id: str, old_animal_id: str, new_pashuadhan_id: str) -> AnimalRecord:
        rec = self.load_record(user_id, old_animal_id)
        if rec is None:
            raise FileNotFoundError(f"Animal '{old_animal_id}' not found for user '{user_id}'.")

        old_json, old_md = self._paths(user_id, old_animal_id)
        rec.pashuadhan_id_exists = "yes"
        rec.pashuadhan_id = new_pashuadhan_id.strip()
        rec.animal_id = _safe_slug(new_pashuadhan_id)
        self.save_record(rec)

        if old_animal_id != rec.animal_id:
            old_json.unlink(missing_ok=True)
            old_md.unlink(missing_ok=True)
        return rec
