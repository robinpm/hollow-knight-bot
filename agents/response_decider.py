from typing import Optional

from langchain_core.language_models.llms import LLM

from gemini_integration import generate_reply
from logger import log


class GeminiLLM(LLM):
    """LangChain LLM wrapper that uses our Gemini integration."""

    def _call(self, prompt: str, **kwargs: Optional[dict]) -> str:  # type: ignore[override]
        try:
            return generate_reply(prompt)
        except Exception as e:  # pragma: no cover - network/LLM errors
            log.error(f"GeminiLLM error: {e}")
            return "no"

    @property
    def _llm_type(self) -> str:
        return "gemini"


# Stateless LLM for response decisions
_llm = GeminiLLM()


def should_respond(
    recent: str, guild_context: str, author: str, custom_context: str
) -> bool:
    """Use an LLM to decide if the bot should reply."""
    preamble = f"{custom_context}\n" if custom_context else ""
    prompt = (
        f"{preamble}Recent conversation:\n{recent}\n\n"
        f"Recent updates from everyone:\n{guild_context}\n"
        f"The last message was from {author}. Should HollowBot reply? Answer yes or no."
    )
    try:
        decision = _llm.invoke(prompt).strip().lower()
        return decision.startswith("y")
    except Exception as e:  # pragma: no cover - LLM call failures
        log.error(f"Response decider failed: {e}")
        return False
