# llm/client.py
import json
import os
import re

from openai import OpenAI


class LLMClient:
    def __init__(self):
        # self.endpoint = os.getenv("JP_ENDPOINT")
        # self.api_key = os.getenv("JP_API_KEY")
        # self.provider = os.getenv("JP_PROVIDER")
        # self.model = os.getenv("JP_MODEL")

        # TODO: UNCOMMENT when ready to test with real LLMs. For now, we want to be able to run the code without needing API keys.
        
        self.endpoint = os.getenv("TAMUS_AI_CHAT_API_ENDPOINT")
        self.api_key = os.getenv("TAMUS_AI_CHAT_API_KEY")
        self.model = os.getenv("TAMUS_AI_CHAT_MODEL", "protected.Claude Sonnet 4")
        self.client = None

        if self.endpoint and self.api_key:
            # TAMUS API expects calls at: {endpoint}/api/chat/completions.
            # OpenAI SDK appends /chat/completions, so we use {endpoint}/api as base_url.
            base_url = self.endpoint.rstrip("/") + "/api"
            self.client = OpenAI(api_key=self.api_key, base_url=base_url)

        # if not self.endpoint:
        #     raise ValueError("JP_ENDPOINT environment variable is not set")

        # if not self.api_key:
        #     raise ValueError("JP_API_KEY environment variable is not set")
        
        # if not self.provider:
        #     raise ValueError("JP_PROVIDER environment variable is not set")
        
        # if not self.model:
        #     raise ValueError("JP_MODEL environment variable is not set")


        # if self.provider == "azure":
        #     from openai import AzureOpenAI
        #     self.client = AzureOpenAI(
        #         api_key= self.api_key,
        #         azure_endpoint= self.endpoint,
        #         api_version="2024-10-21",
        #     )

        # elif self.provider == "openai":
        #     from openai import OpenAI
        #     self.client = OpenAI(api_key= self.api_key)

        # elif self.provider == "groq":
        #     from openai import OpenAI
        #     self.client = OpenAI(api_key= self.api_key, base_url= self.endpoint)

        # elif self.provider == "anthropic":
        #     from anthropic import Anthropic
        #     self.client = Anthropic(api_key= self.api_key)

    def run(self,system: str, prompt: str) -> str:
        """
        Return model output as text.

        If the prompt asks for JSON, normalize common model wrappers
        (like markdown code fences) so downstream json.loads() works.
        """
        if self.client is not None:
            raw = self._chat_response(system, prompt)
            return self._normalize_json_output(system, prompt, raw)

        #why do we have this? - ask 
        # if self.primary: 
        #     return self._legacy_mock_response(system, prompt)
        # if self.fallback:
        #     return self._legacy_mock_response(system, prompt)

        raise RuntimeError(
            "No LLM API keys configured. Set TAMUS_AI_CHAT_API_ENDPOINT and "
            "TAMUS_AI_CHAT_API_KEY."
        )

    def _chat_response(self, system: str, prompt: str) -> str:
        """
        TAMUS/Azure-backed implementation that returns raw model output.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            stream=False,
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

    @staticmethod
    def _normalize_json_output(system: str, prompt: str, raw: str) -> str:
        wants_json = "json" in (system + "\n" + prompt).lower()
        if not wants_json:
            return raw

        candidate = raw.strip()

        # Strip fenced blocks such as ```json ... ```.
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            candidate = fenced.group(1).strip()

        # Try direct parse first.
        try:
            parsed = json.loads(candidate)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            pass

        # Fall back to extracting the first JSON object/array substring.
        decoder = json.JSONDecoder()
        for i, ch in enumerate(candidate):
            if ch not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[i:])
                return json.dumps(parsed)
            except json.JSONDecodeError:
                continue

        return raw