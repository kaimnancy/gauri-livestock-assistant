"""Deterministic tool functions exposed to the ADK Record Agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from gauri_app.core.doc_store import (
    AnimalDocStore,
    AnimalRecord,
    HealthConditionEntry,
    HealthRecordEntry,
    ImageMetadataEntry,
    VaccinationEntry,
    get_missing_key_fields,
)

_STORE = AnimalDocStore()


def _serialize_summary(rec: AnimalRecord) -> dict[str, Any]:
    return {
        "animal_id": rec.animal_id,
        "local_name": rec.local_name,
        "species_or_breed": rec.species_or_breed,
        "pashuadhan_id_exists": rec.pashuadhan_id_exists,
        "pashuadhan_id": rec.pashuadhan_id,
        "insurance_taken": rec.insurance_taken,
        "last_vaccinated": rec.last_vaccinated,
        "health_condition": rec.health_condition,
        "local_vet_number": rec.local_vet_number,
        "image_count": len(rec.image_metadata),
    }


def list_household_animals(user_id: str) -> dict[str, Any]:
    """List all registered animals for a user to check if they are new or returning."""
    records = _STORE.list_user_animals(user_id)
    return {
        "user_id": user_id,
        "is_new_user": len(records) == 0,
        "count": len(records),
        "animals": [_serialize_summary(r) for r in records],
    }


def find_animal(user_id: str, animal_ref: str) -> dict[str, Any]:
    """Search a user's animals by local name, Pashudhan ID, animal_id, or breed."""
    matches = _STORE.find_animals(user_id, animal_ref)
    if len(matches) == 1:
        match_type = "exact"
    elif len(matches) > 1:
        match_type = "multiple"
    else:
        match_type = "none"

    total_animals = len(_STORE.list_user_animals(user_id))
    return {
        "match_type": match_type,
        "count": len(matches),
        "total_household_animals": total_animals,
        "matches": [_serialize_summary(r) for r in matches],
    }


def read_animal_record(user_id: str, animal_id: str) -> dict[str, Any]:
    """Read the full contextual Markdown record and missing key fields for one animal."""
    rec = _STORE.load_record(user_id, animal_id)
    if rec is None:
        return {"found": False, "error": f"No animal found with id '{animal_id}'."}

    return {
        "found": True,
        "animal_id": rec.animal_id,
        "markdown": _STORE.read_markdown(user_id, animal_id),
        "missing_key_fields": get_missing_key_fields(rec),
    }


