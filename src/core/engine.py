import asyncio
import yaml
from typing import Any, Dict, List
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    input: str
    data: Dict[str, Any]
    history: List[str]
    status: str

class PlaybookCompiler:
    """Compiles YAML playbook definitions into LangGraph workflows."""
    def __init__(self, tool_registry: Dict[str, Any]):
        self.tool_registry = tool_registry

    def compile(self, yaml_config: str):
        config = yaml.safe_load(yaml_config)
        workflow = StateGraph(AgentState)
        
        nodes = config.get('nodes', [])
        for node in nodes:
            node_id = node['id']
            tool_name = node['tool']
            
            # FIX: Closure bug. Use default argument to capture value at definition time
            def make_node(t_name=tool_name): 
                async def node_func(state: AgentState):
                    tool_func = self.tool_registry.get(t_name)
                    if not tool_func:
                        state['status'] = f"error: tool {t_name} not found"
                        return state
                    return await tool_func(state)
                return node_func
            
            workflow.add_node(node_id, make_node())
        
        # Linear edges for PoC
        for i in range(len(nodes) - 1):
            workflow.add_edge(nodes[i]['id'], nodes[i+1]['id'])
        
        workflow.set_entry_point(nodes[0]['id'])
        workflow.add_edge(nodes[-1]['id'], END)
        
        return workflow.compile()

class SNOExecutor:
    """Handles the async execution of compiled playbooks."""
    def __init__(self):
        self.jobs = {} # job_id -> {"status": ..., "result": ...}

    async def run_job(self, job_id: str, graph, initial_input: str):
        try:
            self.jobs[job_id]["status"] = "running"
            initial_state = {
                "input": initial_input,
                "data": {},
                "history": [],
                "status": "starting"
            }
            
            final_state = await graph.ainvoke(initial_state)
            
            self.jobs[job_id]["status"] = "completed"
            self.jobs[job_id]["result"] = final_state['data'].get('summary', "No summary produced")
        except Exception as e:
            self.jobs[job_id]["status"] = f"failed: {str(e)}"
