import os

def gemini_text(system: str, prompt: str, model: str = "gemini-2.0-flash") -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai
    client = genai.Client(api_key=api_key)

    full = f"{system}\n\n{prompt}"
    resp = client.models.generate_content(model=model, contents=full)
    return resp.text or ""