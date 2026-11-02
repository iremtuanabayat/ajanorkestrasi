import json
import logging
from typing import Annotated
from typing import TypedDict
from operator import add

from app.database.models import Agent
from app.llm.ollama_provider import ollama

logger = logging.getLogger(__name__)


class OrchestraState(TypedDict, total=False):
    task_id: str
    user_input: str
    selected_agents: list[dict]
    current_agent: str
    messages: list[dict]
    agent_outputs: Annotated[list[dict], add]
    execution_steps: Annotated[list[dict], add]
    task_status: str
    final_result: str
    errors: list[str]
    model: str | None


async def _agent_node(state: OrchestraState, agent: dict) -> dict:
    logger.info("[AGENT] started agent=%s task=%s", agent["name"], state.get("task_id"))
    output = await ollama.chat(state["user_input"], agent["system_prompt"], state.get("model") or agent.get("model_name"))
    logger.info("[AGENT] output generated agent=%s chars=%d", agent["name"], len(output))
    result = {"agent_id": agent["id"], "agent_name": agent["name"], "output": output}
    step = {"agent_id": agent["id"], "agent_name": agent["name"], "status": "completed"}
    return {"agent_outputs": [result], "execution_steps": [step]}


async def _synthesis_node(state: OrchestraState) -> dict:
    synthesis_agent = next((agent for agent in state["selected_agents"] if "synthesis" in agent["name"].lower()), None)
    if not synthesis_agent:
        return {"final_result": "\n\n".join(f"### {item['agent_name']}\n{item['output']}" for item in state.get("agent_outputs", []))}
    evidence = "\n\n".join(f"{item['agent_name']}: {item['output']}" for item in state.get("agent_outputs", []))
    logger.info("[SYNTHESIS] started task=%s outputs=%d", state.get("task_id"), len(state.get("agent_outputs", [])))
    answer = await ollama.chat(f"User request: {state['user_input']}\n\nAgent findings:\n{evidence}\n\nSynthesize a single clear final response.", synthesis_agent["system_prompt"], state.get("model") or synthesis_agent.get("model_name"))
    if not answer.strip():
        raise RuntimeError("Synthesis model returned an empty response")
    logger.info("[SYNTHESIS] completed task=%s chars=%d", state.get("task_id"), len(answer))
    return {"current_agent": synthesis_agent["id"], "final_result": answer}


def build_workflow(agents: list[Agent]):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph is not installed. Run pip install -r requirements.txt") from exc
    if not agents:
        raise ValueError("No active agents are available for orchestration")
    graph = StateGraph(OrchestraState)
    runnable_agents = [agent for agent in agents if "synthesis" not in agent.name.lower()]
    if not runnable_agents:
        runnable_agents = agents[:1]
    for index, agent in enumerate(runnable_agents):
        node_name = f"agent_{index}"
        current = {
            "id": agent.id,
            "name": agent.name,
            "system_prompt": agent.system_prompt,
            "model_name": agent.model_name,
        }

        async def run_agent(state: OrchestraState, selected=current) -> dict:
            return await _agent_node(state, selected)

        graph.add_node(node_name, run_agent)
        graph.add_edge(START, node_name)
    graph.add_node("synthesis", _synthesis_node)
    for index in range(len(runnable_agents)):
        graph.add_edge(f"agent_{index}", "synthesis")
    graph.add_edge("synthesis", END)
    return graph.compile()


async def select_agents(user_input: str, agents: list[Agent], model: str | None = None) -> list[Agent]:
    """Ask the local supervisor to route a request; fall back to keyword matching."""
    if len(agents) <= 1:
        return agents
    catalog = [{"id": agent.id, "name": agent.name, "description": agent.description,
                "capabilities": agent.capabilities} for agent in agents]
    try:
        logger.info("[SUPERVISOR] analyzing task chars=%d agents=%d", len(user_input), len(catalog))
        raw = await ollama.chat(
            "Choose at least 2 useful specialist agents when the catalog has 2 or more, and no more than 3 specialists. "
            "Do not select a synthesis agent as a specialist. Return ONLY JSON: {\"agent_ids\":[...]} "
            f"Choose IDs from this catalog: {json.dumps(catalog, ensure_ascii=False)}\n"
            f"Request: {user_input}",
            "You are a task router. Select agents whose capabilities directly fit the task. Include a synthesis agent only if multiple agents are selected.",
            model,
        )
        parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        selected_ids = set(parsed.get("agent_ids", []))
        selected = [agent for agent in agents if agent.id in selected_ids]
        invalid_ids = selected_ids - {agent.id for agent in agents}
        if invalid_ids:
            logger.warning("[ROUTER] ignored unknown or inactive agent IDs count=%d", len(invalid_ids))
        synthesis = next((agent for agent in agents if "synthesis" in agent.name.lower()), None)
        specialists = [agent for agent in agents if "synthesis" not in agent.name.lower()]
        selected_specialists = [agent for agent in selected if "synthesis" not in agent.name.lower()]
        if len(selected_specialists) < min(2, len(specialists)):
            terms = set(user_input.lower().split())
            ranked = sorted((agent for agent in specialists if agent not in selected), key=lambda agent: sum(
                1 for word in (agent.name + " " + agent.description + " " + " ".join(agent.capabilities or [])).lower().split()
                if word.strip(".,:;!?()") in terms
            ), reverse=True)
            selected.extend(ranked[:max(0, min(2, len(specialists)) - len(selected_specialists))])
        if len([agent for agent in selected if "synthesis" not in agent.name.lower()]) > 1 and synthesis and synthesis not in selected:
            selected.append(synthesis)
        if selected:
            logger.info("[ROUTER] selected agents=%s", [agent.name for agent in selected[:4]])
            return selected[:4]
        logger.warning("[ROUTER] returned no valid active agent IDs; using capability keyword fallback")
    except Exception:
        logger.exception("[SUPERVISOR] local routing failed; using capability keyword fallback")
    terms = set(user_input.lower().split())
    specialists = [agent for agent in agents if "synthesis" not in agent.name.lower()]
    scored = sorted(specialists, key=lambda agent: sum(
        1 for word in (agent.name + " " + agent.description + " " + " ".join(agent.capabilities or [])).lower().split()
        if word.strip(".,:;!?()") in terms
    ), reverse=True)
    selected = scored[:min(3, len(scored))]
    synthesis = next((agent for agent in agents if "synthesis" in agent.name.lower()), None)
    if len(selected) > 1 and synthesis and synthesis not in selected:
        selected.append(synthesis)
    logger.info("[ROUTER] fallback selected agents=%s", [agent.name for agent in selected])
    return selected
