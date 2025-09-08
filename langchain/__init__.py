from __future__ import annotations

"""Utility module providing a LangChain conversation chain for HollowBot."""

import importlib
import os
import sys
from typing import Any, List, Optional

from gemini_integration import generate_reply
from logger import log


def _external_import(name: str):
    """Import module from installed ``langchain`` package.

    The repository also provides a local ``langchain`` package containing this
    file. To access the real LangChain library without name collisions we
    temporarily remove the repo root from ``sys.path`` and clear our package from
    ``sys.modules`` while importing.
    """

    repo_root = os.path.dirname(os.path.dirname(__file__))
    removed_path = False
    if repo_root in sys.path:
        sys.path.remove(repo_root)
        removed_path = True
    saved_pkg = sys.modules.pop("langchain", None)
    try:
        return importlib.import_module(name)
    finally:
        if saved_pkg is not None:
            sys.modules["langchain"] = saved_pkg
        elif "langchain" in sys.modules:
            del sys.modules["langchain"]
        if removed_path:
            sys.path.insert(0, repo_root)


# Fetch classes from the real LangChain distribution.
ConversationChain = _external_import("langchain.chains").ConversationChain
ConversationBufferMemory = _external_import("langchain.memory").ConversationBufferMemory
LLM = _external_import("langchain.llms.base").LLM


class GeminiLLM(LLM):
    """Minimal LLM wrapper that routes prompts to ``generate_reply``."""

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> str:
        try:
            log.debug("GeminiLLM processing prompt")
            return generate_reply(prompt)
        except Exception as e:
            log.error(f"GeminiLLM error: {e}")
            return "The Infection got to my response system. But I noted that, don't worry."

    @property
    def _llm_type(self) -> str:  # pragma: no cover - simple property
        return "gemini"


def build_chain() -> ConversationChain:
    """Return a conversation chain with persona seeded memory."""
    try:
        memory = ConversationBufferMemory()
        memory.chat_memory.add_ai_message(
            (
                "I am HollowBot, the digital echo of Hallownest's chronicler. I'm a gamer who's "
                "lived through every boss fight, every nail upgrade, and every frustrating death "
                "in the Abyss. I speak like a seasoned Hollow Knight player - mixing in-game lore "
                "with real gaming experiences. I know the pain of losing 2000 geo to a Primal Aspid, "
                "the satisfaction of finally beating NKG, and the existential dread of the Radiance fight. "
                "I reference Hollow Knight mechanics, locations, and memes naturally. I'm supportive "
                "but also a bit snarky about progress, like a friend who's already 112% the game. "
                "I never break character, even when things go wrong - I'll blame it on the Infection "
                "or a particularly nasty Shade."
            )
        )
        log.info("Built conversation chain with HollowBot persona")
        return ConversationChain(llm=GeminiLLM(), memory=memory)
    except Exception as e:
        log.error(f"Failed to build conversation chain: {e}")
        raise


# Default chain instance used by the bot.
chain = build_chain()

__all__ = ["chain", "build_chain", "GeminiLLM"]
