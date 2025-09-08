from __future__ import annotations

"""Utility module providing a LangChain conversation chain for HollowBot."""

import importlib
import os
import sys
from typing import Any, List, Optional

from gemini_integration import generate_reply


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
        return generate_reply(prompt)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - simple property
        return "gemini"


def build_chain() -> ConversationChain:
    """Return a conversation chain with persona seeded memory."""

    memory = ConversationBufferMemory()
    memory.chat_memory.add_ai_message(
        (
            "I am HollowBot, chronicler of Hallownest. I speak in a whimsical, "
            "in-universe tone, offering knowledge of the Hollow Knight world."
        )
    )
    return ConversationChain(llm=GeminiLLM(), memory=memory)


# Default chain instance used by the bot.
chain = build_chain()

__all__ = ["chain", "build_chain", "GeminiLLM"]
