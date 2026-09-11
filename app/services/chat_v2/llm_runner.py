"""
LLM construction and the tool-calling audit loop for a single model.

Every LLM call in this file (each tool-loop turn AND the final structured
extraction) now has its token usage captured via `TokenUsageAccumulator`,
which is returned alongside the structured result so callers can persist it.
"""

from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from .constants import GEO_SYSTEM_PROMPT
from .schemas import UnifiedGEOResponse
from .token_usage import TokenUsageAccumulator
from .tools import GEO_TOOLS

_TOOLS_BY_NAME = {t.name: t for t in GEO_TOOLS}


def build_chat_model(model_name: str):
    """Instantiate the right LangChain chat model for a given LLMModels value,
    bound to the GEO tools so the model can actually call them."""

    if model_name == "GPT":
        base = ChatOpenAI(
            model="gpt-5-nano",
            temperature=0,
            reasoning_effort="low",
        )

    elif model_name == "GEMINI":
        base = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            thinking_budget=512,
        )

    else:
        base = ChatAnthropic(
            model="claude-haiku-4-5",
            temperature=1,
            # thinking={"type": "enabled", "budget_tokens": 1024},
            max_tokens_to_sample=16000,
        )

    return base.bind_tools(GEO_TOOLS)


def build_chat_model_no_tools(model_name: str):
    """Same as build_chat_model but without tools bound - used for the final
    structured-output pass after the tool-calling loop is done."""
    if model_name == "GPT":
        return ChatOpenAI(model="gpt-5-nano", temperature=0)
    if model_name == "GEMINI":
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    return ChatAnthropic(model="claude-haiku-4-5", temperature=0)


async def run_single_model_audit(
    model_name: str,
    user_prompt: str,
    search_keyword: str,
    max_tool_iterations: int = 5,
) -> tuple[Optional[UnifiedGEOResponse], TokenUsageAccumulator]:
    """
    Runs a real tool-calling loop: the model decides when/what to search for
    via geo_web_search / scrape_product_metadata, we execute those calls and
    feed the results back, and only once the model stops requesting tools do
    we ask for the final structured UnifiedGEOResponse.

    Returns (structured_response_or_None, token_usage_accumulator).
    """
    usage = TokenUsageAccumulator()

    seed_prompt = f"""{user_prompt}

Start by searching for: "{search_keyword}"
Use the geo_web_search and scrape_product_metadata tools as needed to find
real, verified competitor URLs, pricing, and product metadata before you
finalize your analysis. Do not stop after a single search if more queries
would materially improve the competitor/citation data.

CRITICAL URL CONSTRAINT:
Only use exact URLs returned by tool calls. Never fabricate, edit, or invent
URLs. If no verified URL is available, leave 'product_url' as an empty string "".
"""

    messages = [
        SystemMessage(content=GEO_SYSTEM_PROMPT),
        HumanMessage(content=seed_prompt),
    ]

    llm = build_chat_model(model_name)

    # --- Tool-calling loop ---
    for _ in range(max_tool_iterations):
        ai_message = await llm.ainvoke(messages)
        usage.add(ai_message)
        messages.append(ai_message)

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            tool_fn = _TOOLS_BY_NAME.get(call["name"])
            if tool_fn is None:
                tool_result = f"Error: unknown tool '{call['name']}'"
            else:
                try:
                    tool_result = tool_fn.invoke(call["args"])
                except Exception as tool_err:
                    tool_result = f"Tool '{call['name']}' failed: {tool_err}"

            messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=call["id"])
            )

    # --- Final structured extraction pass, using the full tool-augmented conversation ---
    # include_raw=True is required to get the underlying AIMessage (and thus
    # its usage_metadata) back - by default with_structured_output() only
    # returns the parsed pydantic object, discarding token usage entirely,
    # which is why the original code never had anything to persist.
    structured_llm = build_chat_model_no_tools(model_name).with_structured_output(
        UnifiedGEOResponse, include_raw=True
    )
    messages.append(
        HumanMessage(
            content=(
                "Based on everything above, produce the final UnifiedGEOResponse "
                "JSON now. Use only URLs that appeared in tool results."
            )
        )
    )

    raw_result = await structured_llm.ainvoke(messages)

    raw_message = raw_result.get("raw") if isinstance(raw_result, dict) else None
    if raw_message is not None:
        usage.add(raw_message)

    parsed = raw_result.get("parsed") if isinstance(raw_result, dict) else raw_result
    return parsed, usage