def upsert_animal_record(
    user_id: str,
    animal_id: Optional[str] = None,
    local_name: Optional[str] = None,
    species_or_breed: Optional[str] = None,
    pashuadhan_id_exists: Optional[str] = None,
    pashuadhan_id: Optional[str] = None,
    insurance_taken: Optional[str] = None,
    insurance_info: Optional[str] = None,
    local_vet_number: Optional[str] = None,
    last_vaccinated_date: Optional[str] = None,
    vaccine_name: Optional[str] = None,
    vaccination_notes: Optional[str] = None,
    health_condition_summary: Optional[str] = None,
    health_condition_status: Optional[str] = None,
    health_record_update: Optional[str] = None,
    image_path: Optional[str] = None,
    image_description: Optional[str] = None,
    source: str = "OWNER_REPORTED",
) -> dict[str, Any]:
    """Create a new animal record or update an existing one and append log tables."""
    rec: Optional[AnimalRecord] = None
    action = "updated"

    if animal_id:
        rec = _STORE.load_record(user_id, animal_id)

    # Guard 1: Match existing animal by exact local_name if animal_id omitted
    if rec is None and local_name:
        exact_name_matches = [
            r
            for r in _STORE.list_user_animals(user_id)
            if r.local_name and r.local_name.strip().lower() == local_name.strip().lower()
        ]
        if len(exact_name_matches) == 1:
            rec = exact_name_matches[0]

    # Guard 2: Match existing animal mentioned in description/update text when both ID & name omitted
    if rec is None and not local_name:
        hint_blob = " ".join(filter(None, [image_description, health_record_update, health_condition_summary])).lower()
        if hint_blob:
            name_hits = [
                r
                for r in _STORE.list_user_animals(user_id)
                if r.local_name and re.search(rf"\b{re.escape(r.local_name.lower())}\b", hint_blob)
            ]
            if len(name_hits) == 1:
                rec = name_hits[0]

    # Prevent placeholder strings like "yes" from leaking into insurance_info
    if insurance_info:
        non_detail = {"yes", "no", "true", "false", "unknown", "none", "n/a", "insured"}
        if insurance_info.strip().lower() in non_detail:
            if not insurance_taken and insurance_info.strip().lower() in {"yes", "true", "insured"}:
                insurance_taken = "yes"
            insurance_info = None

    if rec is None:
        action = "created"
        new_id = _STORE.generate_animal_id(user_id, pashuadhan_id=pashuadhan_id)
        rec = AnimalRecord(user_id=user_id, animal_id=new_id)

    # Migrate generated ID to official Pashudhan ID if supplied later
    if pashuadhan_id and pashuadhan_id.strip():
        clean_gov = pashuadhan_id.strip()
        if action == "updated" and rec.animal_id != clean_gov:
            rec = _STORE.migrate_animal_id(user_id, rec.animal_id, clean_gov)
        else:
            rec.pashuadhan_id_exists = "yes"
            rec.pashuadhan_id = clean_gov
    elif pashuadhan_id_exists in ("yes", "no", "unknown"):
        rec.pashuadhan_id_exists = pashuadhan_id_exists  # type: ignore[assignment]

    if local_name:
        rec.local_name = local_name.strip()

    if species_or_breed:
        rec.species_or_breed = species_or_breed.strip()
    elif not rec.species_or_breed and health_record_update:
        low_ctx = health_record_update.lower()
        if "buffalo" in low_ctx:
            rec.species_or_breed = "buffalo"
        elif "cow" in low_ctx:
            rec.species_or_breed = "cow"

    if insurance_taken in ("yes", "no", "unknown"):
        rec.insurance_taken = insurance_taken  # type: ignore[assignment]
    if insurance_info:
        rec.insurance_taken = "yes"
        rec.insurance_info = insurance_info.strip()
    if local_vet_number:
        rec.local_vet_number = local_vet_number.strip()

    # Append-only Image Metadata (only real existing files, deduplicated)
    if image_path and image_path.strip():
        clean_img = image_path.strip()
        if Path(clean_img).exists():
            already_saved = any(img.image_path == clean_img for img in rec.image_metadata)
            if not already_saved:
                rec.image_metadata.append(
                    ImageMetadataEntry(
                        image_path=clean_img,
                        description=(image_description or "Identification photo").strip(),
                    )
                )

    # Append-only Vaccination Table (deduplicated by date + vaccine_name)
    if last_vaccinated_date:
        clean_date = last_vaccinated_date.strip()
        inferred_vaccine = (vaccine_name or "").strip()
        if not inferred_vaccine:
            context_blob = f"{vaccination_notes or ''} {health_record_update or ''}".upper()
            for v_code in ("FMD", "HS", "BQ", "BRUCELLOSIS", "ANTHRAX", "RABIES", "THEILERIOSIS"):
                if v_code in context_blob:
                    inferred_vaccine = v_code
                    break
        final_vaccine = inferred_vaccine or "Unspecified"
        rec.last_vaccinated = clean_date
        already_logged = any(
            v.date == clean_date and v.vaccine_name.lower() == final_vaccine.lower()
            for v in rec.vaccination_table
        )
        if not already_logged:
            rec.vaccination_table.append(
                VaccinationEntry(
                    date=clean_date,
                    vaccine_name=final_vaccine,
                    notes=(vaccination_notes or "").strip(),
                    source=source,
                )
            )

    # Append-only Health Condition Table
    if health_condition_summary:
        rec.health_condition = health_condition_summary.strip()
        rec.health_condition_table.append(
            HealthConditionEntry(
                summary=health_condition_summary.strip(),
                status=(health_condition_status or "active").strip(),
                source=source,
            )
        )

    # Append-only Health Record Table (always log at least a fallback summary)
    log_text = (health_record_update or "").strip()
    if not log_text:
        name_label = rec.local_name or rec.animal_id
        log_text = f"{action.capitalize()} profile record for {name_label}."
    rec.health_record_table.append(
        HealthRecordEntry(
            context_update=log_text,
            source=source,
        )
    )

    _, md_path = _STORE.save_record(rec)
    return {
        "status": "ok",
        "action": action,
        "animal_id": rec.animal_id,
        "markdown_path": str(md_path),
        "record_summary": _serialize_summary(rec),
        "missing_key_fields": get_missing_key_fields(rec),
    }
