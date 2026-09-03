---
name: antigravity-proxy
description: >-
  Manage, run, troubleshoot, and integrate Antigravity Proxy (the local OpenAI-compatible API bridge for Google Antigravity CLI / agy).
  Load this skill when the user asks to start, stop, restart, or check the status/stats of Antigravity Proxy,
  or when configuring third-party AI clients (Cursor, NextChat, ChatBox, Continue, Cherry Studio, OpenAI SDK) to route through local Antigravity.
references:
  - client_integrations
  - api_reference
  - architecture_and_security
---

# Antigravity Proxy Skill

This skill guides you (the AI agent) in managing, configuring, testing, and troubleshooting **Antigravity Proxy**—the official local bridge converting the Google Antigravity native CLI (`agy`) into a standard OpenAI Chat Completions API (`http://127.0.0.1:8765/v1`).

---

## 🎯 When to Activate This Skill

Activate this skill whenever the user prompt involves:
- Starting, stopping, restarting, or inspecting the status of the local Antigravity Proxy server.
- Checking proxy token consumption, requests count, average TPS speed, or active queue count (`GET /v1/stats` or `GET /health`).
- Connecting an external AI client (Cursor, VS Code Continue, NextChat, ChatBox, Cherry Studio, LangChain, or Python OpenAI SDK) to the local proxy.
- Diagnosing proxy issues (e.g., port 8765 occupied, `agy` binary not found, 429 concurrency errors, timeouts).

---

## 🛠️ Quick Decision Matrix

| User Goal | Action to Take | Primary Script / Endpoint |
| :--- | :--- | :--- |
| **Check if proxy is running** | Execute status probe | Run `scripts/status.sh` or `curl -s http://127.0.0.1:8765/health` |
| **Inspect token usage & stats** | Fetch stats snapshot | `curl -s http://127.0.0.1:8765/v1/stats` |
| **Start the proxy** | Launch in background | Run `scripts/start.sh` (or `start.bat` on Windows) |
| **Stop the proxy** | Terminate process safely | Run `scripts/stop.sh` (or `stop.bat` on Windows) |
| **Configure third-party app** | Provide OpenAI config | Point to [Client Integrations Reference](references/client_integrations.md) |
| **Test chat completion** | Verify streaming/blocking | Run `scripts/test.sh` |

---

## 📋 Operational Runbooks

### 1. Verification & Health Check

Always probe whether the proxy is currently listening on port 8765:

```bash
curl -s http://127.0.0.1:8765/health
```

**Expected Response**:
```json
{
  "status": "ok",
  "service": "antigravity-proxy",
  "default_model": "gemini-3.8-flash",
  "max_concurrency": 5,
  "agy_version": "1.1.25"
}
```

If it returns 200 OK, the proxy is active and ready.

---

### 2. Launching the Proxy

If the service is stopped, locate the proxy directory and launch it:

```bash
# Unix (macOS / Linux):
./start.sh

# Windows (Command Prompt / PowerShell):
start.bat
# or: .\start.ps1
```

**Custom parameters**:
```bash
python3 agy_proxy.py --port 8765 --model gemini-3.8-flash --effort high --max-concurrency 5
```

---

### 3. Client Configuration Standards

Any client supporting OpenAI API can connect using these standard credentials:

- **API Base URL**: `http://127.0.0.1:8765/v1`
- **API Key**: Any string (e.g., `sk-antigravity-local`)
- **Model ID**: `gemini-3.8-flash` *(or aliases `gpt-4o`, `claude-3-5-sonnet`)*

For IDE-specific snippets (Cursor, Continue, NextChat, Python SDK), read [references/client_integrations.md](references/client_integrations.md).

---

### 4. Troubleshooting Common Issues

1. **Port 8765 Already in Use**:
   - Run `lsof -i :8765` (or Windows `netstat -ano | findstr :8765`).
   - Execute `scripts/stop.sh` to release the port.
2. **`agy` CLI Not Found**:
   - Verify that `agy --version` works in the user's terminal.
   - Standard locations: `~/.local/bin/agy`, `/usr/local/bin/agy`, `~/.gemini/antigravity-cli/bin/agy`.
3. **429 Rate Limits Avoidance**:
   - Antigravity Proxy automatically enforces a 5-way semaphore (`--max-concurrency 5`). Excess requests smoothly queue in local memory.
