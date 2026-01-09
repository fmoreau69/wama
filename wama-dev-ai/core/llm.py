"""
WAMA Dev AI - LLM Client

Unified interface for Ollama LLM models with streaming support.
"""

import ollama
import logging
from typing import Optional, Generator, Dict, Any, List, Callable
from dataclasses import dataclass
import base64
from pathlib import Path
import json
import re

from config import OLLAMA_HOST, MODELS, ModelConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from an LLM query."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    success: bool = True
    error: Optional[str] = None


class LLMClient:
    """
    Ollama LLM client with streaming and multi-model support.

    Features:
    - Streaming responses for real-time output
    - Multiple model support (dev, debug, architect, vision)
    - Embeddings for semantic search
    - Image analysis with vision models
    - Structured output parsing (JSON, code blocks)
    """

    def __init__(self, host: str = OLLAMA_HOST):
        self._client = ollama.Client(host=host)
        self._host = host
        self._conversation_history: List[Dict] = []

    # =========================================================================
    # Basic Generation
    # =========================================================================

    def generate(
        self,
        prompt: str,
        model: str = "dev",
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Generate a response from the LLM.

        Args:
            prompt: The user prompt
            model: Model role ('dev', 'debug', 'architect') or Ollama model ID
            system_prompt: Optional system prompt
            temperature: Override default temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response

        Returns:
            LLMResponse with the generated content
        """
        # Resolve model config
        model_config = self._resolve_model(model)
        model_id = model_config.ollama_id
        temp = temperature if temperature is not None else model_config.temperature

        try:
            if stream:
                return self._generate_stream(
                    prompt, model_id, system_prompt, temp, max_tokens, model_config.name
                )
            else:
                return self._generate_sync(
                    prompt, model_id, system_prompt, temp, max_tokens, model_config.name
                )
        except Exception as e:
            return LLMResponse(
                content="",
                model=model_config.name,
                success=False,
                error=str(e)
            )

    def _generate_sync(
        self,
        prompt: str,
        model_id: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        model_name: str,
    ) -> LLMResponse:
        """Synchronous generation."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat(
            model=model_id,
            messages=messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        )

        return LLMResponse(
            content=response["message"]["content"],
            model=model_name,
            prompt_tokens=response.get("prompt_eval_count", 0),
            completion_tokens=response.get("eval_count", 0),
            total_tokens=response.get("prompt_eval_count", 0) + response.get("eval_count", 0),
        )

    def _generate_stream(
        self,
        prompt: str,
        model_id: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        model_name: str,
    ) -> LLMResponse:
        """Streaming generation (collects full response)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        full_response = ""
        for chunk in self._client.chat(
            model=model_id,
            messages=messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            stream=True
        ):
            if "message" in chunk:
                full_response += chunk["message"].get("content", "")

        return LLMResponse(
            content=full_response,
            model=model_name,
        )

    def stream(
        self,
        prompt: str,
        model: str = "dev",
        system_prompt: Optional[str] = None,
        callback: Optional[Callable[[str], None]] = None,
    ) -> Generator[str, None, None]:
        """
        Stream response chunks for real-time display.

        Args:
            prompt: The user prompt
            model: Model role or ID
            system_prompt: Optional system prompt
            callback: Optional callback for each chunk

        Yields:
            Response chunks as they arrive
        """
        model_config = self._resolve_model(model)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for chunk in self._client.chat(
            model=model_config.ollama_id,
            messages=messages,
            options={"temperature": model_config.temperature},
            stream=True
        ):
            if "message" in chunk:
                content = chunk["message"].get("content", "")
                if content:
                    if callback:
                        callback(content)
                    yield content

    # =========================================================================
    # Vision
    # =========================================================================

    def analyze_image(
        self,
        image_path: Path,
        prompt: str,
        model: str = "vision",
    ) -> LLMResponse:
        """
        Analyze an image using a vision model.

        Args:
            image_path: Path to the image file
            prompt: Analysis prompt
            model: Vision model to use

        Returns:
            LLMResponse with the analysis
        """
        model_config = self._resolve_model(model)

        # Load and encode image
        with open(image_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')

        response = self._client.chat(
            model=model_config.ollama_id,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [img_data]
            }]
        )

        return LLMResponse(
            content=response['message']['content'],
            model=model_config.name,
        )

    # =========================================================================
    # Embeddings
    # =========================================================================

    def embed(self, text: str, model: str = "embed") -> List[float]:
        """
        Generate embeddings for text.

        Args:
            text: Text to embed
            model: Embedding model to use

        Returns:
            List of embedding floats
        """
        model_config = self._resolve_model(model)
        logger.debug(f"Embedding text ({len(text)} chars) with {model_config.ollama_id}")

        response = self._client.embeddings(
            model=model_config.ollama_id,
            prompt=text
        )

        logger.debug(f"Embedding complete: {len(response['embedding'])} dimensions")
        return response["embedding"]

    def embed_batch(self, texts: List[str], model: str = "embed") -> List[List[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            model: Embedding model to use

        Returns:
            List of embedding vectors
        """
        return [self.embed(text, model) for text in texts]

    # =========================================================================
    # Structured Output
    # =========================================================================

    def generate_json(
        self,
        prompt: str,
        model: str = "dev",
        schema: Optional[Dict] = None,
    ) -> Dict:
        """
        Generate a JSON response.

        Args:
            prompt: Prompt asking for JSON output
            model: Model to use
            schema: Optional JSON schema for validation

        Returns:
            Parsed JSON dict
        """
        # Add JSON instruction to prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown or explanation."

        response = self.generate(json_prompt, model)

        # Extract JSON from response
        content = response.content.strip()

        # Try to find JSON in the response
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try array
        array_match = re.search(r'\[[\s\S]*\]', content)
        if array_match:
            try:
                return json.loads(array_match.group())
            except json.JSONDecodeError:
                pass

        # Return empty dict on failure
        return {}

    def extract_code(self, response: str, language: str = "python") -> str:
        """
        Extract code from a response that may contain markdown code blocks.

        Args:
            response: LLM response text
            language: Expected language

        Returns:
            Extracted code (or original if no blocks found)
        """
        # Try to find code block
        pattern = rf'```(?:{language})?\s*\n([\s\S]*?)\n```'
        match = re.search(pattern, response, re.IGNORECASE)

        if match:
            return match.group(1).strip()

        # Try generic code block
        generic_match = re.search(r'```\s*\n([\s\S]*?)\n```', response)
        if generic_match:
            return generic_match.group(1).strip()

        # Return as-is (might be raw code)
        return response.strip()

    # =========================================================================
    # Conversation
    # =========================================================================

    def chat(
        self,
        message: str,
        model: str = "dev",
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """
        Continue a conversation with history.

        Args:
            message: User message
            model: Model to use
            system_prompt: System prompt (only used if history is empty)

        Returns:
            LLMResponse with the assistant's reply
        """
        model_config = self._resolve_model(model)

        # Add system prompt if this is the first message
        if not self._conversation_history and system_prompt:
            self._conversation_history.append({
                "role": "system",
                "content": system_prompt
            })

        # Add user message
        self._conversation_history.append({
            "role": "user",
            "content": message
        })

        # Generate response
        response = self._client.chat(
            model=model_config.ollama_id,
            messages=self._conversation_history,
            options={"temperature": model_config.temperature}
        )

        assistant_message = response["message"]["content"]

        # Add assistant response to history
        self._conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return LLMResponse(
            content=assistant_message,
            model=model_config.name,
            prompt_tokens=response.get("prompt_eval_count", 0),
            completion_tokens=response.get("eval_count", 0),
        )

    def clear_history(self):
        """Clear conversation history."""
        self._conversation_history = []

    # =========================================================================
    # Utilities
    # =========================================================================

    def _resolve_model(self, model: str) -> ModelConfig:
        """Resolve a model name to its configuration."""
        if model in MODELS:
            return MODELS[model]

        # Assume it's a direct Ollama model ID
        return ModelConfig(
            name=model,
            ollama_id=model,
            description="Custom model",
        )

    def list_models(self) -> List[str]:
        """List available models on the Ollama server."""
        try:
            response = self._client.list()
            models = response.get("models", [])
            # Handle both old API (dict) and new API (object with .model attribute)
            result = []
            for m in models:
                if hasattr(m, 'model'):
                    result.append(m.model)
                elif isinstance(m, dict):
                    result.append(m.get("name", m.get("model", "")))
            return result
        except Exception:
            return []

    def check_model(self, model: str) -> bool:
        """Check if a model is available."""
        model_config = self._resolve_model(model)
        available = self.list_models()
        return model_config.ollama_id in available or any(
            model_config.ollama_id.split(":")[0] in m for m in available
        )
