"""
Token usage extraction and accumulation.

This was dead code in the original module (`_extract_token_usage` was
defined but never called, so no token usage was ever persisted anywhere).
It's now used by `llm_runner.py` after every single LLM call - each tool-
loop turn AND the final structured-output call - and accumulated per model
run so it can be persisted on the ChatGEOAuditRecord.
"""

from dataclasses import dataclass, field


def extract_token_usage(message) -> dict[str, int]:
    """Best-effort extraction of token counts from a LangChain message,
    covering both the `usage_metadata` (newer, provider-agnostic) shape and
    the legacy `response_metadata.token_usage` / `.usage` shapes."""
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0

    usage_metadata = getattr(message, "usage_metadata", None)

    if usage_metadata:
        input_tokens = int(usage_metadata.get("input_tokens", 0) or 0)
        output_tokens = int(usage_metadata.get("output_tokens", 0) or 0)
        total_tokens = int(usage_metadata.get("total_tokens", 0) or 0)

    if not total_tokens:
        response_metadata = getattr(message, "response_metadata", {}) or {}
        token_usage = (
            response_metadata.get("token_usage") or response_metadata.get("usage") or {}
        )

        input_tokens = int(token_usage.get("prompt_tokens", input_tokens) or 0)
        output_tokens = int(token_usage.get("completion_tokens", output_tokens) or 0)
        total_tokens = int(
            token_usage.get("total_tokens", input_tokens + output_tokens) or 0
        )

    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


@dataclass
class TokenUsageAccumulator:
    """Sums token usage across every LLM call made during a single model's
    audit run (each tool-calling turn + the final structured-output call)."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    per_call: list[dict[str, int]] = field(default_factory=list)

    def add(self, message) -> None:
        usage = extract_token_usage(message)
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        self.total_tokens += usage["total_tokens"]
        self.call_count += 1
        self.per_call.append(usage)

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }
