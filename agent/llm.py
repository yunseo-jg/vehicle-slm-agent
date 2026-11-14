"""채팅 모델 만들기. 클라우드 ↔ 로컬 교체는 여기의 식별자만 바꾸면 된다.

식별자는 "provider:model" 형식. provider 는 openai | google | ollama.
    openai:gpt-4o-mini      google:gemini-2.5-flash      ollama:qwen3:4b
식별자를 안 주면 .env 의 LLM_PROVIDER, LLM_MODEL 을 쓴다.
"""

from __future__ import annotations

import os

PROVIDERS = ("openai", "google", "ollama")


def resolve_model_id(model_id: str | None = None) -> str:
    """ "provider:model" 로 정리한다. None 이면 환경 변수에서 읽는다."""
    if not model_id:
        provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        model = os.environ.get("LLM_MODEL", "").strip()
        if not provider or not model:
            raise SystemExit(".env 에 LLM_PROVIDER 와 LLM_MODEL 을 넣어 주세요 (.env.example 참고)")
        model_id = f"{provider}:{model}"
    provider, sep, model = model_id.partition(":")
    if not sep or not model or provider.lower() not in PROVIDERS:
        raise SystemExit(
            f"모델 식별자는 provider:model 형식이고 provider 는 {PROVIDERS} 중 하나: {model_id!r}"
        )
    return f"{provider.lower()}:{model}"


def make_llm(model_id: str | None = None, temperature: float = 0):
    """모델 식별자로 LangChain 채팅 모델을 만든다."""
    provider, _, model = resolve_model_id(model_id).partition(":")
    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model, temperature=temperature)
        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=model, temperature=temperature)
        from langchain_ollama import ChatOllama

        host = os.environ.get("OLLAMA_HOST")
        return ChatOllama(model=model, temperature=temperature, base_url=host)
    except ImportError as error:
        extra = "local" if provider == "ollama" else "cloud"
        message = f"{error.name} 가 없습니다. `uv sync --extra {extra}` 후 다시 실행"
        raise SystemExit(message) from error
