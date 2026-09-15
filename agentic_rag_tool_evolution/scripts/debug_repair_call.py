"""排查 Repair Agent 调用 504 的计时探针（不改变任何实验状态）。

精确重构 blind_reconstruction 里 Repair Agent 的那次调用（同样的 system prompt、
同样的 analysis 输入），然后做两组实验：

  A. max_tokens 阶梯（16 / 1000 / 3000 / 6000，非流式）：定位是否为"生成时长"触网
     关超时——若小 max_tokens 全通、大 max_tokens 必 504，则与输入长度无关。
  B. 同样 6000 max_tokens 的流式调用：流式首字节快、持续有数据，可绕开网关空闲超时。

用法：python debug_repair_call.py --run-dir <blind运行目录> [--skip-large]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(WORKSPACE / "agentic_rag_self_learning" / "scripts"))

import run_pilot as legacy  # noqa: E402
from blind_reconstruction import ARCHITECT_SYSTEM  # noqa: E402

import tiktoken  # noqa: E402
from openai import OpenAI  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


def timed_call(client: OpenAI, model: str, messages: list, max_tokens: int, stream: bool) -> None:
    label = f"max_tokens={max_tokens}{' stream' if stream else ''}"
    started = time.time()
    try:
        if stream:
            chunks: list[str] = []
            first_token_at: float | None = None
            with client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0, stream=True
            ) as response:
                for chunk in response:
                    if first_token_at is None:
                        first_token_at = time.time() - started
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        chunks.append(delta)
            elapsed = time.time() - started
            say(
                f"  [OK] {label}: 首字节 {first_token_at:.1f}s，总耗时 {elapsed:.1f}s，"
                f"收到 {len(''.join(chunks))} 字符"
            )
        else:
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0
            )
            elapsed = time.time() - started
            content = response.choices[0].message.content or ""
            say(f"  [OK] {label}: 总耗时 {elapsed:.1f}s，收到 {len(content)} 字符")
    except Exception as exc:
        elapsed = time.time() - started
        text = str(exc).replace("\n", " ")[:160]
        say(f"  [FAIL] {label}: {elapsed:.1f}s 后 {type(exc).__name__}: {text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="包含 analysis.json/blind_packet.json 的 blind 运行目录")
    parser.add_argument("--skip-large", action="store_true", help="只跑到 1000 tokens 的短调用")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    analysis = legacy.load_json(run_dir / "analysis.json")
    packet = legacy.load_json(run_dir / "blind_packet.json")

    architect_input = {
        "analysis": analysis,
        "observed_baseline_tool_names": packet["available_baseline_tools_observed_in_trajectories"],
        "constraint": "Build one general tool from the diagnosis; do not use test data or benchmark-specific IDs.",
    }
    messages = [
        {"role": "system", "content": ARCHITECT_SYSTEM},
        {"role": "user", "content": json.dumps(architect_input, ensure_ascii=False)},
    ]

    encoder = tiktoken.get_encoding("cl100k_base")
    for message in messages:
        tokens = len(encoder.encode(message["content"]))
        say(f"[载荷] role={message['role']}: {len(message['content'])} 字符 ≈ {tokens} tokens")

    env = legacy.load_experiment_env()
    client = OpenAI(
        api_key=env.get("TEACHER_API_KEY") or env["VOLCENGINE_API_KEY"],
        base_url=env["TEACHER_BASE_URL"],
        timeout=600,
        max_retries=0,
    )
    say(f"[端点] {env['TEACHER_BASE_URL']} 模型={env['TEACHER_MODEL']}")

    say("— A组：非流式，max_tokens 阶梯 —")
    for max_tokens in ([16, 1000] if args.skip_large else [16, 1000, 3000, 6000]):
        timed_call(client, env["TEACHER_MODEL"], messages, max_tokens, stream=False)

    if not args.skip_large:
        say("— B组：流式，max_tokens=6000 —")
        timed_call(client, env["TEACHER_MODEL"], messages, 6000, stream=True)

    say("[探针完成] 把以上输出贴回来即可定位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
