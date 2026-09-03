# API Reference

Antigravity Proxy exposes standard OpenAI-compatible endpoints on `http://127.0.0.1:8765`:

---

## 1. `POST /v1/chat/completions`
Standard OpenAI Chat Completions API.

### Request Headers
- `Content-Type: application/json`
- `Authorization: Bearer <any_key>` (Optional, non-enforcing)

### Request Body
```json
{
  "model": "gemini-3.8-flash",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"}
  ],
  "stream": true,
  "response_format": {"type": "text"}
}
```

### Response
- When `stream: false`: returns standard OpenAI `chat.completion` JSON.
- When `stream: true`: returns SSE `data: {"choices": [{"delta": {"content": "..."}}]}\n\n` ending with `data: [DONE]\n\n`.

---

## 2. `GET /v1/models`
Returns list of available models including native IDs and mapped aliases:
- `gemini-3.8-flash`
- `gemini-3.7-flash`
- `antigravity`
- `gpt-4o` (Alias)
- `claude-3-5-sonnet` (Alias)

---

## 3. `GET /v1/stats`
Returns live performance and usage statistics:
```json
{
  "total_requests": 14,
  "successful_requests": 13,
  "failed_requests": 1,
  "success_rate": 92.9,
  "active_requests": 0,
  "max_concurrency": 5,
  "total_prompt_tokens": 204600,
  "total_completion_tokens": 36200,
  "total_tokens": 240800,
  "avg_duration": 21.3,
  "avg_tps": 130.8,
  "recent_history": [...]
}
```

---

## 4. `GET /health`
Liveness probe returning service status, `agy` binary path, and detected CLI version.
