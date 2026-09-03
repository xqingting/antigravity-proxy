#!/bin/bash
PORT="${1:-8765}"
PROMPT="${2:-Hello, reply in one short sentence.}"

curl -s "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.8-flash",
    "messages": [{"role": "user", "content": "'"$PROMPT"'"}],
    "stream": false
  }'
