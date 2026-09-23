"""Official Responses API adapter with only three read-only function tools."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from openai import AsyncOpenAI
from openai.types.responses import FunctionToolParam, ResponseInputParam
from openai.types.shared_params import Reasoning

from contracts.models import GetFileTool, SearchCodeTool
from reposcope.application.agent import ModelTurn, ToolCall


def _tool(name: str, description: str, schema: dict[str, object]) -> FunctionToolParam:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": schema,
        "strict": False,
    }


TOOLS = [
    _tool(
        "search_code",
        "Search the pinned repository generation.",
        SearchCodeTool.model_json_schema(),
    ),
    _tool(
        "get_file",
        "Read at most 200 lines of a pinned source file.",
        GetFileTool.model_json_schema(),
    ),
    _tool(
        "get_repository_summary",
        "Get pinned file, chunk and language counts.",
        {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string", "format": "uuid"},
                "generation_id": {"type": "string", "format": "uuid"},
            },
            "required": ["repository_id", "generation_id"],
            "additionalProperties": False,
        },
    ),
]


class OpenAIAgentProvider:
    model = "gpt-5.6-luna"

    def __init__(self, api_key: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=45.0)

    async def respond(self, history: list[dict[str, object]]) -> ModelTurn:
        response = await self.client.responses.create(
            model=self.model,
            input=cast(ResponseInputParam, history),
            tools=TOOLS,
            max_output_tokens=2000,
            reasoning=Reasoning(effort="low"),
            include=["reasoning.encrypted_content"],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "agent_final",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "citation_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["answer", "citation_ids"],
                        "additionalProperties": False,
                    },
                }
            },
            store=False,
        )
        if response.status != "completed":
            raise ValueError("Incomplete model response")
        calls = tuple(
            ToolCall(item.call_id, item.name, item.arguments)
            for item in response.output
            if item.type == "function_call"
        )
        usage = response.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        if calls:
            return ModelTurn(
                calls,
                None,
                (),
                input_tokens,
                output_tokens,
                tuple(
                    cast(dict[str, object], item.model_dump(exclude_none=True))
                    for item in response.output
                ),
            )
        try:
            result = json.loads(response.output_text)
            if not isinstance(result, dict):
                raise ValueError("Invalid model result")
            answer = result["answer"]
            raw_citations = result["citation_ids"]
            if not isinstance(answer, str) or not isinstance(raw_citations, list):
                raise ValueError("Invalid model result")
            citations = tuple(UUID(item) for item in raw_citations)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("Invalid model result") from None
        return ModelTurn((), answer, citations, input_tokens, output_tokens)

