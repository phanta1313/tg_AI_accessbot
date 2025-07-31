import aiohttp

async def query_ollama(prompt: str):
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "accessbot_model",  
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            data = await response.json()
            return data.get("message", {}).get("content", "")