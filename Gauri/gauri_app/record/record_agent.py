"""Record ADK LlmAgent and TaskPayload handler backed by record_tools (English-only)."""

from __future__ import annotations

import json
import logging
import pathlib
import re
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from gauri_app.core.models import get_model
from gauri_app.core.schemas import AgentResponse, AgentStatus, TaskPayload
from gauri_app.tools.record_tools import (
    find_animal,
    list_household_animals,
    read_animal_record,
    upsert_animal_record,
)

logger = logging.getLogger(__name__)

_THIS_DIR = pathlib.Path(__file__).resolve().parent
SKILL_PATH = _THIS_DIR / "record_skill.md"
EXAMPLES_PATH = _THIS_DIR / "record_eg.txt"


def load_record_prompt() -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8").strip()
    examples = EXAMPLES_PATH.read_text(encoding="utf-8").strip()
    return f"{skill}\n\n## Examples\n{examples}\n"


_PROMPT_TEXT = load_record_prompt()


def build_instruction(_ctx) -> str:
    return _PROMPT_TEXT


record_agent = LlmAgent(
    name="record_agent",
    model=get_model("record"),
    instruction=build_instruction,
    tools=[
        list_household_animals,
        find_animal,
        read_animal_record,
        upsert_animal_record,
    ],
    generate_content_config=types.GenerateContentConfig(temperature=0.0),
)

_RECORD_RUNNER = InMemoryRunner(agent=record_agent, app_name="gauri_record")


def _format_task_message(task: TaskPayload) -> str:
    user_id = task.extra_data.get("user_id", "default_household")
    lines = [
        "Task:",
        f"user_id: {user_id}",
        f"animal_id: {task.animal_id or 'null'}",
        f"animal_ref: {task.animal_ref or 'null'}",
        f"english_description: {task.english_description}",
        f"image_path: {task.image_path or 'null'}",
    ]
    if task.animal_context:
        lines.append(f"active_user_animals: {task.animal_context}")
    if task.previous_context:
        lines.append(f"previous_context: {task.previous_context}")
    if task.extra_data.get("orchestrator_reason"):
        lines.append(f"orchestrator_reason: {task.extra_data['orchestrator_reason']}")
    return "\n".join(lines)


def _parse_record_response(raw_text: str, task_id: str) -> AgentResponse:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    json_str = match.group(0) if match else cleaned

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Record Agent returned non-JSON output: %r", raw_text)
        return AgentResponse(
            task_id=task_id,
            agent_name="record_agent",
            status=AgentStatus.CLARIFICATION_REQUIRED,
            summary="Could not parse structured response from Record Agent.",
            clarification_questions=[
                "Could you please repeat the animal name and the details you want to record?"
            ],
        )

    raw_status = str(data.get("status", "SUCCESS")).upper()
    status = (
        AgentStatus.CLARIFICATION_REQUIRED
        if raw_status == "CLARIFICATION_REQUIRED"
        else AgentStatus.SUCCESS
    )

    return AgentResponse(
        task_id=task_id,
        agent_name="record_agent",
        status=status,
        summary=str(data.get("summary", "Record processed.")),
        clarification_questions=list(data.get("clarification_questions") or []),
        data={
            "animal_id": data.get("animal_id"),
            "action_taken": data.get("action_taken", "none"),
            "followup_reminders": list(data.get("followup_reminders") or []),
        },
    )


async def run_record_agent(task: TaskPayload) -> AgentResponse:
    user_id = str(task.extra_data.get("user_id", "default_household"))
    run_session_id = f"rec_{user_id}_{uuid4().hex[:6]}"

    await _RECORD_RUNNER.session_service.create_session(
        app_name="gauri_record",
        user_id=user_id,
        session_id=run_session_id,
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text=_format_task_message(task))],
    )

    raw_chunks: list[str] = []
    async for event in _RECORD_RUNNER.run_async(
        user_id=user_id,
        session_id=run_session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    raw_chunks.append(part.text)

    raw_output = "\n".join(raw_chunks).strip()
    logger.info("Record Agent raw output: %s", raw_output)
    return _parse_record_response(raw_output, task.task_id)
