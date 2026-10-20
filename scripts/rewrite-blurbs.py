#!/usr/bin/env python3
"""用 LLM 逐条润色 models.json 里的 blurb（zh/en）。

用法:
    ANTHROPIC_BASE_URL=... ANTHROPIC_API_KEY=... python3 scripts/rewrite-blurbs.py \
        [--model opencode-go/kimi-k3] [--limit N] [--workers 8] [--only-top]

- 只改写 blurb 里带「自动生成，待人工润色」标记的条目
- 输入给模型的只有事实字段（分数、速度、价格、上下文、厂商、标签），不让它编造
- 输出严格要求 JSON {zh, en}；解析失败自动重试
- 结果写回 models.json，blurb 不再带「待润色」标记
- 按分数从高到低处理，低分模型的点评按事实简短给出
"""

import argparse
import json
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

KB = "models.json"
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "opencode-go/kimi-k3"

SYSTEM = """你是模型知识库的编辑，为 AI 模型广场写一句话点评。读者是想选模型的普通用户。

写作要求：
1. 中文**最多 60 字**，英文**最多 120 字符**（硬性上限，超了算失败）。一句话，可用分号连接两个分句。
2. 必须包含「这模型适合谁 / 什么场景」，不能只罗列分数。
3. 有对比时给对比（如"价格只有旗舰的零头""同系列性价比点"），让读者一眼知道定位。
4. 语气专业、直接、有判断，可以带轻微褒贬（如"别指望它做难题"），不要营销腔。
5. 只使用给定的事实字段，绝对不要编造训练数据、发布日期、具体能力细节等未给出的事实。
6. 如果字段缺失（价格/速度/能力分等），就不要提它，转向可用的信息。
7. 开源模型点出"可自部署"；低分模型直说定位（如"轻量/旧款/别用于难题"），不要吹。
8. 数字能省则省：只保留最能说明定位的 1~2 个数字，不要把所有分数都塞进去。

输出严格为 JSON，不要 markdown、不要解释：
{"zh": "...", "en": "..."}"""


