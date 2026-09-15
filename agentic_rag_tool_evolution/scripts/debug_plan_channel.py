"""plan 通道拥塞计时测试（只读诊断，不改任何状态）。

A 组：10 次极短调用（max_tokens=8，timeout=90s），连续背靠背，看延迟分布与失败率；
B 组：1 次 Repair 式真实载荷（~2000 tokens 输入，max_tokens=3000，timeout=420s 非流式）；
C 组：1 次同样载荷的流式调用（看排队期间是否有首字节）。
"""

import sys, time, json
from pathlib import Path

sys.path.insert(0, "agentic_rag_self_learning/scripts")
sys.path.insert(0, "agentic_rag_tool_evolution/scripts")
import run_pilot as legacy
from blind_reconstruction import ARCHITECT_SYSTEM
from openai import OpenAI

env = legacy.load_experiment_env()
key = env["VOLCENGINE_API_KEY"]
base = env["TEACHER_BASE_URL"]
model = env["TEACHER_MODEL"]
print(f"端点: {base}  模型: {model}", flush=True)

def attempt(messages, max_tokens, timeout, stream=False):
    client = OpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=0)
    t0 = time.time()
    try:
        if stream:
            first = None
            n = 0
            with client.chat.completions.create(model=model, messages=messages,
                                                max_tokens=max_tokens, temperature=0, stream=True) as resp:
                for chunk in resp:
                    if first is None:
                        first = time.time() - t0
                    if chunk.choices and chunk.choices[0].delta.content:
                        n += 1
            return f"OK 首字节={first:.1f}s 总={time.time()-t0:.1f}s chunks={n}"
        resp = client.chat.completions.create(model=model, messages=messages,
                                              max_tokens=max_tokens, temperature=0)
        return f"OK {time.time()-t0:.1f}s 回复={ (resp.choices[0].message.content or '')[:20]!r}"
    except Exception as exc:
        return f"FAIL {time.time()-t0:.1f}s {type(exc).__name__}: {str(exc)[:100]}"

print("— A组：10 次短调用 —", flush=True)
lat = []
for i in range(10):
    r = attempt([{"role": "user", "content": "Reply with exactly: OK"}], 8, 90)
    print(f"A{i+1}: {r}", flush=True)

run_dir = Path("/Users/zhangqianyi/experiment_result/214result/DeepReadAddTool/hotpotqa/blind_20260909_152326")
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
print("— B组：Repair 真实载荷，非流式 max_tokens=3000 timeout=420s —", flush=True)
print("B:", attempt(messages, 3000, 420), flush=True)
print("— C组：同载荷，流式 —", flush=True)
print("C:", attempt(messages, 3000, 420, stream=True), flush=True)
print("[测试完成]", flush=True)
