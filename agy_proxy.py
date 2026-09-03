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

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_CONCURRENCY = 5

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
    "Access-Control-Max-Age": "86400",
}

# 常见客户端模型别名映射表
MODEL_ALIASES: dict[str, str] = {
    # OpenAI 常见别名
    "gpt-4o": "gemini-3.8-flash",
    "gpt-4o-mini": "gemini-3.8-flash",
    "gpt-4": "gemini-3.8-flash",
    "gpt-4-turbo": "gemini-3.8-flash",
    "gpt-3.5-turbo": "gemini-3.8-flash",
    "o1": "gemini-3.8-flash",
    "o3-mini": "gemini-3.8-flash",
    # Claude 常见别名
    "claude-3-5-sonnet": "gemini-3.8-flash",
    "claude-3-7-sonnet": "gemini-3.8-flash",
    "claude-3-opus": "gemini-3.8-flash",
    "claude-3-haiku": "gemini-3.8-flash",
    # Gemini / Antigravity 别名
    "gemini-2.5-pro": "gemini-3.8-flash",
    "gemini-2.0-flash": "gemini-3.8-flash",
    "gemini-1.5-pro": "gemini-3.8-flash",
    "gemini-1.5-flash": "gemini-3.8-flash",
    "antigravity": "gemini-3.8-flash",
}


# ==============================================================================
# 统计监控管理器 (StatsTracker)
# ==============================================================================
class StatsTracker:
    """线程安全的统计管理器，支持输入/输出/缓存命中率与本地 JSON 持久化."""

    def __init__(self, storage_path: pathlib.Path | None = None, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        self.lock = threading.Lock()
        self.storage_path = storage_path or (pathlib.Path(__file__).parent / ".stats.json")
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
        status: str,  # "success" | "error" | "timeout"
        error_msg: str | None = None,
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

            record = {
                "id": f"req-{uuid.uuid4().hex[:8]}",
                "timestamp": dt.datetime.now().strftime("%H:%M:%S"),
                "date": dt.datetime.now().strftime("%Y-%m-%d"),
                "model": model,
                "is_stream": is_stream,
                "duration": round(duration, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "tps": tps,
                "status": status,
                "error": error_msg,
            }
            self.recent_history.append(record)
            if len(self.recent_history) > 50:
                self.recent_history.pop(0)

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
    """标准化模型名称并自动补充 effort 参数，支持模型别名智能映射."""
    if not model_name or not isinstance(model_name, str) or not model_name.strip():
        return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)

    raw = model_name.strip().lower()

    # 1. 显式支持 3.7
    if raw in ("3.7-flash", "3 7 flash", "gemini-3.7-flash"):
        return "gemini-3.7-flash", (effort or "high")

    # 2. 别名表匹配
    if raw in MODEL_ALIASES:
        return MODEL_ALIASES[raw], (effort or DEFAULT_EFFORT)

    # 3. 常见模型前缀匹配（如 gpt-、claude- 等）
    if any(raw.startswith(prefix) for prefix in ("gpt-", "claude-", "o1", "o3", "deepseek")):
        return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)

    # 4. 默认兜底至 gemini-3.8-flash
    return DEFAULT_MODEL, (effort or DEFAULT_EFFORT)


def build_agy_prompt(messages: list[dict[str, Any]], response_format: dict[str, Any] | None = None) -> str:
    """将 OpenAI 格式的 messages 列表转换为 Antigravity prompt."""
    system_parts: list[str] = []
    user_parts: list[str] = []

    for msg in messages:
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
        else:
            content_str = str(content)

        if role in ("system", "developer"):
            system_parts.append(content_str)
        elif role == "user":
            user_parts.append(f"User: {content_str}")
        elif role == "assistant":
            user_parts.append(f"Assistant: {content_str}")

    prompt_lines: list[str] = []
    if system_parts:
        prompt_lines.append("【系统指令 / System Instructions】")
        prompt_lines.extend(system_parts)
        prompt_lines.append("")

    if user_parts:
        prompt_lines.append("【上下文与用户输入 / Context & User Prompt】")
        prompt_lines.extend(user_parts)

    if response_format and isinstance(response_format, dict):
        rf_type = response_format.get("type")
        if rf_type == "json_object":
            prompt_lines.append("")
            prompt_lines.append("【关键格式要求】")
            prompt_lines.append("你必须仅输出合法、纯净的 JSON 字符串。不要添加任何前言、解释或 Markdown 代码块标记（如 ```json）。")

    return "\n".join(prompt_lines).strip()


