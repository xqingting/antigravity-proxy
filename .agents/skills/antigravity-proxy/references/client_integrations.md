# Client Integrations Reference

This document provides copy-paste integration guides for popular IDEs, tools, and libraries.

---

## 1. Cursor & Windsurf
1. Open Cursor Settings -> **Models**.
2. Enable **OpenAI API Key**.
3. Set **Base URL**: `http://127.0.0.1:8765/v1`
4. Set **API Key**: `sk-antigravity-local`
5. Under Model list, add `gemini-3.8-flash` (or keep `gpt-4o` as the proxy automatically remaps aliases).

---

## 2. Continue (VS Code & JetBrains)
Add the following to your `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Antigravity Gemini 3.8 Flash",
      "provider": "openai",
      "model": "gemini-3.8-flash",
      "apiBase": "http://127.0.0.1:8765/v1",
      "apiKey": "sk-antigravity-local"
    }
  ]
}
```

---

## 3. NextChat (ChatGPT-Next-Web)
1. Open Settings -> **Model Provider**: `OpenAI`.
2. **API Endpoint**: `http://127.0.0.1:8765`
3. **API Key**: `sk-antigravity-local`
4. **Custom Models**: Add `+gemini-3.8-flash`.

---

## 4. ChatBox
1. Settings -> **Model Provider**: `OpenAI API`.
2. **API Host**: `http://127.0.0.1:8765`
3. **API Key**: `sk-antigravity-local`
4. **Model**: `gemini-3.8-flash`

---

## 5. Official Python `openai` SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8765/v1",
    api_key="sk-antigravity-local",
)

# Streaming completion
response = client.chat.completions.create(
    model="gemini-3.8-flash",
    messages=[{"role": "user", "content": "Hello! Introduce yourself."}],
    stream=True,
)

for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
print()
```

---

## 6. LangChain & LlamaIndex

### LangChain
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://127.0.0.1:8765/v1",
    api_key="sk-antigravity-local",
    model="gemini-3.8-flash",
)

print(llm.invoke("What is Antigravity?").content)
```
