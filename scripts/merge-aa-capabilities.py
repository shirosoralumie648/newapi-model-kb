#!/usr/bin/env python3
"""把 fetch-aa-capabilities.py 生成的草稿合并进 models.json。

用法:
    python3 scripts/fetch-aa-capabilities.py   # 生成 /tmp/aa-capabilities-draft.json
    python3 scripts/merge-aa-capabilities.py   # 合并进 models.json

合并原则:
    - 只补不覆盖：已有非空字段一律保留（人工审核过的值优先）
    - capabilities / speed / price 逐字段合并，不整块替换
    - 新增 price 对象时按 README 划线推导 tier（有 aa_cost_per_task_usd 才推导）
    - 新增 speed 对象时按 median_tokens_per_s 推导 tier
    - 合并后自动跑 schema 校验
"""

import json
import sys

DRAFT = "/tmp/aa-capabilities-draft.json"
KB = "models.json"
SCHEMA = "schema.json"

CAP_KEYS = [
    "finance_and_accounting", "strategy_and_ops", "legal",
    "healthcare_and_medical", "engineering", "economics",
]
PRICE_KEYS = [
    "aa_input_usd_per_1m", "aa_output_usd_per_1m",
    "aa_cache_hit_usd_per_1m", "aa_cache_write_usd_per_1m",
]


def speed_tier(tps):
    if tps is None:
        return None
    return "fast" if tps >= 200 else "normal" if tps >= 60 else "slow"


def price_tier(cost):
    if cost is None:
        return None
    return "budget" if cost <= 0.5 else "mid" if cost <= 2 else "premium"


def main():
    with open(DRAFT, encoding="utf-8") as f:
        draft = json.load(f)
    with open(KB, encoding="utf-8") as f:
        kb = json.load(f)

    stats = {"caps": 0, "ttft": 0, "price": 0}
    for model in kb["models"]:
        d = draft.get(model["id"])
        if not d:
            continue
        changed = False

        caps_in = d.get("capabilities") or {}
        if caps_in:
            caps = model.setdefault("capabilities", {})
            for k in CAP_KEYS:
                if caps_in.get(k) is not None and caps.get(k) is None:
                    caps[k] = caps_in[k]
                    changed = True
            if not any(caps.get(k) is not None for k in CAP_KEYS):
                del model["capabilities"]
            elif changed:
                caps["as_of"] = caps_in.get("as_of", "2026-10")
                stats["caps"] += 1

        sp_in = d.get("_speed_extra") or {}
        ttft = sp_in.get("median_ttft_seconds")
        tps = sp_in.get("median_tokens_per_s")
        if ttft is not None or tps is not None:
            speed = model.setdefault("speed", {})
            if tps is not None and speed.get("median_tokens_per_s") is None:
                speed["median_tokens_per_s"] = tps
                changed = True
            if ttft is not None and speed.get("median_ttft_seconds") is None:
                speed["median_ttft_seconds"] = ttft
                changed = True
            if "tier" not in speed:
                tier = speed_tier(speed.get("median_tokens_per_s"))
                if tier:
                    speed["tier"] = tier
            speed.setdefault("as_of", sp_in.get("as_of", "2026-10"))
            if changed:
                stats["ttft"] += 1

        pr_in = d.get("_price_extra") or {}
        if pr_in:
            price = model.setdefault("price", {})
            for k in PRICE_KEYS:
                if pr_in.get(k) is not None and price.get(k) is None:
                    price[k] = pr_in[k]
                    changed = True
            if "tier" not in price:
                tier = price_tier(price.get("aa_cost_per_task_usd"))
                if tier:
                    price["tier"] = tier
            price.setdefault("as_of", pr_in.get("as_of", "2026-10"))
            if changed:
                stats["price"] += 1

    with open(KB, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"合并完成: {stats}", file=sys.stderr)

    try:
        import jsonschema
        with open(SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        with open(KB, encoding="utf-8") as f:
            data = json.load(f)
        jsonschema.Draft202012Validator(schema).validate(data)
        print("schema 校验通过", file=sys.stderr)
    except ImportError:
        print("（未安装 jsonschema，跳过校验）", file=sys.stderr)


if __name__ == "__main__":
    main()
