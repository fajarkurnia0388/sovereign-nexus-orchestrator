import asyncio

async def web_search_tool(state):
    print(f"[SNO Execution] Searching web for: {state['input']}")
    await asyncio.sleep(2)
    state['data']['search_results'] = "Found high-level data about the topic."
    state['status'] = "data_collected"
    return state

async def cognitive_analyzer_tool(state):
    print("[SNO Execution] Analyzing collected data...")
    await asyncio.sleep(2)
    state['data']['analysis'] = "Analysis complete: Topic is growing at 10% CAGR."
    state['status'] = "analyzed"
    return state

async def cognitive_summarizer_tool(state):
    print("[SNO Execution] Summarizing for Hermes...")
    await asyncio.sleep(1)
    state['data']['summary'] = f"FINAL SUMMARY: {state['data'].get('analysis')}"
    state['status'] = "completed"
    return state

# The Single Source of Truth
TOOL_REGISTRY = {
    "mcp_browser_search": web_search_tool,
    "cognitive_analyzer": cognitive_analyzer_tool,
    "cognitive_summarizer": cognitive_summarizer_tool
}
