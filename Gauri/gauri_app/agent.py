"""ADK entry point exposing root_agent for `adk run` and `adk web`."""

from gauri_app.orchestrator.agent import GauriOrchestrator, router_agent

root_agent = router_agent

__all__ = ["root_agent", "GauriOrchestrator"]
