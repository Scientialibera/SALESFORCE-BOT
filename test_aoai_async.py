import asyncio
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncAzureOpenAI

async def main():
    # Get AAD token
    credential = DefaultAzureCredential()
    token = await credential.get_token("https://cognitiveservices.azure.com/.default")
    # Use the correct endpoint and deployment name
    endpoint = "https://salesforcebot-aoai-eastus2.openai.azure.com"
    deployment = "gpt-41-chat"
    api_version = "2024-02-15-preview"
    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_version=api_version,
        azure_ad_token=token.token,
    )
    try:
        response = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Tell me a joke."}
            ],
            temperature=0.7,
            max_tokens=100
        )
        print("RESPONSE:", response.choices[0].message.content)
    except Exception as e:
        print("ERROR:", e)
    finally:
        await credential.close()

if __name__ == "__main__":
    asyncio.run(main())
