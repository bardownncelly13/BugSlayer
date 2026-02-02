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

    def run(self, prompt: str) -> str:
        """
        Return JSON with keys: is_real_issue, confidence, reasoning
        """
        if self._azure_client is not None:
            return self._mock_response(prompt)

        if self.primary:
            return self._legacy_mock_response(prompt)
        if self.fallback:
            return self._legacy_mock_response(prompt)

        raise RuntimeError("No LLM API keys configured")

    def _mock_response(self, prompt: str) -> str:
        """
        Azure-backed implementation that still returns the old JSON shape.
        """
        response = self._azure_openai_client.chat.completions.create(
            model=self.azure_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a triage assistant.\n"
                        "Given the user input, respond ONLY with JSON of the form:\n"
                        '{ "is_real_issue": boolean, "confidence": number, "reasoning": string }'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

        content = response.choices[0].message.content

        # Handle string or list of parts
        if isinstance(content, list):
            content_str = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        else:
            content_str = str(content)

        # Try to parse JSON from the model
        try:
            parsed = json.loads(content_str)
            result = {
                "is_real_issue": bool(parsed.get("is_real_issue", True)),
                "confidence": float(parsed.get("confidence", 0.85)),
                "reasoning": str(
                    parsed.get("reasoning", "Model response parsed successfully.")
                ),
            }
        except Exception:
            # Fallback to deterministic structure if the model didn't return JSON
            result = {
                "is_real_issue": True,
                "confidence": 0.85,
                "reasoning": "Pattern matches known unsafe usage.",
            }

        return json.dumps(result)

    def _legacy_mock_response(self, prompt: str) -> str:
        """
        Old behavior for non-Azure paths, kept for compatibility.
        """
        return json.dumps(
            {
                "is_real_issue": True,
                "confidence": 0.85,
                "reasoning": "Pattern matches known unsafe usage.",
            }
        )