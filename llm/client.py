# llm/client.py
import os
import json
from typing import Optional

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential


class LLMClient:
    def __init__(self):
        self.endpoint = os.getenv("JP_ENDPOINT")
        self.api_key = os.getenv("JP_API_KEY")
        self.provider = os.getenv("JP_PROVIDER")
        self.model = os.getenv("JP_MODEL")

        if not self.endpoint:
            raise ValueError("JP_ENDPOINT environment variable is not set")

        if not self.api_key:
            raise ValueError("JP_API_KEY environment variable is not set")
        
        if not self.provider:
            raise ValueError("JP_PROVIDER environment variable is not set")
        
        if not self.model:
            raise ValueError("JP_MODEL environment variable is not set")


        if self.provider == "azure":
            from openai import AzureOpenAI
            self.client = AzureOpenAI(
                api_key= self.api_key,
                azure_endpoint= self.endpoint,
                api_version="2024-10-21",
            )

        elif self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key= self.api_key)

        elif self.provider == "groq":
            from openai import OpenAI
            self.client = OpenAI(api_key= self.api_key, base_url= self.endpoint)

        elif self.provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key= self.api_key)

    def run(self,system: str, prompt: str) -> str:
        """
        Return JSON with keys: is_real_issue, confidence, reasoning
        """
        if self.client is not None:
            return self._mock_response(system, prompt)

        #why do we have this? - ask 
        # if self.primary: 
        #     return self._legacy_mock_response(system, prompt)
        # if self.fallback:
        #     return self._legacy_mock_response(system, prompt)

        raise RuntimeError("No LLM API keys configured")

    def _mock_response(self, system: str, prompt: str) -> str:
        """
        Azure-backed implementation that returns raw model output.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )

        content = response.choices[0].message.content

        # Handle Azure returning list-style content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )

        return str(content)