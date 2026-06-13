"""
SNO AI Planner — v2.0  ✨ NEW FEATURE ✨

The Planner bridges natural language goals from the Hermes Agent and
the deterministic YAML Playbook format understood by the SNO Engine.

Given a high-level goal in plain language, the Planner:
  1. Calls an LLM (OpenAI or Anthropic) to generate a structured playbook.
  2. Validates the output against the PlaybookDefinition schema.
  3. Persists the generated file to the playbooks directory.
  4. Returns the playbook ID for immediate execution.

This closes the loop: Hermes can now say "research the competitive landscape"
and SNO will automatically plan AND execute a complete multi-step workflow —
no human-written YAML required.

Architecture note:
  The Planner is intentionally kept simple (single LLM call + schema validation).
  For production, upgrade to a multi-step ReAct loop that can self-correct.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import ValidationError

from src.config import settings
from src.core.engine import PlaybookDefinition
from src.utils.logger import get_logger

logger = get_logger("core.planner")

# ── Prompt Template ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are the SNO Playbook Planner. Your job is to convert a user's goal into a
    valid SNO Playbook YAML that the Sovereign Nexus Orchestrator can execute.

    PLAYBOOK SCHEMA:
    ----------------
    id: <snake_case_unique_id>            # Required. No spaces.
    name: <Human Readable Name>           # Required.
    description: <What this playbook does>  # Required.
    version: "1.0"                        # Required.
    timeout_seconds: 300                  # Required integer.
    nodes:                                # Required. At least 1 node.
      - id: <snake_case_node_id>          # Required. Unique within playbook.
        description: <What this step does>  # Required.
        action: <action_type>             # Required. See actions below.
        params:                           # Optional key-value pairs.
          key: value
        next: <other_node_id or omit>     # Optional. Defaults to next node.

    AVAILABLE ACTIONS:
    ------------------
    - web_search       params: query (str)
    - llm_summarize    params: context (str), instruction (str)
    - memory_store     params: content (str), tags (list[str])
    - memory_retrieve  params: query (str), top_k (int, default=5)
    - code_execute     params: code (str), language (str, default=python)
    - http_request     params: url (str), method (str, default=GET)
    - log              params: message (str)                   [default, always works]
    - wait             params: seconds (int)

    RULES:
    ------
    1. Return ONLY valid YAML. No markdown fences, no explanation text.
    2. Each node id must be unique and snake_case.
    3. Use 3–8 nodes for most goals. Max 15 nodes.
    4. The last node should have no 'next' field (it routes to END automatically).
    5. Make the playbook goal-specific — not generic.
""")

_USER_PROMPT_TEMPLATE = """\
Goal: {goal}

Additional context: {context}

Generate a SNO Playbook YAML for this goal. Return ONLY the YAML, no other text.
"""


# ── LLM Adapter Interface ─────────────────────────────────────────────────────

async def _call_openai(goal: str, context: str) -> str:
    """Call OpenAI Chat Completions API."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured. Set it in .env.")

    payload = {
        "model": settings.default_llm_model,
        "max_tokens": settings.planner_max_tokens,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_PROMPT_TEMPLATE.format(goal=goal, context=context),
            },
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def _call_anthropic(goal: str, context: str) -> str:
    """Call Anthropic Messages API."""
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured. Set it in .env.")

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": settings.planner_max_tokens,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": _USER_PROMPT_TEMPLATE.format(goal=goal, context=context),
            },
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"].strip()


# ── Main Planner ─────────────────────────────────────────────────────────────

class AIPlaybookPlanner:
    """
    Generates, validates, and persists YAML Playbooks from natural-language goals.

    Usage:
        planner = AIPlaybookPlanner(playbooks_dir="./playbooks")
        result = await planner.generate(
            goal="Research the top 5 open-source vector databases and compare them",
            context="Focus on performance benchmarks and Python SDK quality",
        )
        # result = {"playbook_id": "compare_vector_dbs_001", "path": "...", "node_count": 6}
    """

    def __init__(self, playbooks_dir: str | Path):
        self._dir = Path(playbooks_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        goal: str,
        context: str = "",
        provider: str | None = None,
        save: bool = True,
    ) -> dict[str, Any]:
        """
        Generate a playbook from a natural language goal.

        Args:
            goal:     The high-level objective in plain English.
            context:  Optional additional context or constraints.
            provider: 'openai' | 'anthropic'. Falls back to settings.default_llm_provider.
            save:     If True, persist the YAML to disk. If False, dry-run only.

        Returns:
            dict with keys: playbook_id, yaml_content, path (if saved), node_count, validated.
        """
        _provider = provider or settings.default_llm_provider
        logger.info(f"Generating playbook via {_provider} for goal: '{goal[:80]}…'")

        # Step 1: Call LLM
        try:
            if _provider == "anthropic":
                raw_yaml = await _call_anthropic(goal, context)
            else:
                raw_yaml = await _call_openai(goal, context)
        except Exception as exc:
            logger.error(f"LLM call failed: {exc}")
            raise RuntimeError(f"Playbook generation failed ({_provider}): {exc}") from exc

        # Step 2: Validate schema
        validated = False
        pb_def: PlaybookDefinition | None = None
        try:
            data = yaml.safe_load(raw_yaml)
            pb_def = PlaybookDefinition(**data)
            validated = True
            logger.info(
                f"Validation passed — id='{pb_def.id}', nodes={len(pb_def.nodes)}"
            )
        except (yaml.YAMLError, ValidationError, Exception) as exc:
            logger.warning(f"Generated YAML failed schema validation: {exc}")
            # Still return the raw YAML so the caller can inspect and fix it.

        playbook_id = pb_def.id if pb_def else "unvalidated_playbook"
        result: dict[str, Any] = {
            "playbook_id": playbook_id,
            "yaml_content": raw_yaml,
            "node_count": len(pb_def.nodes) if pb_def else None,
            "validated": validated,
            "path": None,
        }

        # Step 3: Persist
        if save and validated and pb_def:
            save_path = self._dir / f"{playbook_id}.yaml"
            save_path.write_text(raw_yaml, encoding="utf-8")
            result["path"] = str(save_path)
            logger.info(f"Playbook saved to {save_path}")

        return result

    async def refine(self, playbook_id: str, feedback: str) -> dict[str, Any]:
        """
        Refine an existing playbook based on natural language feedback.
        Loads the current YAML, asks the LLM to improve it, and overwrites.
        """
        path = self._dir / f"{playbook_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Playbook '{playbook_id}' not found.")

        current_yaml = path.read_text(encoding="utf-8")
        refine_goal = (
            f"Improve this existing SNO Playbook based on the following feedback.\n\n"
            f"FEEDBACK: {feedback}\n\n"
            f"CURRENT PLAYBOOK:\n{current_yaml}"
        )
        return await self.generate(goal=refine_goal, save=True)