def shorten(model, blurb):
    """超长时让模型压缩一轮。"""
    body = json.dumps({
        "model": model,
        "max_tokens": 300,
        "system": "把下面这句中英文点评压缩：中文不超过 60 字，英文不超过 120 字符，保留定位判断，只留最关键的数字。输出 JSON {\"zh\", \"en\"}。",
        "messages": [{"role": "user", "content": json.dumps(blurb, ensure_ascii=False)}],
    }).encode()
    req = urllib.request.Request(
        BASE_URL + "/v1/messages",
        data=body,
        headers={"x-api-key": API_KEY, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        payload = json.loads(r.read())
    text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("shorten: no JSON")
    obj = json.loads(m.group(0))
    return {"zh": obj["zh"].strip(), "en": obj["en"].strip()}


def facts_for(m):
    q = m.get("quality") or {}
    sp = m.get("speed") or {}
    pr = m.get("price") or {}
    caps = m.get("capabilities") or {}
    lines = [
        f"模型: {m['name']}",
        f"厂商: {m['creator']}",
        f"质量档: {q.get('tier')}（AA智力指数 {q.get('aa_intelligence_index')}）" if q.get("aa_intelligence_index") is not None
        else f"质量档: {q.get('tier')}（AA 未给智力指数）",
    ]
    if q.get("aa_coding_index") is not None:
        lines.append(f"编码分: {q['aa_coding_index']}")
    if q.get("aa_agentic_index") is not None:
        lines.append(f"Agent分: {q['aa_agentic_index']}")
    if sp.get("median_tokens_per_s") is not None:
        lines.append(f"速度: {sp['median_tokens_per_s']} tok/s（{sp.get('tier')}）")
    if sp.get("median_ttft_seconds") is not None:
        lines.append(f"首字延迟: {sp['median_ttft_seconds']} 秒")
    if pr.get("aa_cost_per_task_usd") is not None:
        lines.append(f"每任务成本: ${pr['aa_cost_per_task_usd']}（{pr.get('tier')}）")
    if pr.get("aa_input_usd_per_1m") is not None:
        lines.append(f"输入 ${pr['aa_input_usd_per_1m']}/M，输出 ${pr.get('aa_output_usd_per_1m', '?')}/M")
    lines.append(f"上下文: {m['context_tokens']} tokens")
    lines.append(f"开源权重: {'是' if m.get('open_weights') else '否'}")
    mods = (m.get("modalities") or {}).get("in") or []
    if len(mods) > 1:
        lines.append(f"输入模态: {', '.join(mods)}")
    if m.get("strengths"):
        lines.append(f"标签: {', '.join(m['strengths'])}")
    known = [k for k in ("finance_and_accounting", "strategy_and_ops", "legal",
                         "healthcare_and_medical", "engineering", "economics")
             if caps.get(k) is not None]
    if known:
        lines.append("六维能力齐全（" + ", ".join(known) + "）")
    return "\n".join(lines)


def call_llm(model, facts, retries=3):
    body = json.dumps({
        "model": model,
        "max_tokens": 500,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": "事实：\n" + facts + "\n\n请输出 JSON。"}],
    }).encode()
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            BASE_URL + "/v1/messages",
            data=body,
            headers={"x-api-key": API_KEY, "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                payload = json.loads(r.read())
            text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                raise ValueError("no JSON in reply: " + text[:120])
            obj = json.loads(m.group(0))
            zh, en = (obj.get("zh") or "").strip(), (obj.get("en") or "").strip()
            if not zh or not en:
                raise ValueError("empty zh/en")
            # schema 硬限 120/160；目标 60/120，超目标压缩一次
            if len(zh) > 60 or len(en) > 120:
                cand = shorten(model, {"zh": zh, "en": en})
                zh, en = cand["zh"], cand["en"]
            if not zh or not en:
                raise ValueError("empty after shorten")
            if len(zh) > 120 or len(en) > 160:
                raise ValueError(f"too long zh={len(zh)} en={len(en)}")
            return {"zh": zh, "en": en}
        except Exception as e:
            last_err = e
    raise last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--models", default="", help="逗号分隔的模型列表，worker 轮询分流")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only-top", type=int, default=0, help="只处理分数最高的 N 条")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not BASE_URL or not API_KEY:
        sys.exit("缺少 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY")

    models = [x.strip() for x in args.models.split(",") if x.strip()] or [args.model]

    with open(KB, encoding="utf-8") as f:
        kb = json.load(f)

    todo = [m for m in kb["models"] if "待人工润色" in m["blurb"]["zh"]]
    todo.sort(key=lambda m: -(m["quality"].get("aa_intelligence_index") or -999))
    if args.only_top:
        todo = todo[: args.only_top]
    if args.limit:
        todo = todo[: args.limit]
    print(f"待润色 {len(todo)} 条（模型 {models}，并发 {args.workers}）", file=sys.stderr)

    lock = threading.Lock()
    counter = {"n": 0}
    done = failed = 0

    def work(m):
        with lock:
            model = models[counter["n"] % len(models)]
            counter["n"] += 1
        facts = facts_for(m)
        return m, call_llm(model, facts)

    if args.dry_run:
        print(facts_for(todo[0]))
        return

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, m): m for m in todo}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                _, blurb = fut.result()
                m["blurb"] = blurb
                with lock:
                    done += 1
                    if done % 20 == 0 or done == len(todo):
                        print(f"  完成 {done}/{len(todo)}", file=sys.stderr)
                        with open(KB, "w", encoding="utf-8") as f:
                            json.dump(kb, f, ensure_ascii=False, indent=2)
                            f.write("\n")
            except Exception as e:
                with lock:
                    failed += 1
                    print(f"  [fail] {m['id']}: {e}", file=sys.stderr)

    with open(KB, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"完成 {done}，失败 {failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
