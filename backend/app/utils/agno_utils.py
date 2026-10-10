"""Shared ChatterMate model factory for the native Agno 3.x runtime."""

import re
from typing import Any, Dict, Optional

from fastapi import HTTPException
from agno.agent import Agent
from agno.models.openai import OpenAIChat

from app.core.logger import get_logger
from app.core.model_catalog import get_reasoning_strengths

logger = get_logger(__name__)


def create_model(
    model_type: str,
    api_key: str,
    model_name: str,
    max_tokens: int = 1000,
    response_format: Optional[Dict[str, Any]] = None,
    base_url: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
) -> Any:
    """Create a native Agno model for the configured ChatterMate provider."""
    model_type = model_type.upper()
    reasoning_strength = (reasoning_strength or "").strip().lower() or None
    if reasoning_strength and reasoning_strength not in get_reasoning_strengths(model_type, model_name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {model_type} has no qualified provider-native "
                f"reasoning strength {reasoning_strength!r}"
            ),
        )

    try:
        if model_type in {"OPENAI", "CHATTERMATE"}:
            kwargs = dict(api_key=api_key, id=model_name, max_tokens=max_tokens)
            if reasoning_strength:
                kwargs["reasoning_effort"] = reasoning_strength
            if response_format:
                kwargs["response_format"] = response_format
            return OpenAIChat(**kwargs)

        if model_type == "OPENAI_COMPATIBLE":
            if not base_url:
                raise ValueError("base_url is required for OPENAI_COMPATIBLE")
            normalized = re.sub(
                r"/chat/completions/?$", "", base_url.strip(), flags=re.IGNORECASE
            ).rstrip("/")
            kwargs = dict(
                api_key=api_key,
                id=model_name,
                base_url=normalized,
                max_tokens=max_tokens,
            )
            if response_format:
                kwargs["response_format"] = response_format
            return OpenAIChat(**kwargs)

        if model_type == "ANTHROPIC":
            from agno.models.anthropic import Claude
            return Claude(api_key=api_key, id=model_name, max_tokens=max_tokens)

        if model_type == "DEEPSEEK":
            from agno.models.deepseek import DeepSeek
            return DeepSeek(api_key=api_key, id=model_name, max_tokens=max_tokens)

        if model_type == "GOOGLE":
            from agno.models.google import Gemini
            return Gemini(
                api_key=api_key,
                id=model_name,
                max_output_tokens=max_tokens,
            )

        if model_type == "GOOGLEVERTEX":
            # Agno 3.x consolidated Google AI Studio and Vertex AI onto the
            # google-genai backed Gemini adapter. Vertex authentication remains
            # native (ADC/project/location); an explicitly configured key is
            # passed through for environments using Vertex express mode.
            from agno.models.google import Gemini
            kwargs = dict(
                id=model_name,
                max_output_tokens=max_tokens,
                vertexai=True,
            )
            if api_key:
                kwargs["api_key"] = api_key
            return Gemini(**kwargs)

        if model_type == "GROQ":
            from agno.models.groq import Groq
            # Groq structured replies are handled at the Agent layer by the
            # existing explicit json tool. Do not monkey-patch the 3.x model.
            return Groq(api_key=api_key, id=model_name, max_tokens=max_tokens)

        if model_type == "MISTRAL":
            from agno.models.mistral import MistralChat
            return MistralChat(api_key=api_key, id=model_name, max_tokens=max_tokens)

        if model_type == "HUGGINGFACE":
            from agno.models.huggingface import HuggingFace
            return HuggingFace(api_key=api_key, id=model_name, max_tokens=max_tokens)

        if model_type == "OLLAMA":
            from agno.models.ollama import Ollama
            return Ollama(id=model_name)

        if model_type == "XAI":
            from agno.models.xai import xAI
            return xAI(api_key=api_key, id=model_name, max_tokens=max_tokens)

        raise ValueError(f"Unsupported model type: {model_type}")

    except ImportError as exc:
        logger.error(f"Import error when creating model type {model_type}: {exc}")
        raise HTTPException(
            status_code=400,
            detail=f"Model type {model_type} is not available in this installation",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error creating model type {model_type}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize model: {exc}",
        ) from exc


async def test_model_api_key(
    api_key: str,
    model_type: str,
    model_name: str,
    base_url: Optional[str] = None,
) -> bool:
    """Test the configured provider through the same native Agent runtime."""
    try:
        model = create_model(
            model_type,
            api_key,
            model_name,
            base_url=base_url,
        )
        test_agent = Agent(
            name="Test Agent",
            model=model,
            instructions="You are a test agent. Just respond with 'Test successful.'",
            debug_mode=False,
        )
        await test_agent.arun("This is a test message.", stream=False)
        return True
    except Exception as exc:
        logger.error(f"API key test failed: {exc}")
        return False
