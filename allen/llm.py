"""LLM provider abstraction. Default impl = Anthropic Claude (the 'company LLM'
is TBD long-term; swap here without touching the rest of ALLEN)."""

import logging
from typing import Protocol

from .config import settings

logger = logging.getLogger(__name__)

_CACHE_CONTROL = {"type": "ephemeral"}


def _cache_prefix(system, tools):
    """Return (system, tools) with a prompt-cache breakpoint on the stable prefix.

    The tool schemas + system prompt are byte-identical across the many calls in the daily
    brief and WhatsApp loops, so caching that prefix cuts repeated input-token cost by ~90%.
    Breakpoints cascade in the API's fixed order (tools → system → messages): marking the last
    tool caches the whole tool array; marking the last system block extends the cached prefix
    through the system prompt. Volatile content (the user turn, tool results) stays after the
    breakpoint and never invalidates the cache. Below the model's minimum cacheable length the
    API simply ignores the marker — so this is always safe to leave on.

    Copies are shallow and local; the shared ALLEN_TOOLS list is never mutated.
    """
    if not settings.prompt_cache_enabled:
        return system, tools

    sys_blocks = system
    if isinstance(system, str) and system:
        sys_blocks = [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]

    cached_tools = tools
    if tools:
        cached_tools = list(tools)
        last = dict(cached_tools[-1])
        last["cache_control"] = _CACHE_CONTROL
        cached_tools[-1] = last

    return sys_blocks, cached_tools


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...

    def complete_blocks(self, system: str, content: list, max_tokens: int = 2000) -> str: ...


class ClaudeProvider:
    def __init__(self) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def _log_usage(self, resp, project: str, namespace: str, feature: str) -> None:
        try:
            from . import usage

            u = getattr(resp, "usage", None)
            if u is not None:
                usage.log_llm(
                    u.input_tokens, u.output_tokens, self.model,
                    project=project or "rmg-ai", namespace=namespace or "", feature=feature or "chat",
                    cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                )
        except Exception:
            pass  # usage tracking must never break the actual response

    def complete(
        self, system: str, user: str, max_tokens: int = 2000,
        *, project: str = "rmg-ai", namespace: str = "", feature: str = "chat",
    ) -> str:
        sys_blocks, _ = _cache_prefix(system, None)
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=sys_blocks,
            messages=[{"role": "user", "content": user}],
        )
        self._log_usage(msg, project, namespace, feature)
        return "".join(block.text for block in msg.content if block.type == "text").strip()

    def complete_blocks(
        self, system: str, content: list, max_tokens: int = 2000,
        *, project: str = "rmg-ai", namespace: str = "", feature: str = "chat",
    ) -> str:
        """Multimodal turn — `content` is a list of Anthropic content blocks (text + image +
        document), so ALLEN can SEE images/PDFs/video frames, not just read text about them."""
        sys_blocks, _ = _cache_prefix(system, None)
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=sys_blocks,
            messages=[{"role": "user", "content": content}],
        )
        self._log_usage(msg, project, namespace, feature)
        return "".join(block.text for block in msg.content if block.type == "text").strip()

    def run_agent(
        self, system, messages, tools, tool_runner, max_rounds=6, max_tokens=1400,
        *, project: str = "rmg-ai", namespace: str = "", feature: str = "agent",
    ):
        """Run a tool-use loop. `tools` = Anthropic tool schemas; `tool_runner(name, input)->str`
        executes a tool call and returns the result text. Returns the model's final text once it
        stops calling tools (this is how ALLEN delegates to ALLIE, and ALLIE calls ClickUp/Notion)."""
        msgs = list(messages)
        last_text = ""
        system, tools = _cache_prefix(system, tools)
        for _ in range(max_rounds):
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system, messages=msgs, tools=tools,
            )
            self._log_usage(resp, project, namespace, feature)
            last_text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason != "tool_use":
                return last_text
            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    try:
                        out = tool_runner(block.name, block.input)
                    except Exception as exc:  # surface tool failure to the model, don't crash
                        logger.warning("tool %r failed: %s", block.name, exc)
                        out = f"(tool '{block.name}' failed: {exc})"
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out or "(no result)"})
            msgs.append({"role": "user", "content": results})
        return last_text or "(I worked on that but couldn't finish cleanly — try again.)"


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = ClaudeProvider()
    return _provider
