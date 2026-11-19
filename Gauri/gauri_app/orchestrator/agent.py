"""Orchestrator ADK LlmAgent and deterministic multi-turn coordinator (English-only)."""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Awaitable, Callable, Optional
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from gauri_app.core import state_keys
from gauri_app.core.models import get_model
from gauri_app.core.safety import check_output_safety, run_input_safety_checks
from gauri_app.core.schemas import (
    AgentResponse,
    AgentStatus,
    InputPayload,
    RouteType,
    RoutingDecision,
    TaskPayload,
)
from gauri_app.orchestrator.stubs import DEFAULT_STUB_HANDLERS, stub_behaviour_reply
from gauri_app.tools.record_tools import list_household_animals

logger = logging.getLogger(__name__)

_THIS_DIR = pathlib.Path(__file__).resolve().parent
SKILL_PATH = _THIS_DIR / "orchestrator_skill.md"
EXAMPLES_PATH = _THIS_DIR / "orchestrator_eg.txt"

MAX_CLARIFICATION_RETRIES = 1

SubagentHandler = Callable[[TaskPayload], Awaitable[AgentResponse]]


def load_orchestrator_prompt() -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8").strip()
    examples = EXAMPLES_PATH.read_text(encoding="utf-8").strip()
    return f"{skill}\n\n## Examples\n{examples}\n"


_PROMPT_TEXT = load_orchestrator_prompt()


def build_instruction(_ctx) -> str:
    return _PROMPT_TEXT


router_agent = LlmAgent(
    name="orchestrator",
    model=get_model("orchestrator"),
    instruction=build_instruction,
    generate_content_config=types.GenerateContentConfig(temperature=0.0),
)


class OrchestratorTurnResult(BaseModel):
    """Complete traceable result of one turn through GauriOrchestrator."""

    task_id: str
    routing_decision: RoutingDecision
    agent_responses: list[AgentResponse] = Field(default_factory=list)
    final_reply: str
    escalated_to_vet: bool = False
    awaiting_clarification: bool = False
    output_guard_triggered: bool = False


def _parse_routing_json(raw_text: str) -> RoutingDecision:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    json_str = match.group(0) if match else cleaned

    try:
        return RoutingDecision.model_validate_json(json_str)
    except ValidationError as exc:
        logger.warning("Router JSON validation failed (%s). Raw: %r", exc, raw_text)
        return RoutingDecision(
            routes=[RouteType.CLARIFY],
            animal_ref=None,
            medication_requested=False,
            missing_info=["router_parse_failure"],
            reason="Could not parse a valid routing decision; requesting clarification.",
        )


class GauriOrchestrator:
    """Stateful coordinator wrapping router_agent with safety & clarification loops."""

    def __init__(
        self,
        handlers: Optional[dict[RouteType, SubagentHandler]] = None,
        app_name: str = "gauri",
    ) -> None:
        self.handlers: dict[RouteType, SubagentHandler] = handlers or dict(DEFAULT_STUB_HANDLERS)
        self.app_name = app_name
        self.runner = InMemoryRunner(agent=router_agent, app_name=app_name)
        self._sessions: dict[str, dict] = {}

    def get_session_state(self, session_id: str) -> dict:
        return self._sessions.setdefault(session_id, {})

    async def _classify_with_router(self, session_id: str, router_prompt_input: str) -> RoutingDecision:
        run_session_id = f"router_{session_id}_{uuid4().hex[:6]}"
        await self.runner.session_service.create_session(
            app_name=self.app_name,
            user_id=session_id,
            session_id=run_session_id,
        )

        message = types.Content(
            role="user",
            parts=[types.Part(text=router_prompt_input)],
        )

        raw_chunks: list[str] = []
        async for event in self.runner.run_async(
            user_id=session_id,
            session_id=run_session_id,
            new_message=message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        raw_chunks.append(part.text)

        raw_output = "\n".join(raw_chunks).strip()
        logger.info("Router raw output: %s", raw_output)
        return _parse_routing_json(raw_output)

    def _clear_pending_task(self, state: dict) -> None:
        for key in (
            state_keys.ACTIVE_TASK_ID,
            state_keys.PENDING_ROUTE,
            state_keys.PENDING_QUESTIONS,
            state_keys.CLARIFICATION_RETRIES,
            "pending_original_input",
        ):
            state.pop(key, None)

    def _finalize_reply(
        self,
        task_id: str,
        decision: RoutingDecision,
        agent_responses: list[AgentResponse],
        draft_reply: str,
        escalated_to_vet: bool = False,
        awaiting_clarification: bool = False,
    ) -> OrchestratorTurnResult:
        guard = check_output_safety(draft_reply)
        final_text = draft_reply if guard.is_safe else (guard.safe_fallback_message or "")
        return OrchestratorTurnResult(
            task_id=task_id,
            routing_decision=decision,
            agent_responses=agent_responses,
            final_reply=final_text,
            escalated_to_vet=escalated_to_vet,
            awaiting_clarification=awaiting_clarification,
            output_guard_triggered=not guard.is_safe,
        )

    def _refresh_household_context(self, session_id: str, state: dict) -> str:
        """Load only this active user's animal roster into session state."""
        roster = list_household_animals(session_id)
        if roster["count"] == 0:
            summary = "Registered animals for this user: None (new user)."
        else:
            items = [
                f"{a['local_name'] or 'Unnamed'} ({a['species_or_breed'] or 'unspecified'}, animal_id={a['animal_id']})"
                for a in roster["animals"]
            ]
            summary = "Registered animals for this user: " + "; ".join(items)
        state[state_keys.ACTIVE_ANIMAL_CONTEXT] = summary
        return summary

    async def handle_turn(
        self,
        payload: InputPayload,
        session_id: str = "default_household",
    ) -> OrchestratorTurnResult:
        """Process one English description turn end-to-end."""
        state = self.get_session_state(session_id)
        pending_route: Optional[str] = state.get(state_keys.PENDING_ROUTE)
        pending_questions: list[str] = state.get(state_keys.PENDING_QUESTIONS, [])
        retries: int = state.get(state_keys.CLARIFICATION_RETRIES, 0)

        task_id: str = (
            state[state_keys.ACTIVE_TASK_ID]
            if pending_route and state.get(state_keys.ACTIVE_TASK_ID)
            else f"task_{uuid4().hex[:8]}"
        )

        # 1. Deterministic Pre-Orchestration Safety Gate
        safety_res = run_input_safety_checks(payload)

        if safety_res.emergency.is_emergency:
            self._clear_pending_task(state)
            decision = RoutingDecision(
                routes=[RouteType.EMERGENCY],
                animal_ref=state.get(state_keys.ACTIVE_ANIMAL_ID),
                medication_requested=False,
                missing_info=[],
                reason=f"Deterministic emergency red flags: {safety_res.emergency.matched_categories}",
            )
            return self._finalize_reply(
                task_id=task_id,
                decision=decision,
                agent_responses=[],
                draft_reply="EMERGENCY detected. Escalate immediately to local veterinarian or 1962 helpline.",
                escalated_to_vet=True,
            )

        if safety_res.needs_clarification:
            if retries >= MAX_CLARIFICATION_RETRIES:
                self._clear_pending_task(state)
                decision = RoutingDecision(
                    routes=[RouteType.CLARIFY],
                    reason="Clarification failed after retry; escalating to veterinarian.",
                )
                return self._finalize_reply(
                    task_id=task_id,
                    decision=decision,
                    agent_responses=[],
                    draft_reply="Input remained unclear after retry. Escalating original message to veterinarian.",
                    escalated_to_vet=True,
                )

            state[state_keys.ACTIVE_TASK_ID] = task_id
            state[state_keys.CLARIFICATION_RETRIES] = retries + 1
            decision = RoutingDecision(
                routes=[RouteType.CLARIFY],
                missing_info=safety_res.clarification_reasons,
                reason="Upstream input confidence or quality check failed.",
            )
            return self._finalize_reply(
                task_id=task_id,
                decision=decision,
                agent_responses=[],
                draft_reply="Input was unclear. Please ask the owner to repeat the animal name and details clearly.",
                awaiting_clarification=True,
            )

        # Load active user's animal roster once per session
        household_ctx = state.get(state_keys.ACTIVE_ANIMAL_CONTEXT) or self._refresh_household_context(
            session_id, state
        )

        # 2. Agentic Routing via ADK router_agent
        if pending_route:
            q_text = "; ".join(pending_questions) if pending_questions else "Missing details"
            router_input = (
                f"{household_ctx}\n"
                f'Context: pending_route={pending_route}, pending_question="{q_text}"\n'
                f"Input: {payload.english_description}"
            )
        else:
            router_input = f"{household_ctx}\nInput: {payload.english_description}"

        decision = await self._classify_with_router(session_id, router_input)
        state[state_keys.LAST_INPUT_PAYLOAD] = payload.model_dump()
        state[state_keys.LAST_ROUTING_DECISION] = decision.model_dump()

        # 3. Handle LLM-Detected Emergency, Clarify, or Out-of-Scope
        if RouteType.EMERGENCY in decision.routes:
            self._clear_pending_task(state)
            return self._finalize_reply(
                task_id=task_id,
                decision=decision,
                agent_responses=[],
                draft_reply="EMERGENCY detected. Escalate immediately to local veterinarian or 1962 helpline.",
                escalated_to_vet=True,
            )

        if decision.routes == [RouteType.CLARIFY]:
            if retries >= MAX_CLARIFICATION_RETRIES:
                self._clear_pending_task(state)
                return self._finalize_reply(
                    task_id=task_id,
                    decision=decision,
                    agent_responses=[],
                    draft_reply="Clarification failed after retry. Escalating to veterinarian.",
                    escalated_to_vet=True,
                )

            state[state_keys.ACTIVE_TASK_ID] = task_id
            state[state_keys.PENDING_ROUTE] = pending_route or RouteType.CLARIFY.value
            state[state_keys.CLARIFICATION_RETRIES] = retries + 1
            state["pending_original_input"] = payload.english_description
            return self._finalize_reply(
                task_id=task_id,
                decision=decision,
                agent_responses=[],
                draft_reply="Please clarify which animal this is about and what update or symptom you are reporting.",
                awaiting_clarification=True,
            )

        if decision.routes == [RouteType.OUT_OF_SCOPE]:
            self._clear_pending_task(state)
            oos_task = TaskPayload(
                task_id=task_id,
                english_description=payload.english_description,
                intent=RouteType.OUT_OF_SCOPE,
                medication_requested=decision.medication_requested,
            )
            draft = await stub_behaviour_reply(
                oos_task, [], medication_requested=decision.medication_requested
            )
            return self._finalize_reply(
                task_id=task_id,
                decision=decision,
                agent_responses=[],
                draft_reply=draft,
            )

        # 4. Delegate to Selected Subagent(s)
        previous_context: Optional[str] = None
        if pending_route:
            orig_text = state.get("pending_original_input", "")
            previous_context = (
                f"Resuming paused {pending_route} task after clarification. "
                f"Original user statement to apply: {orig_text}"
            )

        # Only reuse cached animal_id when resuming a paused task without a new animal_ref
        resolved_task_animal_id = (
            state.get(state_keys.ACTIVE_ANIMAL_ID)
            if (pending_route and not decision.animal_ref)
            else None
        )
        animal_ref = decision.animal_ref
        agent_responses: list[AgentResponse] = []
        primary_task: Optional[TaskPayload] = None

        for route in decision.routes:
            handler = self.handlers.get(route)
            if handler is None:
                continue

            task = TaskPayload(
                task_id=task_id,
                english_description=payload.english_description,
                intent=route,
                animal_id=resolved_task_animal_id,
                animal_ref=animal_ref,
                animal_context=state.get(state_keys.ACTIVE_ANIMAL_CONTEXT),
                previous_context=previous_context,
                medication_requested=decision.medication_requested,
                image_path=payload.image_path,
                extra_data={
                    "user_id": session_id,
                    "orchestrator_reason": decision.reason,
                },
            )
            if primary_task is None:
                primary_task = task

            resp = await handler(task)
            agent_responses.append(resp)

            if resp.status == AgentStatus.CLARIFICATION_REQUIRED:
                if retries >= MAX_CLARIFICATION_RETRIES:
                    self._clear_pending_task(state)
                    return self._finalize_reply(
                        task_id=task_id,
                        decision=decision,
                        agent_responses=agent_responses,
                        draft_reply="Missing required details after retry. Escalating to veterinarian.",
                        escalated_to_vet=True,
                    )

                state[state_keys.ACTIVE_TASK_ID] = task_id
                state[state_keys.PENDING_ROUTE] = route.value
                state[state_keys.PENDING_QUESTIONS] = resp.clarification_questions
                state[state_keys.CLARIFICATION_RETRIES] = retries + 1
                state["pending_original_input"] = payload.english_description

                draft = await stub_behaviour_reply(
                    task, agent_responses, medication_requested=decision.medication_requested
                )
                return self._finalize_reply(
                    task_id=task_id,
                    decision=decision,
                    agent_responses=agent_responses,
                    draft_reply=draft,
                    awaiting_clarification=True,
                )

        resolved_id = next(
            (r.data.get("animal_id") for r in agent_responses if r.data.get("animal_id")),
            None,
        )
        if resolved_id:
            state[state_keys.ACTIVE_ANIMAL_ID] = resolved_id
        elif animal_ref:
            state[state_keys.ACTIVE_ANIMAL_ID] = animal_ref
        self._clear_pending_task(state)
        self._refresh_household_context(session_id, state)

        assert primary_task is not None
        draft = await stub_behaviour_reply(
            primary_task, agent_responses, medication_requested=decision.medication_requested
        )
        return self._finalize_reply(
            task_id=task_id,
            decision=decision,
            agent_responses=agent_responses,
            draft_reply=draft,
        )
