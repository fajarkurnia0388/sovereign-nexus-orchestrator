import asyncio
import yaml
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver 
from typing import TypedDict
from src.config import settings

class NodeSchema(BaseModel):
    id: str
    tool: str
    next: Optional[str] = None
    condition: Optional[Dict[str, str]] = None

class PlaybookSchema(BaseModel):
    playbook_id: str
    description: Optional[str] = ""
    nodes: List[NodeSchema]

class AgentState(TypedDict):
    input: str
    data: Dict[str, Any]
    history: List[str]
    status: str

class PlaybookCompiler:
    def __init__(self, tool_registry: Dict[str, Any]):
        self.tool_registry = tool_registry

    def compile(self, yaml_config: str):
        config_data = yaml.safe_load(yaml_config)
        pb = PlaybookSchema(**config_data)
        
        workflow = StateGraph(AgentState)
        
        for node in pb.nodes:
            def make_node(t_name=node.tool): # Fix: Closure capture
                async def node_func(state: AgentState):
                    tool_func = self.tool_registry.get(t_name)
                    if not tool_func:
                        state['status'] = f"error: tool {t_name} not found"
                        return state
                    return await tool_func(state)
                return node_func
            
            workflow.add_node(node.id, make_node())
        
        # Edges logic
        for node in pb.nodes:
            if node.next:
                workflow.add_edge(node.id, node.next)
            elif node.id == pb.nodes[-1].id:
                workflow.add_edge(node.id, END)
        
        # Fallback linear edges
        for i in range(len(pb.nodes) - 1):
            if not pb.nodes[i].next:
                workflow.add_edge(pb.nodes[i].id, pb.nodes[i+1].id)

        workflow.set_entry_point(pb.nodes[0].id)
        
        # FIX: Real Persistence using settings.DATABASE_URL
        # Remove 'sqlite:///' for SqliteSaver
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        memory = SqliteSaver.from_conn_string(db_path) 
        return workflow.compile(checkpointer=memory)

class SNOExecutor:
    def __init__(self):
        self.jobs = {}

    async def run_job(self, job_id: str, graph, initial_input: str):
        try:
            self.jobs[job_id] = {"status": "running", "result": None}
            # Use thread_id for LangGraph persistence
            config = {"configurable": {"thread_id": job_id}}
            
            initial_state = {
                "input": initial_input,
                "data": {},
                "history": [],
                "status": "started"
            }
            
            final_state = await graph.ainvoke(initial_state, config=config)
            
            self.jobs[job_id] = {
                "status": "completed", 
                "result": final_state['data'].get('summary', "No summary produced")
            }
        except Exception as e:
            self.jobs[job_id] = {"status": "failed", "error": str(e)}
