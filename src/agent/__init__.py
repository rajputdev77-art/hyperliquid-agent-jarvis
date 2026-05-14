"""Agent factory — picks Gemini or Ollama based on LLM_PROVIDER env var."""

from __future__ import annotations

from src.config_loader import CONFIG


def make_decision_maker(hyperliquid=None, model_override: str | None = None):
    """Return a decision maker matching the configured LLM_PROVIDER.

    - "gemini" (default, free cloud — used on laptop)
    - "ollama" (local self-hosted — used on Oracle Cloud, free forever)
    """
    provider = (CONFIG.get("llm_provider") or "gemini").lower()
    if provider == "ollama":
        from src.agent.ollama_decision_maker import OllamaDecisionMaker
        return OllamaDecisionMaker(hyperliquid=hyperliquid, model_override=model_override)
    if provider == "gemini":
        from src.agent.decision_maker import DecisionMaker
        return DecisionMaker(hyperliquid=hyperliquid, model_override=model_override)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'gemini' or 'ollama'.")
