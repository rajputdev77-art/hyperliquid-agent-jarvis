"""Agent factory — picks Gemini, Ollama, or Groq based on LLM_PROVIDER env var."""

from __future__ import annotations

from src.config_loader import CONFIG


def make_decision_maker(hyperliquid=None, model_override: str | None = None):
    """Return a decision maker matching the configured LLM_PROVIDER.

    - "gemini" — free cloud (Gemini Flash, 20 req/day on free tier)
    - "ollama" — local self-hosted (free forever, slow on ARM CPU)
    - "groq"   — fast cloud (Llama 3.3 70B, ~14k req/day free tier)
    """
    provider = (CONFIG.get("llm_provider") or "gemini").lower()
    if provider == "ollama":
        from src.agent.ollama_decision_maker import OllamaDecisionMaker
        return OllamaDecisionMaker(hyperliquid=hyperliquid, model_override=model_override)
    if provider == "groq":
        from src.agent.groq_decision_maker import GroqDecisionMaker
        return GroqDecisionMaker(hyperliquid=hyperliquid, model_override=model_override)
    if provider == "gemini":
        from src.agent.decision_maker import DecisionMaker
        return DecisionMaker(hyperliquid=hyperliquid, model_override=model_override)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'gemini', 'ollama', or 'groq'.")
