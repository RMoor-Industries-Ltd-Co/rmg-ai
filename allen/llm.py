"""LLM provider abstraction. Default impl = Anthropic Claude (the 'company LLM'
is TBD long-term; swap here without touching the rest of ALLEN)."""

import logging
from typing import Protocol

from .config import settings

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...

    def complete_blocks(self, system: str, content: list, max_tokens: int = 2000) -> str: ...


class ClaudeProvider:
    def __init__(self) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model
        self.effort = (settings.anthropic_effort or "").strip()

    @staticmethod
    def _cached_system(system: str) -> list:
        """Wrap the system prompt as a cache-marked text block so the (large, mostly-static)
        system + tool prefix is written once and read from cache on later rounds/requests
        instead of re-billed in full. Below the model's min cacheable prefix it silently
        no-ops — no extra charge — so this is safe on small prompts too."""
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _cached_tools(tools: list) -> list:
        """Copy the tool list and mark the LAST tool for caching, so the whole tool payload
        (rendered before `system`) caches as one prefix. Copies rather than mutating the
        shared module-level TOOLS lists so the cache marker never leaks between call sites."""
        if not tools:
            return tools
        out = list(tools)
        last = dict(out[-1])
        last["cache_control"] = {"type": "ephemeral"}
        out[-1] = last
        return out

    def _create(self, **kwargs):
        """messages.create with the effort hint attached. If the running SDK or the target
        model doesn't accept output_config/effort, retry once without it rather than failing —
        keeps ALLEN responsive across SDK/model versions."""
        if self.effort:
            try:
                return self._client.messages.create(
                    output_config={"effort": self.effort}, **kwargs
                )
            except TypeError:
                pass  # SDK predates output_config kwarg
            except Exception as exc:  # model rejected effort (400) — fall back, else re-raise
                msg = str(exc).lower()
                if "output_config" not in msg and "effort" not in msg:
                    raise
                logger.warning("effort hint unsupported for %s, retrying without: %s", self.model, exc)
        return self._client.messages.create(**kwargs)

    def _log_usage(self, resp, project: str, namespace: str, feature: str) -> None:
        try:
            from . import usage

            u = getattr(resp, "usage", None)
            if u is not None:
                usage.log_llm(
                    u.input_tokens, u.output_tokens, self.model,
                    project=project or "rmg-ai", namespace=namespace or "", feature=feature or "chat",
                )
        except Exception:
            pass  # usage tracking must never break the actual response

    def complete(
        self, system: str, user: str, max_tokens: int = 2000,
        *, project: str = "rmg-ai", namespace: str = "", feature: str = "chat",
    ) -> str:
        msg = self._create(
            model=self.model,
            max_tokens=max_tokens,
            system=self._cached_system(system),
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
        msg = self._create(
            model=self.model,
            max_tokens=max_tokens,
            system=self._cached_system(system),
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
        cached_system = self._cached_system(system)
        cached_tools = self._cached_tools(tools)
        last_text = ""
        for _ in range(max_rounds):
            resp = self._create(
                model=self.model, max_tokens=max_tokens, system=cached_system, messages=msgs, tools=cached_tools,
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
