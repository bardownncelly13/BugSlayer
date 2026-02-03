# llm/client.py
import os
import json
from typing import Optional

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential


class LLMClient:
    def __init__(self):
        self.primary = os.getenv("ANTHROPIC_API_KEY")
        self.fallback = os.getenv("OPENAI_API_KEY")

        self.azure_project_endpoint = (
            "https://ryancoffman-5902-resource.services.ai.azure.com/api/projects/ryancoffman-5902"
        )
        self.azure_api_version = "2024-10-21"
        self.azure_model = "gpt-4.1"

        self._azure_client: Optional[AIProjectClient] = AIProjectClient(
            endpoint=self.azure_project_endpoint,
            credential=DefaultAzureCredential(),
        )
        self._azure_openai_client = self._azure_client.get_openai_client(
            api_version=self.azure_api_version
        )

    def run(self,system: str, prompt: str) -> str:
        """
        Return JSON with keys: is_real_issue, confidence, reasoning
        """
        if self._azure_client is not None:
            return self._mock_response(system, prompt)

        if self.primary:
            return self._legacy_mock_response(system, prompt)
        if self.fallback:
            return self._legacy_mock_response(system, prompt)

        raise RuntimeError("No LLM API keys configured")

    def _mock_response(self, system: str, prompt: str) -> str:
        """
        Azure-backed implementation that returns raw model output.
        """
        response = self._azure_openai_client.chat.completions.create(
            model=self.azure_model,
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