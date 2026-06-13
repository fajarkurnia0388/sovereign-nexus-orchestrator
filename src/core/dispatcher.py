"""
SNO Action Dispatcher — v2.0
Executes real actions defined in SNO Playbook nodes.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("core.dispatcher")


class ActionDispatcher:
    """
    Dispatches and executes node actions defined in playbooks.
    Resolves dynamic parameters referencing state values.
    """

    def __init__(self, nexus: Any = None):
        self.nexus = nexus

    async def dispatch(self, action: str, params: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """
        Execute an action with resolved parameters.

        Args:
            action: The action name (e.g. 'llm_summarize').
            params: Parameters defined in the playbook.
            state: The current LangGraph state.
        """
        logger.info(f"Executing action '{action}'")
        resolved_params = self._resolve_params(params, state)
        
        result_payload: dict[str, Any] = {
            "status": "completed",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            if action == "web_search":
                query = resolved_params.get("query", state.get("query", ""))
                # Mock web search returning structured payload
                logger.info(f"web_search query: '{query}'")
                result_payload["results"] = (
                    f"Search results for '{query}': Found references to SNO, Agentic OS, "
                    f"and Model Context Protocol. Cognitive systems are shifting towards "
                    f"deterministic playbooks for reliable execution."
                )

            elif action == "llm_summarize":
                context = resolved_params.get("context", "")
                instruction = resolved_params.get("instruction", "Summarise this content concisely.")
                if not context:
                    # Fallback to general state data if no explicit context
                    context = str({k: v for k, v in state.items() if not k.startswith("node_")})
                
                result_payload["summary"] = await self._call_llm(context, instruction)

            elif action == "memory_store":
                content = resolved_params.get("content", "")
                tags = resolved_params.get("tags", [])
                entity_name = resolved_params.get("entity_name", "")
                if self.nexus:
                    res = await self.nexus.store(content=content, tags=tags, entity_name=entity_name)
                    result_payload["doc_id"] = res.get("doc_id")
                    result_payload["entity_name"] = res.get("entity_name")
                else:
                    result_payload["warning"] = "Nexus not initialized. Mocked store."
                    import uuid
                    result_payload["doc_id"] = str(uuid.uuid4())[:8]

            elif action == "memory_retrieve":
                query = resolved_params.get("query", "")
                top_k = resolved_params.get("top_k", 5)
                if self.nexus:
                    res = await self.nexus.query(query, top_k=top_k)
                    result_payload["retrieved_knowledge"] = res
                else:
                    result_payload["warning"] = "Nexus not initialized. Mocked retrieve."
                    result_payload["retrieved_knowledge"] = {"query": query, "semantic_results": []}

            elif action == "http_request":
                url = resolved_params.get("url", "")
                method = resolved_params.get("method", "GET").upper()
                headers = resolved_params.get("headers", {})
                json_data = resolved_params.get("json", None)
                if not url:
                    raise ValueError("URL parameter is required for http_request")

                async with httpx.AsyncClient() as client:
                    resp = await client.request(method, url, headers=headers, json=json_data, timeout=15.0)
                    result_payload["status_code"] = resp.status_code
                    result_payload["response_text"] = resp.text[:2000]  # Cap response size

            elif action == "code_execute":
                code = resolved_params.get("code", "")
                if not code:
                    raise ValueError("Code parameter is required for code_execute")

                # Execute python code in an isolated scope
                loc = {"state": state}
                import sys
                from io import StringIO
                old_stdout = sys.stdout
                redirected = sys.stdout = StringIO()
                try:
                    exec(code, {"__builtins__": __builtins__}, loc)
                    sys.stdout = old_stdout
                    result_payload["stdout"] = redirected.getvalue()
                    result_payload["variables"] = {k: str(v) for k, v in loc.items() if k != "state" and not k.startswith("__")}
                except Exception as exc:
                    sys.stdout = old_stdout
                    raise exc

            elif action == "wait":
                seconds = int(resolved_params.get("seconds", 1))
                logger.info(f"Waiting for {seconds}s...")
                await asyncio.sleep(seconds)
                result_payload["waited_seconds"] = seconds

            elif action == "log":
                message = resolved_params.get("message", "")
                logger.info(f"[Playbook Log] {message}")
                result_payload["logged_message"] = message

            else:
                raise ValueError(f"Unknown action type: '{action}'")

        except Exception as exc:
            logger.error(f"Action '{action}' execution failed: {exc}")
            result_payload["status"] = "failed"
            result_payload["error"] = str(exc)

        return result_payload

    def _resolve_params(self, params: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively resolves parameter values containing template strings,
        e.g., "{query}" or "{node_step_1_result.results}".
        """
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                resolved[k] = self._resolve_string_template(v, state)
            elif isinstance(v, dict):
                resolved[k] = self._resolve_params(v, state)
            elif isinstance(v, list):
                resolved[k] = [self._resolve_string_template(item, state) if isinstance(item, str) else item for item in v]
            else:
                resolved[k] = v
        return resolved

    def _resolve_string_template(self, template: str, state: dict[str, Any]) -> str:
        """Helper to substitute variables like {query} or {node_id.key}."""
        def replacer(match):
            key = match.group(1).strip()
            # Handle nested dotted properties (e.g. node_step_1.results)
            if "." in key:
                parts = key.split(".")
                val = state
                for p in parts:
                    if isinstance(val, dict):
                        val = val.get(p)
                    else:
                        return match.group(0)
                return str(val) if val is not None else ""
            return str(state.get(key, ""))

        return re.sub(r"\{([^}]+)\}", replacer, template)

    async def _call_llm(self, context: str, instruction: str) -> str:
        """Call LLM provider for summarisation."""
        provider = settings.default_llm_provider
        model = settings.default_llm_model
        
        system_prompt = "You are the SNO Cognitive Summariser. Condense the context according to instructions."
        user_prompt = f"Instruction: {instruction}\n\nContext:\n{context}"

        if provider == "anthropic":
            if not settings.anthropic_api_key:
                return f"[Mock Summary - Anthropic key missing] Summarized: {context[:100]}..."
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"].strip()
        else:
            # Default to OpenAI
            if not settings.openai_api_key:
                return f"[Mock Summary - OpenAI key missing] Summarized: {context[:100]}..."
            payload = {
                "model": model,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
