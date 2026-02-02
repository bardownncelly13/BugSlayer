from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

def test_api_call():
    project = AIProjectClient(
        endpoint="https://ryancoffman-5902-resource.services.ai.azure.com/api/projects/ryancoffman-5902",
        credential=DefaultAzureCredential(),
    )

    client = project.get_openai_client(api_version="2024-10-21")

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "You are a test system."},
            {"role": "user", "content": "Say hello and print 2+2."},
        ],
    )

    print("API RESPONSE:")
    print(response.choices[0].message.content)

if __name__ == "__main__":
    test_api_call()
