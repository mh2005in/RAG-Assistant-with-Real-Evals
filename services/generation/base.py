"""Common interface for text-generation backends (generation stage).

Every LLM client turns a fully-built prompt into a text completion. Keeping the
interface uniform lets the answering service stay backend-agnostic and lets evals
compare models (local Ollama, hosted APIs, ...) apples-to-apples (see CLAUDE.md).
"""

from typing import Protocol


class LLMClient(Protocol):
    """A text-generation backend: prompt in, completion out."""

    def generate(self, prompt: str) -> str:
        """Return the model's completion for ``prompt``."""
        ...
