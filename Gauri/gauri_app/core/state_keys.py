"""Central registry of all session-state keys used across Gauri."""

# Active task & clarification loop state
ACTIVE_TASK_ID = "active_task_id"
PENDING_ROUTE = "pending_route"
PENDING_QUESTIONS = "pending_questions"
CLARIFICATION_RETRIES = "clarification_retries"

# Resolved animal context for the current conversation
ACTIVE_ANIMAL_ID = "active_animal_id"
ACTIVE_ANIMAL_CONTEXT = "active_animal_context"

# Most recent turn artifacts (for auditing & resuming)
LAST_INPUT_PAYLOAD = "last_input_payload"
LAST_ROUTING_DECISION = "last_routing_decision"

# Staged record changes awaiting Entry Checker validation
STAGED_UPDATES = "staged_updates"

# Rolling summary of recent turns
INTERACTION_HISTORY = "interaction_history"
