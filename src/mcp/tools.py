from typing import Any, Dict
import asyncio
import uuid

# Mock Tools for the registry
async def web_search(state):
    state['data']['search'] = "Search results for " + state['input']
    return state

async def data_analyzer(state):
    state['data']['analysis'] = "Analyzed " + state['data'].get('search', 'nothing')
    return state

async def cognitive_summarizer(state):
    state['data']['summary'] = f"FINAL RESULT: {state['data'].get('analysis')}"
    return state

TOOL_REGISTRY = {
    "mcp_browser_search": web_search,
    "cognitive_analyzer": data_analyzer,
    "cognitive_summarizer": cognitive_summarizer
}
