"""English-only stub subagent handlers for testing Orchestrator delegation."""

from __future__ import annotations

from gauri_app.core.schemas import AgentResponse, AgentStatus, RouteType, TaskPayload


async def stub_record_agent(task: TaskPayload) -> AgentResponse:
    if not task.animal_ref and not task.animal_id:
        return AgentResponse(
            task_id=task.task_id,
            agent_name="record_agent_stub",
            status=AgentStatus.CLARIFICATION_REQUIRED,
            summary="Animal identity is required before staging a record update.",
            missing_fields=["animal_identity"],
            clarification_questions=[
                "Which animal (name, tag ID, or description) is this update about?"
            ],
        )

    return AgentResponse(
        task_id=task.task_id,
        agent_name="record_agent_stub",
        status=AgentStatus.SUCCESS,
        summary=f"[STUB] Updated record for '{task.animal_ref or task.animal_id}'.",
        data={"animal_ref": task.animal_ref, "note": task.english_description},
    )


async def stub_triage_agent(task: TaskPayload) -> AgentResponse:
    med_note = (
        " Remind owner that Gauri cannot prescribe drugs."
        if task.medication_requested
        else ""
    )
    return AgentResponse(
        task_id=task.task_id,
        agent_name="triage_agent_stub",
        status=AgentStatus.SUCCESS,
        summary=(
            f"[STUB] Triage assessed for '{task.animal_ref or 'unspecified animal'}'. "
            f"Vet Card drafted.{med_note}"
        ),
        data={"urgency": "MODERATE", "medication_requested": task.medication_requested},
    )


async def stub_health_check_agent(task: TaskPayload) -> AgentResponse:
    if not task.image_path:
        return AgentResponse(
            task_id=task.task_id,
            agent_name="health_check_agent_stub",
            status=AgentStatus.CLARIFICATION_REQUIRED,
            summary="No photograph attached for breed/BCS check.",
            missing_fields=["image_path"],
            clarification_questions=[
                "Please share a clear photo of the animal to check breed and body condition."
            ],
        )

    return AgentResponse(
        task_id=task.task_id,
        agent_name="health_check_agent_stub",
        status=AgentStatus.SUCCESS,
        summary=f"[STUB] Processed image '{task.image_path}' for breed and BCS.",
        data={"image_path": task.image_path},
    )


async def stub_general_query_agent(task: TaskPayload) -> AgentResponse:
    return AgentResponse(
        task_id=task.task_id,
        agent_name="general_query_stub",
        status=AgentStatus.SUCCESS,
        summary=f"[STUB] General dairy guidance retrieved for: {task.english_description}",
    )


async def stub_behaviour_reply(
    task: TaskPayload,
    agent_responses: list[AgentResponse],
    medication_requested: bool = False,
) -> str:
    """Placeholder English formatter (will be replaced by Behaviour Reply Agent later)."""
    for resp in agent_responses:
        if resp.status == AgentStatus.CLARIFICATION_REQUIRED and resp.clarification_questions:
            return " ".join(resp.clarification_questions)

    parts: list[str] = []
    if medication_requested:
        parts.append("Note: Gauri cannot recommend medicines, injections, or dosages.")

    if task.intent == RouteType.OUT_OF_SCOPE:
        parts.append(
            "This request is outside Gauri's scope. Please ask about dairy animal care or records, "
            "or contact a local veterinarian for medications."
        )
        return " ".join(parts)

    summaries = "; ".join(r.summary for r in agent_responses)
    parts.append(summaries)

    reminders: list[str] = []
    for r in agent_responses:
        reminders.extend(r.data.get("followup_reminders") or [])
    if reminders:
        parts.append("Follow-up questions: " + " | ".join(reminders[:2]))

    return " ".join(parts)


DEFAULT_STUB_HANDLERS = {
    RouteType.RECORD: stub_record_agent,
    RouteType.TRIAGE: stub_triage_agent,
    RouteType.HEALTH_CHECK: stub_health_check_agent,
    RouteType.GENERAL_QUERY: stub_general_query_agent,
}
