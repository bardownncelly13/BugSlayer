import os
from dotenv import load_dotenv
from google import genai

def main():
    # Load environment variables from .env file
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment.")

    # Create Gemini client
    client = genai.Client(api_key=api_key)

    # Make a simple test request
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Explain in simple terms how APIs work."
    )

    print("\n=== Gemini Response ===\n")
    print(response.text)

if __name__ == "__main__":
    main()
