"""LLM provider abstraction. Default impl = Anthropic Claude (the 'company LLM'
is TBD long-term; swap here without touching the rest of ALLEN)."""

from typing import Protocol

from .config import settings


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...

    def complete_blocks(self, system: str, content: list, max_tokens: int = 2000) -> str: ...


class ClaudeProvider:
    def __init__(self) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in msg.content if block.type == "text").strip()

    def complete_blocks(self, system: str, content: list, max_tokens: int = 2000) -> str:
        """Multimodal turn — `content` is a list of Anthropic content blocks (text + image +
        document), so ALLEN can SEE images/PDFs/video frames, not just read text about them."""
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return "".join(block.text for block in msg.content if block.type == "text").strip()

    def run_agent(self, system, messages, tools, tool_runner, max_rounds=6, max_tokens=1400):
        """Run a tool-use loop. `tools` = Anthropic tool schemas; `tool_runner(name, input)->str`
        executes a tool call and returns the result text. Returns the model's final text once it
        stops calling tools (this is how ALLEN delegates to ALLIE, and ALLIE calls ClickUp/Notion)."""
        msgs = list(messages)
        last_text = ""
        for _ in range(max_rounds):
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system, messages=msgs, tools=tools,
            )
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
