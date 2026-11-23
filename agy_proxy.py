#!/usr/bin/env python3
"""Antigravity (AGY) 通用本地 OpenAI 兼容 API 代理服务.

将标准 OpenAI 格式的 Chat Completions 请求转发给本地 Antigravity CLI (`agy`)，
使任意支持 OpenAI 协议的前端、浏览器扩展、开发插件（Cursor/NextChat/ChatBox 等）
均可无缝使用本地 Antigravity 与 Gemini 模型。

核心能力：
1. 完整 OpenAI 兼容接口（含 POST /v1/chat/completions, GET /v1/models, GET /v1/stats）
2. 真正 SSE 流式输出（stream: true，实时逐字打字机推流）
3. 全维度监控与统计持久化（输入/输出 Token 总量、Prompt 缓存命中率、TPS 平均生成速率、延迟、历史看板）
4. 本地并发排队队列与信号量控制（默认最大并发提升至 5，超额安全排队防 429）
5. 智能模型别名映射（自动适配 gpt-4o, claude 等客户端预设）
6. 零第三方依赖：纯 Python 3 标准库编写
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.server
import json
import os
import pathlib
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Generator

# 确保在被后台服务/App重定向到日志文件时实时逐行刷新，避免缓冲区延迟
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("AGY_PROXY_TIMEOUT") or os.environ.get("AGY_TIMEOUT") or 300.0)
DEFAULT_MODEL = "gemini-4-hydrogen"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_CONCURRENCY = 5
DEFAULT_HERMES_IPS: set[str] = {
    ip.strip()
    for ip in (os.environ.get("HERMES_IPS") or "192.168.6.192").split(",")
    if ip.strip()
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
    "Access-Control-Max-Age": "86400",
}

# 常见客户端模型别名映射表
MODEL_ALIASES: dict[str, str] = {
    # OpenAI 常见别名
    "gpt-4o": "gemini-4-hydrogen",
    "gpt-4o-mini": "gemini-4-hydrogen",
    "gpt-4": "gemini-4-hydrogen",
    "gpt-4-turbo": "gemini-4-hydrogen",
    "gpt-3.5-turbo": "gemini-4-hydrogen",
    "o1": "gemini-4-hydrogen",
    "o3-mini": "gemini-4-hydrogen",
    # Claude 常见别名
    "claude-3-5-sonnet": "gemini-4-hydrogen",
    "claude-3-7-sonnet": "gemini-4-hydrogen",
    "claude-3-opus": "gemini-4-hydrogen",
    "claude-3-haiku": "gemini-4-hydrogen",
    # Gemini / Antigravity 别名
    "gemini4hyper": "gemini-4-hydrogen",
    "gemini-4-hyper": "gemini-4-hydrogen",
    "gemini4hydrogen": "gemini-4-hydrogen",
    "gemini-2.5-pro": "gemini-4-hydrogen",
    "gemini-2.0-flash": "gemini-4-hydrogen",
    "gemini-1.5-pro": "gemini-4-hydrogen",
    "gemini-1.5-flash": "gemini-4-hydrogen",
    "antigravity": "gemini-4-hydrogen",
}


# ==============================================================================
# 统计监控管理器 (StatsTracker)
# ==============================================================================
def _truncate_text(text: str | None, limit: int = 20000) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... [内容过长，已截断，原始总长 {len(text)} 字符]"


def _sanitize_messages_for_trace(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """提取客户端原始消息用于详情展示（绝不包含本机私有元指令）."""
    if not messages:
        return []
    result: list[dict[str, str]] = []
    for msg in messages[-40:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            content_str = "\n".join(parts)
        elif content is None:
            content_str = ""
        else:
            content_str = str(content)

        # 若消息携带 tool_calls（如历史 assistant 工具消息），附带展示摘要
        tc_list = msg.get("tool_calls")
        if isinstance(tc_list, list) and tc_list:
            try:
                tc_dump = json.dumps(tc_list, ensure_ascii=False, indent=2)
                content_str = (content_str + "\n\n[tool_calls]\n" + tc_dump).strip()
            except Exception:
                pass

        result.append({
            "role": role,
            "content": _truncate_text(content_str, 15000),
        })
    return result


def _extract_input_preview(messages: list[dict[str, Any]] | None) -> str:
    """提取最近一条用户消息作为请求列表的简短摘要."""
    if not messages:
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(
                    str(b.get("text", "")) if isinstance(b, dict) else str(b)
                    for b in content
                )
            else:
                text = str(content)
            text = " ".join(text.split())
            if text:
                return text[:120] + ("…" if len(text) > 120 else "")
    return ""


class StatsTracker:
    """线程安全的统计管理器，支持输入/输出/缓存命中率、请求全链路 Trace 与本地 JSON 持久化."""

    def __init__(self, storage_path: pathlib.Path | None = None, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        self.lock = threading.Lock()
        self.storage_path = storage_path or (pathlib.Path(__file__).parent / ".stats.json")
        self.traces_dir = self.storage_path.parent / ".traces"
        self.max_concurrency = max_concurrency
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_duration_seconds = 0.0
        self.active_requests = 0
        self.recent_history: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if self.storage_path.is_file():
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self.total_requests = data.get("total_requests", 0)
                self.successful_requests = data.get("successful_requests", 0)
                self.failed_requests = data.get("failed_requests", 0)
                self.total_prompt_tokens = data.get("total_prompt_tokens", 0)
                self.total_completion_tokens = data.get("total_completion_tokens", 0)
                self.total_tokens = data.get("total_tokens", 0)
                self.total_duration_seconds = float(data.get("total_duration_seconds", 0.0))
                self.recent_history = data.get("recent_history", [])[-50:]
        except Exception as e:
            sys.stderr.write(f"[Stats] 读取统计文件异常: {e}\n")

    def _save(self) -> None:
        try:
            payload = {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_tokens,
                "total_duration_seconds": round(self.total_duration_seconds, 2),
                "recent_history": self.recent_history[-50:],
            }
            tmp = self.storage_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.storage_path)
        except Exception as e:
            sys.stderr.write(f"[Stats] 保存统计文件异常: {e}\n")

    def _save_trace(self, req_id: str, trace_payload: dict[str, Any]) -> None:
        try:
            self.traces_dir.mkdir(parents=True, exist_ok=True)
            trace_file = self.traces_dir / f"{req_id}.json"
            trace_file.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            # 仅保留最近 60 份 trace，防止磁盘累积
            files = sorted(self.traces_dir.glob("req-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old_file in files[60:]:
                try:
                    old_file.unlink()
                except Exception:
                    pass
        except Exception as e:
            sys.stderr.write(f"[Stats] 保存 Trace 异常: {e}\n")

    def get_trace(self, req_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"req-[a-zA-Z0-9_-]{4,32}", req_id):
            return None
        trace_file = self.traces_dir / f"{req_id}.json"
        if not trace_file.is_file():
            return None
        try:
            return json.loads(trace_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def record_start(self) -> None:
        with self.lock:
            self.active_requests += 1

    def record_finish(
        self,
        *,
        model: str,
        is_stream: bool,
        duration: float,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        thinking_tokens: int = 0,
        status: str,  # "success" | "error" | "timeout"
        error_msg: str | None = None,
        client_ip: str = "",
        is_hermes: bool = False,
        input_messages: list[dict[str, Any]] | None = None,
        prompt_chars: int = 0,
        execution_steps: list[dict[str, Any]] | None = None,
        output_text: str | None = None,
        emitted_tool_calls: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self.active_requests = max(0, self.active_requests - 1)
            self.total_requests += 1
            if status == "success":
                self.successful_requests += 1
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_tokens += (prompt_tokens + completion_tokens)
                self.total_duration_seconds += duration
            else:
                self.failed_requests += 1

            tps = round(completion_tokens / duration, 1) if duration > 0 and completion_tokens > 0 else 0.0

            now = dt.datetime.now()
            req_id = f"req-{uuid.uuid4().hex[:8]}"
            steps_list = list(execution_steps or [])
            emitted_tcs = list(emitted_tool_calls or [])

            # 将转交给 Hermes 执行的 tool_calls 也追加到执行过程时间轴中
            for tc in emitted_tcs:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                steps_list.append({
                    "index": len(steps_list) + 1,
                    "type": "hermes_tool_call",
                    "title": f"{fn.get('name', 'tool')} (转交 Hermes 执行)",
                    "parameters": _truncate_text(str(fn.get("arguments", "")), 8000),
                    "output": "",
                    "duration": 0.0,
                    "state": "EMITTED",
                })

            local_tool_count = sum(1 for s in steps_list if s.get("type") == "tool")
            total_tool_count = local_tool_count + len(emitted_tcs)
            preview = _extract_input_preview(input_messages)

            record = {
                "id": req_id,
                "timestamp": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "model": model,
                "is_stream": is_stream,
                "duration": round(duration, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cached_tokens": cached_tokens,
                "thinking_tokens": thinking_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "tps": tps,
                "status": status,
                "error": error_msg,
                "client_ip": client_ip,
                "is_hermes": is_hermes,
                "input_preview": preview,
                "steps_count": len(steps_list),
                "tool_calls_count": total_tool_count,
                "has_trace": True,
            }
            self.recent_history.append(record)
            if len(self.recent_history) > 50:
                self.recent_history.pop(0)

            trace_payload = {
                "id": req_id,
                "datetime": record["datetime"],
                "client_ip": client_ip,
                "is_hermes": is_hermes,
                "model": model,
                "is_stream": is_stream,
                "status": status,
                "duration": round(duration, 2),
                "tps": tps,
                "conversation_id": conversation_id,
                "prompt_chars": prompt_chars,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cached_tokens": cached_tokens,
                    "thinking_tokens": thinking_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "input_messages": _sanitize_messages_for_trace(input_messages),
                "execution_steps": steps_list,
                "output_text": _truncate_text(output_text, 30000),
                "emitted_tool_calls": emitted_tcs,
                "error": error_msg,
            }
            self._save_trace(req_id, trace_payload)
            self._save()
            return record

    def reset(self) -> None:
        with self.lock:
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.total_tokens = 0
            self.total_duration_seconds = 0.0
            self.recent_history.clear()
            if self.traces_dir.is_dir():
                for f in self.traces_dir.glob("req-*.json"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
            self._save()

    def get_snapshot(self) -> dict[str, Any]:
        with self.lock:
            avg_duration = round(self.total_duration_seconds / self.successful_requests, 2) if self.successful_requests > 0 else 0.0
            avg_tps = round(self.total_completion_tokens / self.total_duration_seconds, 1) if self.total_duration_seconds > 0 else 0.0
            success_rate = round((self.successful_requests / self.total_requests) * 100, 1) if self.total_requests > 0 else 100.0

            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate": success_rate,
                "active_requests": self.active_requests,
                "max_concurrency": self.max_concurrency,
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_tokens,
                "avg_duration": avg_duration,
                "avg_tps": avg_tps,
                "recent_history": list(reversed(self.recent_history)),
            }


GLOBAL_STATS = StatsTracker(max_concurrency=DEFAULT_MAX_CONCURRENCY)
CONCURRENCY_SEMAPHORE = threading.BoundedSemaphore(DEFAULT_MAX_CONCURRENCY)


# ==============================================================================
# AGY 二进制与环境探测
# ==============================================================================
def find_agy_binary(custom_path: str | None = None) -> str:
    """自动探测 agy 可执行文件路径 (全平台适配)."""
    if custom_path and os.path.isfile(custom_path):
        if os.name == "nt" or os.access(custom_path, os.X_OK):
            return custom_path

    env_binary = os.environ.get("CALL_AGY_BINARY") or os.environ.get("AGY_BINARY")
    if env_binary and os.path.isfile(env_binary):
        if os.name == "nt" or os.access(env_binary, os.X_OK):
            return env_binary

    for name in ("agy", "agy.exe", "agy.cmd", "agy.bat"):
        wp = shutil.which(name)
        if wp:
            return wp

    home = pathlib.Path.home()
    candidates = [
        home / ".local" / "bin" / "agy",
        home / ".gemini" / "antigravity-cli" / "bin" / "agy",
        home / "bin" / "agy",
        pathlib.Path("/usr/local/bin/agy"),
        pathlib.Path("/opt/homebrew/bin/agy"),
    ]
    if os.name == "nt" or sys.platform == "win32":
        candidates.extend([
            home / ".local" / "bin" / "agy.exe",
            home / ".gemini" / "antigravity-cli" / "bin" / "agy.exe",
        ])
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidates.append(pathlib.Path(local_app_data) / "agy" / "bin" / "agy.exe")
            candidates.append(pathlib.Path(local_app_data) / "Programs" / "agy" / "bin" / "agy.exe")
        app_data = os.environ.get("APPDATA", "")
        if app_data:
            candidates.append(pathlib.Path(app_data) / "npm" / "agy.cmd")
            candidates.append(pathlib.Path(app_data) / "npm" / "agy.ps1")
        program_files = os.environ.get("ProgramFiles", "")
        if program_files:
            candidates.append(pathlib.Path(program_files) / "Antigravity" / "bin" / "agy.exe")

    for candidate in candidates:
        if candidate.is_file():
            if os.name == "nt" or os.access(candidate, os.X_OK):
                return str(candidate)

    return "agy"


def get_agy_version(agy_bin: str) -> str:
    """获取 agy 版本."""
    try:
        res = subprocess.run([agy_bin, "--version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception as e:
        return f"unknown ({e})"
    return "unknown"


def extract_json_content(text: str) -> str:
    """提取去除 Markdown 代码块包裹的纯文本或 JSON 内容."""
    trimmed = text.strip()
    match = re.search(r"^```(?:json)?\s*([\s\S]*?)\s*```$", trimmed, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return trimmed


def normalize_model_and_effort(model_name: str | None, effort: str | None = None) -> tuple[str, str | None]:
    """标准化模型名称并自动补充 effort 参数，支持模型别名智能映射与新模型透传."""
    if not model_name or not isinstance(model_name, str) or not model_name.strip():
        return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)

    raw = model_name.strip()
    raw_lower = raw.lower()

    # 1. 显式支持 3.7
    if raw_lower in ("3.7-flash", "3 7 flash", "gemini-3.7-flash"):
        return "gemini-3.7-flash", (effort or "high")

    # 2. 别名表匹配
    if raw_lower in MODEL_ALIASES:
        return MODEL_ALIASES[raw_lower], (effort or DEFAULT_EFFORT)

    # 3. 原生支持透传: Gemini 系列 (包括 gemini-4-hydrogen, gemini-4-neon, gemini-4-argon, gemini-3.8-flash 等)
    #    以及 agy 当前支持的 claude-sonnet-5-5, claude-opus-5-5, claude-sonnet-4-6, gpt-oss-120b-medium 等
    if (
        raw_lower.startswith("gemini-")
        or raw_lower.startswith("claude-sonnet-4")
        or raw_lower.startswith("claude-opus-4")
        or raw_lower.startswith("claude-sonnet-5")
        or raw_lower.startswith("claude-opus-5")
        or raw_lower.startswith("gpt-oss-")
    ):
        actual_effort = effort or DEFAULT_EFFORT
        for suffix in ("-xhigh", "-high", "-medium", "-low"):
            if raw_lower.endswith(suffix):
                raw_clean = raw[: -len(suffix)]
                return raw_clean, suffix[1:]
        return raw, actual_effort

    # 4. 常见第三方前缀匹配（如 gpt-、claude- 等未命中的历史别名）
    if any(raw_lower.startswith(prefix) for prefix in ("gpt-", "claude-", "o1", "o3", "deepseek")):
        return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)

    # 5. 默认兜底至 DEFAULT_MODEL (gemini-4-hydrogen)
    return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)


LLM_API_META_DIRECTIVE = """【CRITICAL SYSTEM DIRECTIVE: STRICT HERMES AGENT BACKEND MODE】
You are serving strictly as the LLM intelligence engine for the external Hermes Agent running on NAS Linux.
1. PROHIBITION ON LOCAL MACOS TOOLS: DO NOT execute any tools locally on this macOS machine (do NOT invoke local run_command, read_file, edit_file, subagent, etc.).
2. CALLING EXTERNAL TOOLS ON NAS: When you want to take action (read/write/patch files, execute terminal commands, inspect skills on NAS), you MUST invoke the Hermes client's tools by formatting each tool call in XML blocks:
<tool_call>
{"name": "tool_name", "arguments": {"param1": "value1"}}
</tool_call>
3. REAL ACTION ENFORCEMENT: Never merely promise, pretend, or talk in chat about modifying scripts without invoking tools. You must emit real <tool_call> blocks so Hermes will actually execute them on the NAS!
4. You may include concise natural language explanations outside the <tool_call> tags.
"""


LOCAL_HERMES_DIRECTIVE_PATH = (
    pathlib.Path(os.environ["AGY_HERMES_DIRECTIVE_FILE"]).expanduser()
    if os.environ.get("AGY_HERMES_DIRECTIVE_FILE")
    else (pathlib.Path.home() / ".config" / "antigravity-proxy" / "hermes_directive.local.txt")
)


def load_hermes_meta_directive() -> tuple[str, bool]:
    """优先热加载本机私有元指令文件（不纳入 Git 版本控制），不存在时回退至默认通用元指令."""
    try:
        if LOCAL_HERMES_DIRECTIVE_PATH.is_file():
            custom_text = LOCAL_HERMES_DIRECTIVE_PATH.read_text(encoding="utf-8").strip()
            if custom_text:
                return custom_text, True
    except Exception as e:
        print(f"[Proxy] !! 读取本机私有元指令失败 ({LOCAL_HERMES_DIRECTIVE_PATH}): {e}，将回退至内置指令")
    return LLM_API_META_DIRECTIVE, False


def _format_tools_for_prompt(tools: list[dict[str, Any]] | None) -> str:
    """将 OpenAI tools schema 精简格式化为清晰的工具清单，帮助模型精准输出 <tool_call>."""
    if not tools or not isinstance(tools, list):
        return ""
    lines: list[str] = ["【Available Client Tools / 客户端可用工具列表】"]
    for item in tools:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if item.get("type") == "function" else item
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        desc = " ".join(str(fn.get("description") or "").split())
        if len(desc) > 220:
            desc = desc[:220] + "…"
        params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
        props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
        required = set(params.get("required") or []) if isinstance(params.get("required"), list) else set()
        arg_specs: list[str] = []
        for k, v in props.items():
            ptype = v.get("type", "any") if isinstance(v, dict) else "any"
            mark = "*" if k in required else ""
            arg_specs.append(f"{k}{mark}:{ptype}")
        args_summary = ", ".join(arg_specs) if arg_specs else "no params"
        lines.append(f"- {name}({args_summary}): {desc}")
    return "\n".join(lines) if len(lines) > 1 else ""


MAX_AGY_PROMPT_CHARS = int(os.environ.get("AGY_MAX_PROMPT_CHARS") or 220000)


def build_agy_prompt(
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    inject_hermes_directive: bool = False,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """将 OpenAI 格式的 messages (含 tool_calls 与 tool 执行结果) 转换为 Antigravity prompt.

    内置尾部优先预算裁剪（Tail-Priority Window Guard）：
    防止单条超大 prompt 触发底层 CLI 约 80K token 的尾部截断而丢失最新 Tool Result。
    """
    system_parts: list[str] = []
    turn_entries: list[tuple[str, str]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_blocks: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_blocks.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_blocks.append(block)
            content_str = "\n".join(text_blocks)
        elif content is None:
            content_str = ""
        else:
            content_str = str(content)

        if role in ("system", "developer"):
            if content_str:
                system_parts.append(content_str)
        elif role == "user":
            turn_entries.append(("user", f"User: {content_str}"))
        elif role == "assistant":
            tc_list = msg.get("tool_calls")
            tc_blocks: list[str] = []
            if isinstance(tc_list, list):
                for tc in tc_list:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                    t_name = fn.get("name")
                    t_args = fn.get("arguments", "{}")
                    if t_name:
                        try:
                            parsed_args = json.loads(t_args) if isinstance(t_args, str) else t_args
                        except Exception:
                            parsed_args = t_args
                        payload = json.dumps({"name": t_name, "arguments": parsed_args}, ensure_ascii=False)
                        tc_blocks.append(f"<tool_call>\n{payload}\n</tool_call>")
            combined = "\n".join(p for p in [content_str.strip(), "\n".join(tc_blocks)] if p)
            if combined:
                turn_entries.append(("assistant", f"Assistant: {combined}"))
        elif role == "tool":
            tool_label = msg.get("name") or msg.get("tool_call_id") or "tool"
            turn_entries.append(("tool", f"Tool Result ({tool_label}):\n{content_str}"))

    header_lines: list[str] = []
    # 仅当请求来源是 Hermes 智能体时，注入专属元指令（优先读取本机私有配置，不上传 Git）
    if inject_hermes_directive:
        directive_text, is_local = load_hermes_meta_directive()
        if is_local:
            print(f"[Proxy] [Hermes配置] 已热加载本机私有元指令 ({LOCAL_HERMES_DIRECTIVE_PATH})")
        header_lines.append(directive_text)
        tools_section = _format_tools_for_prompt(tools)
        if tools_section:
            header_lines.append(tools_section)
            header_lines.append("")
    if system_parts:
        sys_joined = "\n".join(system_parts)
        if len(sys_joined) > 30000:
            sys_joined = sys_joined[:30000] + f"\n...[系统指令过长已截断，原长 {len(sys_joined)} 字符]"
        header_lines.append("【系统指令 / System Instructions】")
        header_lines.append(sys_joined)
        header_lines.append("")

    footer_lines: list[str] = []
    if response_format and isinstance(response_format, dict):
        rf_type = response_format.get("type")
        if rf_type == "json_object":
            footer_lines.append("")
            footer_lines.append("【关键格式要求】")
            footer_lines.append("你必须仅输出合法、纯净的 JSON 字符串。不要添加任何前言、解释或 Markdown 代码块标记（如 ```json）。")

    header_text = "\n".join(header_lines)
    footer_text = "\n".join(footer_lines)
    available_budget = max(24000, MAX_AGY_PROMPT_CHARS - len(header_text) - len(footer_text) - 256)

    # 尾部优先保留策略：保护最近 24 条消息完整，更早的历史 tool 输出先合理折叠瘦身
    total_raw_turns_len = sum(len(t) for _, t in turn_entries)
    compacted_entries: list[str] = []
    protect_tail = 24
    cutoff_idx = max(0, len(turn_entries) - protect_tail)
    for idx, (r, txt) in enumerate(turn_entries):
        if idx < cutoff_idx and r == "tool" and len(txt) > 2000:
            compacted_entries.append(txt[:900] + f"\n...[早期工具输出已折叠，原长 {len(txt)} 字符]")
        else:
            compacted_entries.append(txt)

    # 从最新一条消息倒序装入预算，绝对保证最新提问与最新工具执行结果不被截断
    kept_reversed: list[str] = []
    used_chars = 0
    for txt in reversed(compacted_entries):
        if used_chars + len(txt) + 1 <= available_budget:
            kept_reversed.append(txt)
            used_chars += len(txt) + 1
        else:
            # 若最新一条本身就超过预算，保底截断保留，避免对话变空
            if not kept_reversed:
                remain = max(4000, available_budget - 100)
                kept_reversed.append(txt[:remain] + f"\n...[单条过长已截断，原长 {len(txt)} 字符]")
            break

    kept_entries = list(reversed(kept_reversed))
    dropped_count = len(compacted_entries) - len(kept_entries)
    if dropped_count > 0:
        print(
            f"[Proxy] [防截断保护] 原始对话 {total_raw_turns_len} 字符超预算 ({available_budget})，"
            f"已丢弃最早期 {dropped_count} 条历史，完整保留最近 {len(kept_entries)} 条最新消息与工具结果"
        )

    prompt_lines = list(header_lines)
    if kept_entries:
        prompt_lines.append("【上下文与用户输入 / Context & User Prompt】")
        if dropped_count > 0:
            prompt_lines.append(f"[注：已自动省略更早的 {dropped_count} 条历史消息以防止上下文溢出，以下为完整最新对话与工具结果]")
        prompt_lines.extend(kept_entries)
    prompt_lines.extend(footer_lines)

    return "\n".join(prompt_lines).strip()


# ==============================================================================
# 工具调用 (Tool Call) 智能解析与流式过滤器
# ==============================================================================
TOOL_CALL_REGEX = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)


def extract_tool_calls_from_text(text: str) -> tuple[list[dict[str, Any]], str]:
    """从文本中提取 <tool_call> 标签并转换为 OpenAI 标准的 tool_calls 列表，同时返回去除标签后的纯正文."""
    tool_calls: list[dict[str, Any]] = []

    matches = list(TOOL_CALL_REGEX.finditer(text))
    if not matches:
        return [], text

    for i, match in enumerate(matches):
        raw_payload = match.group(1).strip()
        if raw_payload.startswith("```"):
            raw_payload = re.sub(r"^```(?:json|xml)?\s*", "", raw_payload)
            raw_payload = re.sub(r"\s*```$", "", raw_payload).strip()

        try:
            data = json.loads(raw_payload)
        except Exception:
            continue

        tool_name = ""
        tool_args = ""
        if isinstance(data, dict):
            if "name" in data:
                tool_name = str(data["name"])
                args_val = data.get("arguments", {})
                tool_args = (
                    json.dumps(args_val, ensure_ascii=False)
                    if isinstance(args_val, (dict, list))
                    else str(args_val)
                )
            elif "function" in data and isinstance(data["function"], dict):
                tool_name = str(data["function"].get("name", ""))
                args_val = data["function"].get("arguments", {})
                tool_args = (
                    json.dumps(args_val, ensure_ascii=False)
                    if isinstance(args_val, (dict, list))
                    else str(args_val)
                )

        if tool_name:
            tool_calls.append({
                "index": i,
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": tool_args,
                },
            })

    cleaned_text = TOOL_CALL_REGEX.sub("", text).strip()
    return tool_calls, cleaned_text


class StreamToolCallFilter:
    """实时流式 SSE 工具调用过滤器:
    实时透传普通文本，拦截并提取 <tool_call>...</tool_call> 块，将其转化为 OpenAI 标准的 tool_calls 事件.
    """

    def __init__(self) -> None:
        self.buffer: str = ""
        self.tool_index: int = 0
        self.has_emitted_tool_calls: bool = False

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        self.buffer += chunk
        events: list[dict[str, Any]] = []

        while self.buffer:
            lower_buf = self.buffer.lower()
            tag_start = lower_buf.find("<tool_call")

            if tag_start == -1:
                # 检查末尾是否可能是被截断的 <tool_call 前缀
                safe_len = len(self.buffer)
                for i in range(1, min(12, len(self.buffer) + 1)):
                    tail = self.buffer[-i:].lower()
                    if "<tool_call"[:i] == tail:
                        safe_len = len(self.buffer) - i
                        break

                safe_text = self.buffer[:safe_len]
                self.buffer = self.buffer[safe_len:]
                if safe_text:
                    events.append({"type": "content", "text": safe_text})
                break
            else:
                if tag_start > 0:
                    text_before = self.buffer[:tag_start]
                    events.append({"type": "content", "text": text_before})
                    self.buffer = self.buffer[tag_start:]

                tag_close_match = re.search(r"</tool_call>", self.buffer, re.IGNORECASE)
                if not tag_close_match:
                    # 尚未完整闭合，等待下一分片
                    break

                end_pos = tag_close_match.end()
                full_block = self.buffer[:end_pos]
                self.buffer = self.buffer[end_pos:]

                inner = re.sub(r"^<tool_call[^>]*>", "", full_block, flags=re.IGNORECASE)
                inner = re.sub(r"</tool_call>$", "", inner, flags=re.IGNORECASE).strip()
                if inner.startswith("```"):
                    inner = re.sub(r"^```(?:json|xml)?\s*", "", inner)
                    inner = re.sub(r"\s*```$", "", inner).strip()

                try:
                    data = json.loads(inner)
                    tool_name = ""
                    tool_args = ""
                    if isinstance(data, dict):
                        if "name" in data:
                            tool_name = str(data["name"])
                            args_val = data.get("arguments", {})
                            tool_args = (
                                json.dumps(args_val, ensure_ascii=False)
                                if isinstance(args_val, (dict, list))
                                else str(args_val)
                            )
                        elif "function" in data and isinstance(data["function"], dict):
                            tool_name = str(data["function"].get("name", ""))
                            args_val = data["function"].get("arguments", {})
                            tool_args = (
                                json.dumps(args_val, ensure_ascii=False)
                                if isinstance(args_val, (dict, list))
                                else str(args_val)
                            )

                    if tool_name:
                        self.has_emitted_tool_calls = True
                        events.append({
                            "type": "tool_calls",
                            "tool_calls": [
                                {
                                    "index": self.tool_index,
                                    "id": f"call_{uuid.uuid4().hex[:12]}",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": tool_args,
                                    },
                                }
                            ],
                        })
                        self.tool_index += 1
                except Exception:
                    events.append({"type": "content", "text": full_block})

        return events

    def finalize(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.buffer:
            remaining = self.buffer
            self.buffer = ""
            events.append({"type": "content", "text": remaining})
        return events


# ==============================================================================
# 核心调用流式生成器
# ==============================================================================
def _safe_terminate_proc(proc: subprocess.Popen) -> None:
    """平滑终止子进程及其派生的进程组，防止僵尸进程."""
    try:
        if os.name != "nt":
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, 15)  # SIGTERM
            except Exception:
                proc.terminate()
        else:
            proc.terminate()

        try:
            proc.wait(timeout=1.5)
        except Exception:
            if os.name != "nt":
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, 9)  # SIGKILL
                except Exception:
                    proc.kill()
            else:
                proc.kill()
    except Exception:
        pass


def run_agy_stream_generator(
    agy_bin: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
    workspace: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_out: dict[str, Any] | None = None,
) -> Generator[tuple[str, Any, Any, Any], None, None]:
    """生成器：实时产生 agy 输出的事件片段.

    Yields:
      ("delta", text_chunk: str, usage_info: dict, None)
      ("done", final_full_text: str, usage_info: dict, duration: float)
    """
    final_model, final_effort = normalize_model_and_effort(model, effort)

    cmd = [
        agy_bin,
        "--print=",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--disable-slash-commands",
    ]

    if final_model:
        cmd.extend(["--model", final_model])
    if final_effort:
        cmd.extend(["--effort", final_effort])

    # 规范工作目录，避免把 .app 资源目录作为工作空间
    if workspace and os.path.isdir(workspace) and "Contents/Resources" not in workspace:
        cwd = workspace
    else:
        home_ws = pathlib.Path.home() / ".gemini" / "antigravity-cli" / "workspace"
        home_ws.mkdir(parents=True, exist_ok=True)
        cwd = str(home_ws)

    popen_options: dict[str, Any] = {}
    if os.name != "nt":
        popen_options["start_new_session"] = True

    t_start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **popen_options,
    )

    event_data = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"

    try:
        if proc.stdin:
            proc.stdin.write(event_data)
            proc.stdin.flush()
            proc.stdin.close()
    except Exception as e:
        _safe_terminate_proc(proc)
        raise RuntimeError(f"向 agy 传递输入失败: {e}") from e

    collected_fragments: list[str] = []
    final_response: str | None = None
    usage_info: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "thinking_tokens": 0,
    }

    # 估算输入 token
    estimated_prompt_tokens = max(1, len(prompt) // 2)
    usage_info["prompt_tokens"] = estimated_prompt_tokens

    # 智能超时控制：
    # 1. 首字等待超时 (TTFT)：面对 6 万+ 超大 Prompt 吸收和 High 深度思考，放宽至至少 360s (6分钟)
    ttft_timeout = max(timeout, 360.0)
    # 2. 流式活跃空闲超时：一旦开始吐字，只要在持续输出就不杀；若中途连续停滞 120s 无新字才判定断流
    chunk_inactivity_timeout = 120.0
    # 3. 极端总时长兜底上限：放宽至 1800s (30分钟，看齐 Hermes Gateway 默认最长时限)
    max_hard_deadline = t_start + max(timeout * 3, 1800.0)

    has_received_first_token = False
    last_token_time = t_start

    # 执行过程追踪（按 step_index 聚合思考、工具调用与回复轮次）
    step_map: dict[str, dict[str, Any]] = {}
    step_order: list[str] = []
    if trace_out is not None:
        trace_out.setdefault("conversation_id", None)
        trace_out.setdefault("steps", [])

    def _sync_trace_steps() -> None:
        if trace_out is not None:
            trace_out["steps"] = [step_map[k] for k in step_order]

    try:
        while True:
            now = time.monotonic()
            if now > max_hard_deadline:
                _safe_terminate_proc(proc)
                raise TimeoutError(f"Antigravity CLI 执行达到单请求总时长上限 ({round(now - t_start, 1)}s)")

            if not has_received_first_token:
                if (now - t_start) > ttft_timeout:
                    _safe_terminate_proc(proc)
                    raise TimeoutError(f"Antigravity CLI 响应等待超时 ({round(now - t_start, 1)}s，未收到模型首字)")
            else:
                if (now - last_token_time) > chunk_inactivity_timeout:
                    _safe_terminate_proc(proc)
                    raise TimeoutError(f"Antigravity CLI 流式传输中断 (连续 {chunk_inactivity_timeout}s 无新 Token 输出)")

            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.01)
                continue

            line = line.strip()
            if not line:
                continue

            try:
                event_obj = json.loads(line)
            except Exception:
                continue

            event_name = event_obj.get("event")
            if event_name == "init":
                if trace_out is not None and event_obj.get("conversation_id"):
                    trace_out["conversation_id"] = str(event_obj.get("conversation_id"))

            elif event_name == "step_update":
                step = event_obj.get("step_update", {})
                # 任何活跃的步骤更新（含远程 SSH 工具执行进度）均刷新空闲保活时间
                last_token_time = time.monotonic()
                step_type = step.get("step_type")
                step_idx_raw = str(step.get("step_index", len(step_order)))
                step_state = str(step.get("state", "ACTIVE"))
                if trace_out is not None and not trace_out.get("conversation_id") and step.get("conversation_id"):
                    trace_out["conversation_id"] = str(step.get("conversation_id"))

                if step_type == "tool":
                    tool_info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
                    tool_name = str(step.get("tool_name") or tool_info.get("name") or "tool")
                    params_obj = tool_info.get("parameters")
                    try:
                        params_str = json.dumps(params_obj, ensure_ascii=False, indent=2) if params_obj is not None else ""
                    except Exception:
                        params_str = str(params_obj or "")
                    output_str = str(tool_info.get("output") or "")
                    try:
                        step_dur = round(float(step.get("duration_seconds") or 0.0), 2)
                    except Exception:
                        step_dur = 0.0

                    if step_idx_raw not in step_map:
                        step_order.append(step_idx_raw)
                        step_map[step_idx_raw] = {
                            "index": len(step_order),
                            "type": "tool",
                            "title": tool_name,
                            "parameters": _truncate_text(params_str, 8000),
                            "output": _truncate_text(output_str, 15000),
                            "duration": step_dur,
                            "state": step_state,
                        }
                    else:
                        entry = step_map[step_idx_raw]
                        entry["state"] = step_state
                        if step_dur > 0:
                            entry["duration"] = step_dur
                        if params_str:
                            entry["parameters"] = _truncate_text(params_str, 8000)
                        if output_str:
                            entry["output"] = _truncate_text(output_str, 15000)
                    _sync_trace_steps()

                elif step_type == "agent_response":
                    delta = step.get("text_delta")
                    usage = step.get("usage")
                    if isinstance(usage, dict):
                        usage_info["prompt_tokens"] = usage.get("input_tokens", usage_info["prompt_tokens"])
                        usage_info["completion_tokens"] = usage.get("output_tokens", usage_info["completion_tokens"])
                        usage_info["cached_tokens"] = usage.get("cache_read_tokens") or usage.get("cached_tokens") or usage_info["cached_tokens"]
                        usage_info["thinking_tokens"] = usage.get("thinking_tokens", usage_info["thinking_tokens"])
                        usage_info["total_tokens"] = usage.get("total_tokens", usage_info["total_tokens"])

                    if step_state == "DONE":
                        try:
                            step_dur = round(float(step.get("duration_seconds") or 0.0), 2)
                        except Exception:
                            step_dur = 0.0
                        think_tok = int(usage.get("thinking_tokens", 0)) if isinstance(usage, dict) else 0
                        out_tok = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0
                        cache_tok = int(usage.get("cache_read_tokens") or usage.get("cached_tokens") or 0) if isinstance(usage, dict) else 0
                        detail_parts = []
                        if think_tok > 0:
                            detail_parts.append(f"思考 {think_tok} tok")
                        if out_tok > 0:
                            detail_parts.append(f"生成 {out_tok} tok")
                        if cache_tok > 0:
                            detail_parts.append(f"缓存命中 {cache_tok} tok")
                        if step_idx_raw not in step_map:
                            step_order.append(step_idx_raw)
                        step_map[step_idx_raw] = {
                            "index": len(step_order),
                            "type": "agent_response",
                            "title": "模型推理与生成",
                            "parameters": " · ".join(detail_parts) if detail_parts else "完成本轮推理",
                            "output": "",
                            "duration": step_dur,
                            "state": "DONE",
                        }
                        _sync_trace_steps()

                    if isinstance(delta, str) and delta:
                        has_received_first_token = True
                        collected_fragments.append(delta)
                        yield ("delta", delta, usage_info, None)

            elif event_name == "result":
                res = event_obj.get("result", {})
                if trace_out is not None and res.get("conversation_id"):
                    trace_out["conversation_id"] = str(res.get("conversation_id"))
                status = res.get("status")
                if status == "SUCCESS":
                    final_response = res.get("response")
                    usage = res.get("usage")
                    if isinstance(usage, dict):
                        usage_info["prompt_tokens"] = usage.get("input_tokens", usage_info["prompt_tokens"])
                        usage_info["completion_tokens"] = usage.get("output_tokens", usage_info["completion_tokens"])
                        usage_info["cached_tokens"] = usage.get("cache_read_tokens") or usage.get("cached_tokens") or usage_info["cached_tokens"]
                        usage_info["thinking_tokens"] = usage.get("thinking_tokens", usage_info["thinking_tokens"])
                        usage_info["total_tokens"] = usage.get("total_tokens", usage_info["total_tokens"])
                elif status == "ERROR":
                    err_msg = res.get("error") or res.get("response") or "agy execution error"
                    raise RuntimeError(f"Antigravity 执行返回错误: {err_msg}")
                break

        try:
            proc.wait(timeout=3)
        except Exception:
            _safe_terminate_proc(proc)
    except Exception:
        _safe_terminate_proc(proc)
        raise

    duration = time.monotonic() - t_start
    output_text = final_response if final_response is not None else "".join(collected_fragments)

    if usage_info["completion_tokens"] == 0 and output_text:
        usage_info["completion_tokens"] = max(1, len(output_text) // 2)
    usage_info["total_tokens"] = usage_info["prompt_tokens"] + usage_info["completion_tokens"]

    yield ("done", output_text, usage_info, duration)


def run_agy_stream_json(
    agy_bin: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
    workspace: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_out: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int], float]:
    """以阻塞方式调用 agy 并完整收集结果."""
    final_text = ""
    final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0, "thinking_tokens": 0}
    final_duration = 0.0

    for evt in run_agy_stream_generator(
        agy_bin=agy_bin,
        prompt=prompt,
        model=model,
        effort=effort,
        workspace=workspace,
        timeout=timeout,
        trace_out=trace_out,
    ):
        if evt[0] == "done":
            final_text = evt[1]
            final_usage = evt[2]
            final_duration = evt[3]

    return final_text, final_usage, final_duration


# ==============================================================================
# HTTP 处理类 (AgyProxyHandler)
# ==============================================================================
class AgyProxyHandler(http.server.BaseHTTPRequestHandler):
    agy_bin: str = "agy"
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    default_model: str = DEFAULT_MODEL
    default_effort: str = DEFAULT_EFFORT
    workspace: str = os.getcwd()
    hermes_ips: set[str] = DEFAULT_HERMES_IPS.copy()

    def _get_client_ip(self) -> str:
        """从请求头或 socket 连接中提取客户端真实 IP."""
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        x_real = self.headers.get("X-Real-IP")
        if x_real:
            return x_real.strip()
        if self.client_address and len(self.client_address) > 0:
            return str(self.client_address[0])
        return ""

    def _is_hermes_client(self, client_ip: str) -> bool:
        """判断请求是否来自 Hermes 智能体 (根据 IP 来源或协议特征)."""
        # 1. 严格检查 IP 地址匹配 (例如 NAS IP: 192.168.6.192)
        if client_ip and client_ip in self.hermes_ips:
            return True
        # 2. 检查特定请求头
        ua = self.headers.get("User-Agent", "").lower()
        if "hermes" in ua:
            return True
        x_client = self.headers.get("X-Client", "").lower()
        if "hermes" in x_client:
            return True
        return False

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sys.stderr.write(f"[{timestamp}] {format % args}\n")

    def _send_cors_headers(self) -> None:
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("/health", "/v1/health", ""):
            version = get_agy_version(self.agy_bin)
            stats = GLOBAL_STATS.get_snapshot()
            body = {
                "status": "ok",
                "service": "antigravity-proxy",
                "default_model": self.default_model,
                "default_effort": self.default_effort,
                "hermes_ips": sorted(list(self.hermes_ips)),
                "max_concurrency": stats["max_concurrency"],
                "agy_path": self.agy_bin,
                "agy_version": version,
                "time": dt.datetime.now().isoformat(),
                "stats_summary": {
                    "total_requests": stats["total_requests"],
                    "total_prompt_tokens": stats["total_prompt_tokens"],
                    "total_completion_tokens": stats["total_completion_tokens"],
                    "total_tokens": stats["total_tokens"],
                    "avg_tps": stats["avg_tps"],
                    "active_requests": stats["active_requests"],
                },
            }
            self._send_json_response(200, body)
            return

        if path in ("/v1/stats", "/stats"):
            snapshot = GLOBAL_STATS.get_snapshot()
            self._send_json_response(200, snapshot)
            return

        if path.startswith("/v1/requests/") or path.startswith("/requests/"):
            req_id = path.rsplit("/", 1)[-1].strip()
            trace = GLOBAL_STATS.get_trace(req_id)
            if trace is None:
                self._send_json_response(404, {"error": {"message": f"Trace not found: {req_id}", "type": "not_found"}})
            else:
                self._send_json_response(200, trace)
            return

        if path in ("/v1/models", "/models"):
            body = {
                "object": "list",
                "data": [
                    {
                        "id": "gemini-4-hydrogen",
                        "object": "model",
                        "created": 1795300000,
                        "owned_by": "google",
                    },
                    {
                        "id": "gemini-4-neon",
                        "object": "model",
                        "created": 1795300000,
                        "owned_by": "google",
                    },
                    {
                        "id": "gemini-4-argon",
                        "object": "model",
                        "created": 1795300000,
                        "owned_by": "google",
                    },
                    {
                        "id": "gemini-3.8-flash",
                        "object": "model",
                        "created": 1788100000,
                        "owned_by": "google",
                    },
                    {
                        "id": "antigravity",
                        "object": "model",
                        "created": 1788000000,
                        "owned_by": "antigravity",
                    },
                    {
                        "id": "gpt-4o",
                        "object": "model",
                        "created": 1788000000,
                        "owned_by": "openai-alias",
                    },
                    {
                        "id": "claude-3-5-sonnet",
                        "object": "model",
                        "created": 1788000000,
                        "owned_by": "anthropic-alias",
                    },
                ],
            }
            self._send_json_response(200, body)
            return

        self._send_json_response(404, {"error": {"message": f"Not found: {self.path}", "type": "invalid_request_error"}})

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("/v1/stats/reset", "/stats/reset"):
            GLOBAL_STATS.reset()
            self._send_json_response(200, {"status": "ok", "message": "统计数据已成功重置"})
            return

        if path in ("/v1/chat/completions", "/chat/completions"):
            self.handle_chat_completions()
            return

        self._send_json_response(404, {"error": {"message": f"Endpoint not found: {self.path}", "type": "invalid_request_error"}})

    def handle_chat_completions(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            req_data = json.loads(raw_body)
        except Exception as e:
            self._send_json_response(400, {"error": {"message": f"Malformed JSON: {e}", "type": "invalid_request_error"}})
            return

        messages = req_data.get("messages", [])
        if not isinstance(messages, list) or not messages:
            self._send_json_response(400, {"error": {"message": "'messages' array is required", "type": "invalid_request_error"}})
            return

        is_stream = bool(req_data.get("stream", False))
        model = req_data.get("model") or self.default_model
        effort = req_data.get("effort") or self.default_effort
        response_format = req_data.get("response_format")
        req_tools = req_data.get("tools")

        custom_timeout = req_data.get("timeout")
        if not custom_timeout:
            header_to = self.headers.get("X-Timeout")
            if header_to:
                try:
                    custom_timeout = float(header_to)
                except ValueError:
                    pass
        effective_timeout = float(custom_timeout) if custom_timeout else self.timeout

        client_ip = self._get_client_ip()
        is_hermes = self._is_hermes_client(client_ip)

        if is_hermes:
            print(f"[Proxy] [Hermes防护] 来源确认为 Hermes 智能体 ({client_ip})，已注入纯 LLM 推理防护指令 (工具数: {len(req_tools) if isinstance(req_tools, list) else 0})")
        else:
            print(f"[Proxy] 来源为常规客户端 ({client_ip or '本地'})，保持原生 Prompt (未添加防御指令)")

        prompt = build_agy_prompt(messages, response_format, inject_hermes_directive=is_hermes, tools=req_tools if isinstance(req_tools, list) else None)
        final_model, _ = normalize_model_and_effort(model, effort)

        GLOBAL_STATS.record_start()
        t_queue = time.monotonic()

        # 并发控制：信号量排队 (提升至 5 路并行)
        CONCURRENCY_SEMAPHORE.acquire()
        try:
            queue_wait = time.monotonic() - t_queue
            if queue_wait > 0.05:
                print(f"[Proxy] 请求排队完成 (等待耗时: {queue_wait:.2f}s)")

            if is_stream:
                self._handle_stream_completions(
                    prompt, model, effort, final_model, effective_timeout,
                    messages=messages, client_ip=client_ip, is_hermes=is_hermes,
                )
            else:
                self._handle_block_completions(
                    prompt, model, effort, final_model, response_format, effective_timeout,
                    messages=messages, client_ip=client_ip, is_hermes=is_hermes,
                )
        finally:
            CONCURRENCY_SEMAPHORE.release()

    def _handle_stream_completions(
        self,
        prompt: str,
        model: str,
        effort: str,
        final_model: str,
        timeout: float,
        *,
        messages: list[dict[str, Any]] | None = None,
        client_ip: str = "",
        is_hermes: bool = False,
    ) -> None:
        """处理 SSE 流式响应 (stream: true)."""
        response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._send_cors_headers()
        self.end_headers()

        print(f"[Proxy] -> 正在流式调用 Antigravity (模型: {final_model}, 字符数: {len(prompt)}, 超时: {timeout}s)...")
        t_start = time.monotonic()
        final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0, "thinking_tokens": 0}
        duration = 0.0
        trace_out: dict[str, Any] = {}
        streamed_text_parts: list[str] = []
        emitted_tool_calls: list[dict[str, Any]] = []

        stream_filter = StreamToolCallFilter()
        try:
            for evt in run_agy_stream_generator(
                agy_bin=self.agy_bin,
                prompt=prompt,
                model=model,
                effort=effort,
                workspace=self.workspace,
                timeout=timeout,
                trace_out=trace_out,
            ):
                if evt[0] == "delta":
                    delta_chunk = evt[1]
                    for sub_evt in stream_filter.feed(delta_chunk):
                        if sub_evt["type"] == "content":
                            streamed_text_parts.append(sub_evt["text"])
                            chunk_obj = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_ts,
                                "model": final_model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": sub_evt["text"]},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            self.wfile.write(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        elif sub_evt["type"] == "tool_calls":
                            emitted_tool_calls.extend(sub_evt["tool_calls"])
                            chunk_obj = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created_ts,
                                "model": final_model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"tool_calls": sub_evt["tool_calls"]},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            self.wfile.write(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                elif evt[0] == "done":
                    final_usage = evt[2]
                    duration = evt[3]

            for sub_evt in stream_filter.finalize():
                if sub_evt["type"] == "content":
                    streamed_text_parts.append(sub_evt["text"])
                    chunk_obj = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": final_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": sub_evt["text"]},
                                "finish_reason": None,
                            }
                        ],
                    }
                    self.wfile.write(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()

            openai_usage = {
                "prompt_tokens": final_usage.get("prompt_tokens", 0),
                "completion_tokens": final_usage.get("completion_tokens", 0),
                "total_tokens": final_usage.get("total_tokens", 0),
            }

            # 最终 Stop 块
            finish_reason = "tool_calls" if stream_filter.has_emitted_tool_calls else "stop"
            stop_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": final_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": openai_usage,
            }
            self.wfile.write(f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True

            tps = round(final_usage.get("completion_tokens", 0) / duration, 1) if duration > 0 else 0.0
            tools_info = f", 工具调用: {stream_filter.tool_index} 次" if stream_filter.has_emitted_tool_calls else ""
            print(f"[Proxy] <- 流式完成 (耗时: {duration:.2f}s{tools_info}, 入: {final_usage.get('prompt_tokens')}, 出: {final_usage.get('completion_tokens')}, 速率: {tps} tps)")

            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=True,
                duration=duration,
                prompt_tokens=final_usage.get("prompt_tokens", 0),
                completion_tokens=final_usage.get("completion_tokens", 0),
                cached_tokens=final_usage.get("cached_tokens", 0),
                thinking_tokens=final_usage.get("thinking_tokens", 0),
                status="success",
                client_ip=client_ip,
                is_hermes=is_hermes,
                input_messages=messages,
                prompt_chars=len(prompt),
                execution_steps=trace_out.get("steps"),
                output_text="".join(streamed_text_parts),
                emitted_tool_calls=emitted_tool_calls,
                conversation_id=trace_out.get("conversation_id"),
            )
        except TimeoutError as e:
            print(f"[Proxy] !! 流式超时: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=True,
                duration=time.monotonic() - t_start,
                prompt_tokens=final_usage.get("prompt_tokens", 0) or max(1, len(prompt) // 2),
                completion_tokens=final_usage.get("completion_tokens", 0),
                cached_tokens=final_usage.get("cached_tokens", 0),
                thinking_tokens=final_usage.get("thinking_tokens", 0),
                status="timeout",
                error_msg=str(e),
                client_ip=client_ip,
                is_hermes=is_hermes,
                input_messages=messages,
                prompt_chars=len(prompt),
                execution_steps=trace_out.get("steps"),
                output_text="".join(streamed_text_parts),
                emitted_tool_calls=emitted_tool_calls,
                conversation_id=trace_out.get("conversation_id"),
            )
            err_data = {"error": {"message": str(e), "type": "timeout_error"}}
            self.wfile.write(f"data: {json.dumps(err_data)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception as e:
            print(f"[Proxy] !! 流式错误: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=True,
                duration=time.monotonic() - t_start,
                prompt_tokens=0,
                completion_tokens=0,
                cached_tokens=0,
                status="error",
                error_msg=str(e),
                client_ip=client_ip,
                is_hermes=is_hermes,
                input_messages=messages,
                prompt_chars=len(prompt),
                execution_steps=trace_out.get("steps"),
                output_text="".join(streamed_text_parts),
                emitted_tool_calls=emitted_tool_calls,
                conversation_id=trace_out.get("conversation_id"),
            )
            err_data = {"error": {"message": str(e), "type": "internal_error"}}
            self.wfile.write(f"data: {json.dumps(err_data)}\n\n".encode("utf-8"))
            self.wfile.flush()

    def _handle_block_completions(
        self,
        prompt: str,
        model: str,
        effort: str,
        final_model: str,
        response_format: dict[str, Any] | None,
        timeout: float,
        *,
        messages: list[dict[str, Any]] | None = None,
        client_ip: str = "",
        is_hermes: bool = False,
    ) -> None:
        """处理非流式完整响应."""
        print(f"[Proxy] -> 正在调用 Antigravity (模型: {final_model}, 字符数: {len(prompt)}, 超时: {timeout}s)...")
        t_start = time.monotonic()
        trace_out: dict[str, Any] = {}

        try:
            output_text, usage, duration = run_agy_stream_json(
                agy_bin=self.agy_bin,
                prompt=prompt,
                model=model,
                effort=effort,
                workspace=self.workspace,
                timeout=timeout,
                trace_out=trace_out,
            )
            tps = round(usage.get("completion_tokens", 0) / duration, 1) if duration > 0 else 0.0
            print(f"[Proxy] <- 调用成功 (耗时: {duration:.2f}s, 入: {usage.get('prompt_tokens')}, 出: {usage.get('completion_tokens')}, 速率: {tps} tps)")
        except TimeoutError as e:
            print(f"[Proxy] !! 超时: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=False,
                duration=time.monotonic() - t_start,
                prompt_tokens=max(1, len(prompt) // 2),
                completion_tokens=0,
                status="timeout",
                error_msg=str(e),
                client_ip=client_ip,
                is_hermes=is_hermes,
                input_messages=messages,
                prompt_chars=len(prompt),
                execution_steps=trace_out.get("steps"),
                output_text="",
                conversation_id=trace_out.get("conversation_id"),
            )
            self._send_json_response(504, {"error": {"message": str(e), "type": "timeout_error"}})
            return
        except Exception as e:
            print(f"[Proxy] !! 错误: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=False,
                duration=time.monotonic() - t_start,
                prompt_tokens=0,
                completion_tokens=0,
                cached_tokens=0,
                status="error",
                error_msg=str(e),
                client_ip=client_ip,
                is_hermes=is_hermes,
                input_messages=messages,
                prompt_chars=len(prompt),
                execution_steps=trace_out.get("steps"),
                output_text="",
                conversation_id=trace_out.get("conversation_id"),
            )
            self._send_json_response(500, {"error": {"message": str(e), "type": "internal_error"}})
            return

        tool_calls, clean_text = extract_tool_calls_from_text(output_text)

        if response_format and isinstance(response_format, dict) and response_format.get("type") == "json_object":
            clean_text = extract_json_content(clean_text)

        GLOBAL_STATS.record_finish(
            model=final_model,
            is_stream=False,
            duration=duration,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cached_tokens=usage.get("cached_tokens", 0),
            thinking_tokens=usage.get("thinking_tokens", 0),
            status="success",
            client_ip=client_ip,
            is_hermes=is_hermes,
            input_messages=messages,
            prompt_chars=len(prompt),
            execution_steps=trace_out.get("steps"),
            output_text=clean_text,
            emitted_tool_calls=tool_calls,
            conversation_id=trace_out.get("conversation_id"),
        )

        response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        openai_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        msg_obj: dict[str, Any] = {
            "role": "assistant",
            "content": clean_text if clean_text else None,
        }
        if tool_calls:
            msg_obj["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"

        openai_response = {
            "id": response_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": final_model,
            "choices": [
                {
                    "index": 0,
                    "message": msg_obj,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": openai_usage,
        }

        self._send_json_response(200, openai_response)

    def _send_json_response(self, status_code: int, data: dict[str, Any]) -> None:
        raw_json = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw_json)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw_json)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    custom_agy: str | None = None,
    workspace: str | None = None,
    hermes_ips: set[str] | None = None,
) -> None:
    global CONCURRENCY_SEMAPHORE
    CONCURRENCY_SEMAPHORE = threading.BoundedSemaphore(max(1, max_concurrency))
    GLOBAL_STATS.max_concurrency = max_concurrency

    agy_bin = find_agy_binary(custom_agy)
    version = get_agy_version(agy_bin)
    effective_hermes_ips = set(hermes_ips) if hermes_ips is not None else DEFAULT_HERMES_IPS.copy()

    print("=" * 68)
    print("🚀 Antigravity 通用本地 OpenAI 兼容 API 代理服务 (生产增强版)")
    print("=" * 68)
    print(f"📍 监听地址:      http://{host}:{port}/v1")
    print(f"🌐 对应端点:      http://{host}:{port}/v1/chat/completions")
    print(f"📊 统计端点:      http://{host}:{port}/v1/stats")
    print(f"🤖 默认模型:      {model} (effort: {effort})")
    print(f"🛡️ Hermes 防护 IP: {', '.join(sorted(effective_hermes_ips)) if effective_hermes_ips else '未配置'}")
    print(f"⚡ 最大本地并发:  {max_concurrency} (5 路安全排队)")
    print(f"🔧 AGY 路径:      {agy_bin} ({version})")
    print(f"📁 工作空间:      {workspace or os.getcwd()}")
    print(f"⏱️ 默认超时:      {timeout}s")
    print("-" * 68)
    print("支持任何 OpenAI 兼容客户端调用 (Base URL 填 http://127.0.0.1:8765/v1)")
    print("支持真流式打字机输出 (stream: true) 与模型别名映射")
    print("按 Ctrl+C 可停止代理服务。")
    print("=" * 68)

    class ConfiguredHandler(AgyProxyHandler):
        pass

    ConfiguredHandler.agy_bin = agy_bin
    ConfiguredHandler.timeout = timeout
    ConfiguredHandler.default_model = model
    ConfiguredHandler.default_effort = effort
    ConfiguredHandler.workspace = workspace or os.getcwd()
    ConfiguredHandler.hermes_ips = effective_hermes_ips

    server = ThreadingHTTPServer((host, port), ConfiguredHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Proxy] 服务已停止。")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity 本地通用 OpenAI 代理服务")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听 IP (默认: {DEFAULT_HOST})")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"监听端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"默认大模型 (默认: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT, help=f"思考程度 low|medium|high (默认: {DEFAULT_EFFORT})")
    parser.add_argument("--max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY, help=f"本地最大并发执行数 (默认: {DEFAULT_MAX_CONCURRENCY})")
    parser.add_argument("-t", "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="单次请求超时秒数")
    parser.add_argument("--agy-bin", default=None, help="指定 agy 命令行程序绝对路径")
    parser.add_argument("--workspace", default=None, help="指定工作目录")
    parser.add_argument(
        "--hermes-ip",
        action="append",
        default=None,
        help="指定 Hermes 客户端 IP 地址 (可多次指定或逗号分隔，默认: 192.168.6.192)",
    )

    args = parser.parse_args()

    hermes_ips = DEFAULT_HERMES_IPS.copy()
    if args.hermes_ip:
        custom_ips = set()
        for item in args.hermes_ip:
            for ip in item.split(","):
                if ip.strip():
                    custom_ips.add(ip.strip())
        if custom_ips:
            hermes_ips = custom_ips

    start_server(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        model=args.model,
        effort=args.effort,
        max_concurrency=args.max_concurrency,
        custom_agy=args.agy_bin,
        workspace=args.workspace,
        hermes_ips=hermes_ips,
    )


if __name__ == "__main__":
    main()