# ==============================================================================
# 核心调用流式生成器
# ==============================================================================
def run_agy_stream_generator(
    agy_bin: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
    workspace: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
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
    ]

    if final_model:
        cmd.extend(["--model", final_model])
    if final_effort:
        cmd.extend(["--effort", final_effort])

    cwd = workspace or os.getcwd()

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
        proc.kill()
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

    deadline = time.monotonic() + timeout

    try:
        while True:
            if time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError(f"Antigravity CLI 执行超时 ({timeout}s)")

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
            if event_name == "step_update":
                step = event_obj.get("step_update", {})
                if step.get("step_type") == "agent_response":
                    delta = step.get("text_delta")
                    usage = step.get("usage")
                    if isinstance(usage, dict):
                        usage_info["prompt_tokens"] = usage.get("input_tokens", usage_info["prompt_tokens"])
                        usage_info["completion_tokens"] = usage.get("output_tokens", usage_info["completion_tokens"])
                        usage_info["cached_tokens"] = usage.get("cache_read_tokens") or usage.get("cached_tokens") or usage_info["cached_tokens"]
                        usage_info["thinking_tokens"] = usage.get("thinking_tokens", usage_info["thinking_tokens"])
                        usage_info["total_tokens"] = usage.get("total_tokens", usage_info["total_tokens"])

                    if isinstance(delta, str) and delta:
                        collected_fragments.append(delta)
                        yield ("delta", delta, usage_info, None)

            elif event_name == "result":
                res = event_obj.get("result", {})
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

        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), 9)
            else:
                proc.kill()
        except Exception:
            pass
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

        if path in ("/v1/models", "/models"):
            body = {
                "object": "list",
                "data": [
                    {
                        "id": "gemini-3.8-flash",
                        "object": "model",
                        "created": 1788100000,
                        "owned_by": "google",
                    },
                    {
                        "id": "gemini-3.7-flash",
                        "object": "model",
                        "created": 1788000000,
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

        prompt = build_agy_prompt(messages, response_format)
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
                self._handle_stream_completions(prompt, model, effort, final_model)
            else:
                self._handle_block_completions(prompt, model, effort, final_model, response_format)
        finally:
            CONCURRENCY_SEMAPHORE.release()

    def _handle_stream_completions(self, prompt: str, model: str, effort: str, final_model: str) -> None:
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

        print(f"[Proxy] -> 正在流式调用 Antigravity (模型: {final_model}, 字符数: {len(prompt)})...")
        t_start = time.monotonic()
        final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0, "thinking_tokens": 0}
        duration = 0.0

        try:
            for evt in run_agy_stream_generator(
                agy_bin=self.agy_bin,
                prompt=prompt,
                model=model,
                effort=effort,
                workspace=self.workspace,
                timeout=self.timeout,
            ):
                if evt[0] == "delta":
                    delta_chunk = evt[1]
                    chunk_obj = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": final_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta_chunk},
                                "finish_reason": None,
                            }
                        ],
                    }
                    self.wfile.write(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                elif evt[0] == "done":
                    final_usage = evt[2]
                    duration = evt[3]

            openai_usage = {
                "prompt_tokens": final_usage.get("prompt_tokens", 0),
                "completion_tokens": final_usage.get("completion_tokens", 0),
                "total_tokens": final_usage.get("total_tokens", 0),
            }

            # 最终 Stop 块
            stop_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": final_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
                "usage": openai_usage,
            }
            self.wfile.write(f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True

            tps = round(final_usage.get("completion_tokens", 0) / duration, 1) if duration > 0 else 0.0
            print(f"[Proxy] <- 流式完成 (耗时: {duration:.2f}s, 入: {final_usage.get('prompt_tokens')}, 出: {final_usage.get('completion_tokens')}, 速率: {tps} tps)")

            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=True,
                duration=duration,
                prompt_tokens=final_usage.get("prompt_tokens", 0),
                completion_tokens=final_usage.get("completion_tokens", 0),
                status="success",
            )
        except TimeoutError as e:
            print(f"[Proxy] !! 流式超时: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=True,
                duration=time.monotonic() - t_start,
                prompt_tokens=0,
                completion_tokens=0,
                status="timeout",
                error_msg=str(e),
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
            )
            err_data = {"error": {"message": str(e), "type": "internal_error"}}
            self.wfile.write(f"data: {json.dumps(err_data)}\n\n".encode("utf-8"))
            self.wfile.flush()

    def _handle_block_completions(
        self, prompt: str, model: str, effort: str, final_model: str, response_format: dict[str, Any] | None
    ) -> None:
        """处理非流式完整响应."""
        print(f"[Proxy] -> 正在调用 Antigravity (模型: {final_model}, 字符数: {len(prompt)})...")
        t_start = time.monotonic()

        try:
            output_text, usage, duration = run_agy_stream_json(
                agy_bin=self.agy_bin,
                prompt=prompt,
                model=model,
                effort=effort,
                workspace=self.workspace,
                timeout=self.timeout,
            )
            tps = round(usage.get("completion_tokens", 0) / duration, 1) if duration > 0 else 0.0
            print(f"[Proxy] <- 调用成功 (耗时: {duration:.2f}s, 入: {usage.get('prompt_tokens')}, 出: {usage.get('completion_tokens')}, 速率: {tps} tps)")

            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=False,
                duration=duration,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                status="success",
            )
        except TimeoutError as e:
            print(f"[Proxy] !! 超时: {e}")
            GLOBAL_STATS.record_finish(
                model=final_model,
                is_stream=False,
                duration=time.monotonic() - t_start,
                prompt_tokens=0,
                completion_tokens=0,
                status="timeout",
                error_msg=str(e),
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
            )
            self._send_json_response(500, {"error": {"message": str(e), "type": "internal_error"}})
            return

        if response_format and isinstance(response_format, dict) and response_format.get("type") == "json_object":
            clean_text = extract_json_content(output_text)
        else:
            clean_text = output_text

        response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        openai_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        openai_response = {
            "id": response_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": final_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": clean_text,
                    },
                    "finish_reason": "stop",
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
) -> None:
    global CONCURRENCY_SEMAPHORE
    CONCURRENCY_SEMAPHORE = threading.BoundedSemaphore(max(1, max_concurrency))
    GLOBAL_STATS.max_concurrency = max_concurrency

    agy_bin = find_agy_binary(custom_agy)
    version = get_agy_version(agy_bin)

    print("=" * 68)
    print("🚀 Antigravity 通用本地 OpenAI 兼容 API 代理服务 (生产增强版)")
    print("=" * 68)
    print(f"📍 监听地址:      http://{host}:{port}/v1")
    print(f"🌐 对应端点:      http://{host}:{port}/v1/chat/completions")
    print(f"📊 统计端点:      http://{host}:{port}/v1/stats")
    print(f"🤖 默认模型:      {model} (effort: {effort})")
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

    args = parser.parse_args()
    start_server(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        model=args.model,
        effort=args.effort,
        max_concurrency=args.max_concurrency,
        custom_agy=args.agy_bin,
        workspace=args.workspace,
    )


if __name__ == "__main__":
    main()
