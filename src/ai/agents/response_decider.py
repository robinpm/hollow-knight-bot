from typing import Optional


from langchain_core.language_models.llms import LLM

from ai.gemini_integration import generate_reply
from core.logger import log


class GeminiLLM(LLM):
    """LangChain LLM wrapper that uses our Gemini integration."""

    def _call(self, prompt: str, **kwargs: Optional[dict]) -> str:  # type: ignore[override]
        try:
            from ai.gemini_integration import _gemini_client
            return _gemini_client.generate_content(prompt)
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
Should HollowBot respond to this message? 

ALWAYS respond if:
- The message directly mentions HollowBot, @Hollow-Bot, or "hollow bot"
- The message asks "are you there", "is hollow bot in here", "hello", "hi", or similar direct questions to the bot
- The message is about Hollow Knight progress, achievements, or gaming
- The message contains keywords like "hollow knight", "hallownest", "knight", "bug", "vessel", "progress", "save", "achievement", "boss", "area"
- The message is a question (ends with "?")
- The message is part of an active conversation with the bot

CONSIDER responding if:
- The message is casual but shows interest in the bot
- The message is short but engaging
- The user seems to be trying to interact with the bot

NEVER respond if:
- The message is just random chatter with no clear question or mention
- The message is clearly not directed at the bot and has no Hollow Knight relevance
- The message is spam or very low quality

Note: The system will handle consecutive response limits and keyword overrides automatically, so focus on the content and context quality.

Answer only "yes" or "no".
</instructions>"""
    
    try:
        decision = _llm.invoke(prompt).strip().lower()
        return decision.startswith("y")
    except Exception as e:  # pragma: no cover - LLM call failures
        log.error(f"Response decider failed: {e}")
        return False
