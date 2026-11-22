#!/usr/bin/env python3
"""测试 Antigravity 本地代理服务的 OpenAI 兼容接口（含非流式、流式 SSE、别名与统计端点）."""

import json
import time
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8765/v1"

def test_health():
    print("1. 测试 /health 健康检查...")
    req = urllib.request.Request("http://127.0.0.1:8765/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        print(f"   [成功] 状态: {data.get('status')}, 版本: {data.get('agy_version')}")
        print(f"   统计概览: {data.get('stats_summary')}")

def test_models():
    print("\n2. 测试 /v1/models 模型列表...")
    req = urllib.request.Request(f"{BASE_URL}/models")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get("data", [])]
        print(f"   [成功] 获得 {len(models)} 个模型: {', '.join(models)}")

def test_chat_non_stream():
    print("\n3. 测试 /v1/chat/completions 阻塞调用 (使用别名: gpt-4o)...")
    payload = {
        "model": "gpt-4o",  # 测试模型别名映射
        "messages": [
            {"role": "system", "content": "简短回答，不超过20个字。"},
            {"role": "user", "content": "你好，请报出当前时间或一句简短问候。"}
        ],
        "stream": False
    }
    t0 = time.time()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
        elapsed = round(time.time() - t0, 2)
        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        print(f"   [成功] 回复: {content}")
        print(f"   耗时: {elapsed}s | 模型实际回落: {data.get('model')} | Usage: {usage}")

def test_chat_stream():
    print("\n4. 测试 /v1/chat/completions 真正 SSE 流式输出 (stream: true)...")
    payload = {
        "model": "gemini-4-hydrogen",
        "messages": [
            {"role": "user", "content": "请用五道菜名组成一首打油诗，每句一道菜。"}
        ],
        "stream": True
    }
    t0 = time.time()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    print("   [流式接收中] -> ", end="", flush=True)
    chunks_count = 0
    full_content = []
    with urllib.request.urlopen(req, timeout=60) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if not line_str or not line_str.startswith("data:"):
                continue
            data_str = line_str[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    chunks_count += 1
                    full_content.append(delta)
                    print(delta, end="", flush=True)
            except Exception:
                pass
    elapsed = round(time.time() - t0, 2)
    print(f"\n   [成功] 流式接收完毕! 共收 {chunks_count} 个 SSE 数据块，总耗时 {elapsed}s")

def test_stats():
    print("\n5. 测试 /v1/stats 运行统计数据端点...")
    req = urllib.request.Request(f"{BASE_URL}/stats")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        print(f"   [成功] 统计详情:")
        print(f"     - 总调用次数: {data.get('total_requests')}")
        print(f"     - 成功率: {data.get('success_rate')}%")
        print(f"     - 累计消耗 Tokens: {data.get('total_tokens')} (输入: {data.get('total_prompt_tokens')}, 输出: {data.get('total_completion_tokens')})")
        print(f"     - 平均响应耗时: {data.get('avg_duration')}s")
        print(f"     - 平均生成速率 (TPS): {data.get('avg_tps')} tokens/s")
        print(f"     - 最近历史条数: {len(data.get('recent_history', []))}")

if __name__ == "__main__":
    try:
        test_health()
        test_models()
        test_chat_non_stream()
        test_chat_stream()
        test_stats()
        print("\n🎉 全部接口与特性测试通过！")
    except urllib.error.URLError as e:
        print(f"\n❌ 连接失败: {e}")
        print("请确保已执行 ./start.sh 或 python3 agy_proxy.py 启动代理服务。")
