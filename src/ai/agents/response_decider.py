from typing import Optional


from langchain_core.language_models.llms import LLM

from ai.gemini_integration import generate_reply
from core.logger import log


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
    previous_messages: str, current_message: str, guild_context: str, author: str, custom_context: str
) -> bool:
    """Use an LLM to decide if the bot should reply."""
    prompt = f"""<system>
You are a decision-making system for HollowBot, a Hollow Knight Discord bot.
Your job is to determine if HollowBot should respond to a message.
</system>

<context>
{f"Server context: {custom_context}" if custom_context else "No special server context."}
{f"Recent activity: {guild_context}" if guild_context and guild_context != "No updates yet today." else "No recent Hollow Knight activity."}
</context>

<conversation>
{previous_messages if previous_messages != "No previous messages." else "No previous conversation."}
</conversation>

<message>
{current_message}
</message>

<instructions>
Should HollowBot respond to this message? Consider:
- Is this a direct question or mention of HollowBot?
- Is this about Hollow Knight progress or gaming?
- Would a response add value to the conversation?
- Has HollowBot already responded recently in this conversation?
- Is this just casual chat that doesn't need a response?

Answer only "yes" or "no".
</instructions>"""
    
    try:
        decision = _llm.invoke(prompt).strip().lower()
        return decision.startswith("y")
    except Exception as e:  # pragma: no cover - LLM call failures
        log.error(f"Response decider failed: {e}")
        return False
