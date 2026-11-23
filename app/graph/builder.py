from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.agents.governance_gate import governance_node
from app.agents.institutional_memory import memory_node
from app.agents.investigator import investigator_node
from app.agents.remediation import remediation_node
from app.agents.triage_router import triage_node
from app.observability.callbacks import audited
from app.resilience.guards import guarded
from app.schemas.state import IncidentState

MAX_STEPS = 10
AGENT_NAMES = ["investigator", "memory", "remediation", "governance"]

REAL_NODES = {
    "investigator": investigator_node,
    "memory": memory_node,
    "remediation": remediation_node,
    "governance": governance_node,
}


def make_placeholder(name):
    """Fallback stand-in if an agent is ever missing from REAL_NODES."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "completed": list(state.get("completed", [])) + [name],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    return node


def route_next(state: Dict[str, Any]) -> str:
    """Pick the next agent from triage.route, or stop."""
    if state.get("iteration_count", 0) >= MAX_STEPS:
        return END                      # loop protection
    done = state.get("completed", [])
    for agent in state["triage"]["route"]:
        if agent not in done:
            return agent
    return END


def build_graph(checkpointer=None):
    """A checkpointer is required for human approval (pause and resume).
    The default is in memory. Part C of Phase 10 swaps in PostgreSQL."""
    graph = StateGraph(IncidentState)

    graph.add_node("triage", audited("triage", triage_node))
    for name in AGENT_NAMES:
        node = REAL_NODES.get(name) or make_placeholder(name)
        graph.add_node(name, audited(name, guarded(name, node)))

    graph.add_edge(START, "triage")

    targets = {name: name for name in AGENT_NAMES}
    targets[END] = END
    for source in ["triage"] + AGENT_NAMES:
        graph.add_conditional_edges(source, route_next, targets)

    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)