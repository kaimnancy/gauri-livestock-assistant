# Gauri — Agentic AI Livestock Healthcare & Triage Assistant

Gauri is a multi-agent livestock record-keeping and triage assistant designed for dairy caregivers. It combines a deterministic safety layer, a stateful session-scoped orchestrator, and a file-backed animal record agent that supports both official Pashudhan IDs and non-governmental photo-based identification.

## System Architecture

```text
User Input (English Description + Optional Image)
        │
        ▼
┌──────────────────────────────┐
│  Deterministic Safety Gate   │ ── Red Flags (0.0s bypass) ──► 1962 / Vet Escalation
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     Gauri Orchestrator       │ ◄── Session-scoped household animal roster
│  (ADK Router + Task State)   │ ◄── Pause & resume on same task_id if ambiguous
└──────┬───────────────┬───────┘
       │               │
       ▼               ▼
 [Live Core]     [Phase 2 Contracts (Wired Stubs)]
 • Record Agent  • Triage Agent (Symptom assessment & Vet Card)
 • AnimalDocStore• Health Check Agent (Breed / BCS visual check)
   (JSON + MD)   • Behaviour Reply Agent (Regional / Hindi output)
```

## What Is Live in This Proof-of-Concept

* **Deterministic Safety Gate (`gauri_app/core/safety.py`):** Intercepts life-threatening red flags (e.g., severe bloat, breathing distress) before the LLM runs, returning an instant (`0.0s`) escalation to the local veterinarian or 1962 helpline. Also enforces non-prescription guardrails whenever medication or dosage is requested.
* **Stateful Orchestrator (`gauri_app/orchestrator/`):** Preloads only the active user's registered animals into session state, routes across `RECORD`, `TRIAGE`, `HEALTH_CHECK`, `GENERAL_QUERY`, and `EMERGENCY`, and pauses/resumes on the exact same `task_id` when an animal reference is ambiguous.
* **Record Agent & Deterministic DocStore (`gauri_app/record/`, `gauri_app/core/doc_store.py`, `gauri_app/tools/record_tools.py`):**
  * Stores household-isolated canonical `.json` and human-readable `.md` profiles.
  * Supports non-governmental identification via uploaded photos and local names, with automatic file migration if a Pashudhan ID is added later.
  * Maintains deduplicated, append-only tables for **Vaccinations**, **Image Metadata**, **Health Conditions**, and **Conversation Logs**.
  * Automatically surfaces prioritized follow-up prompts for missing emergency fields (vet number, vaccination history, identification).
* **Phase 2 Agent Contracts (`gauri_app/orchestrator/stubs.py`):** Typed `TaskPayload` -> `AgentResponse` interfaces for `TRIAGE`, `HEALTH_CHECK`, `GENERAL_QUERY`, and the regional-language Behaviour Reply layer are already wired into the orchestrator loop.

## Repository Structure

```text
.
├── gauri_app/
│   ├── core/          # Schemas, deterministic safety gate, JSON/Markdown DocStore
│   ├── orchestrator/  # ADK router, session state management, Phase 2 stubs
│   ├── record/        # Record Agent prompt, examples, and runner
│   └── tools/         # Deterministic record lookup and upsert tools
├── demo_outputs/      # Sample 5-turn execution trace and generated Markdown animal record
├── requirements.txt
└── README.md
```

## Sample Verified Run (`demo_outputs/`)

A full 5-turn live trace is included in `demo_outputs/` demonstrating:

1. **Turn 1 (`RECORD`):** Registers a cow (`Ganga`), logs her FMD vaccination, vet number, and insurance status, and asks back for an identification photo.
2. **Turn 2 (`RECORD`):** Attaches an identification photo and updates Pashudhan ID status on the exact same animal record with zero duplicates.
3. **Turn 3 (`TRIAGE`):** Routes reduced appetite and dullness to the triage handler with `Ganga` pre-resolved.
4. **Turn 4 (`TRIAGE` + Safety Guard):** Flags an antibiotic/dosage request (`medication_requested: true`) and injects the non-prescription warning.
5. **Turn 5 (`EMERGENCY`):** Bypasses the LLM in `0.0s` on severe bloat and breathing distress, escalating to the 1962 helpline.

## Setup

```bash
pip install -r requirements.txt
```

The proof-of-concept runs locally with Ollama (`qwen2.5:7b`) via LiteLLM and Google ADK. Start your Ollama server and pull `qwen2.5:7b` before running the notebook or orchestrator.