import yaml
import asyncio
from typing import Any, Dict, List, Optional
from langgraph.graph import StateGraph, END
from typing import TypedDict

class SNOState(TypedDict):
    input: str
    data: Dict[str, Any]
    history: List[str]
    status: str

class PlaybookCompiler:
    """Compiles YAML playbook definitions into LangGraph workflows."""
    
    def __init__(self, tool_registry: Dict[str, Any]):
        self.tool_registry = tool_registry

    def compile(self, yaml_path: str):
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        workflow = StateGraph(SNOState)
        nodes = config.get('nodes', [])
        
        for node in nodes:
            node_id = node['id']
            tool_name = node['tool']
            
            # Wrap the registered tool in a node function
            def make_node(t_name):
                async def node_func(state: SNOState):
                    tool_func = self.tool_registry.get(t_name)
                    if not tool_func:
                        raise ValueError(f"Tool {t_name} not found in registry")
                    return await tool_func(state)
                return node_func
            
            workflow.add_node(node_id, make_node(tool_name))

        # Establish Edges (Simple linear flow for PoC, can be expanded to conditional)
        for i in range(len(nodes) - 1):
            workflow.add_edge(nodes[i]['id'], nodes[i+1]['id'])
        
        workflow.set_entry_point(nodes[0]['id'])
        workflow.add_edge(nodes[-1]['id'], END)
        
        return workflow.compile()

class SNOExecutor:
    """Handles the async execution of compiled playbooks."""
    def __init__(self):
        self.active_jobs = {}

    async def execute(self, job_id: str, graph, initial_input: str):
        try:
            self.active_jobs[job_id] = {"status": "running", "result": None}
            initial_state = {"input": initial_input, "data": {}, "history": [], "status": "started"}
            
            final_state = await graph.ainvoke(initial_state)
            
            self.active_jobs[job_id] = {"status": "completed", "result": final_state.get('data', {}).get('summary')}
        except Exception as e:
            self.active_jobs[job_id] = {"status": "failed", "error": str(e)}
