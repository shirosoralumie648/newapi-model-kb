#!/usr/bin/env python3
"""从 Artificial Analysis 公开页面抓取 v2 能力数据，合并进 models.json。

用法:
    python3 scripts/fetch-aa-capabilities.py

数据来源（均为 AA 公开页面，无需 API key）:
    - 六维能力指数: https://artificialanalysis.ai/models/<slug>（每个模型自己的详情页）
    - 速度 / TTFT / 每百万 token 价格: https://artificialanalysis.ai/leaderboards/models

口径说明:
    - 六维能力取 detail 页模型对象的 capabilities（与 /indexes/<维度> 页面数值一致）
    - 速度取 outputSpeedVariance.median（tok/s），TTFT 取 timeToFirstChunkVariance.median（秒）
    - 价格取 price1m{Input,Output}Tokens / cacheHitPrice / cacheWritePrice（美元/百万 token）
    - 所有数值四舍五入到 2 位小数，与 AA 页面展示口径一致
    - 只填写 AA 有值的字段；AA 未测（null/缺失）的字段保持原样，不写 null
"""

import json
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; newapi-model-kb/1.0)"}
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"
LEADERBOARD_URL = "https://artificialanalysis.ai/leaderboards/models"

CAPABILITY_FIELDS = [
    ("financeAndAccounting", "finance_and_accounting"),
    ("strategyAndOps", "strategy_and_ops"),
    ("legal", "legal"),
    ("healthcareAndMedical", "healthcare_and_medical"),
    ("engineering", "engineering"),
    ("economics", "economics"),
]

# KB 的 id 与 AA 的 slug 不一致时，在这里映射（KB id -> AA slug）
AA_SLUG_OVERRIDES = {
    "gpt-5-5-instant": "gpt-5-5-instant-06-26",
    "nova-2-0-pro-preview": "nova-2-0-pro-reasoning-medium",
    "solar-pro-4": "solar-pro4",
}

PRICE_FIELDS = [
    ("price1mInputTokens", "aa_input_usd_per_1m"),
    ("price1mOutputTokens", "aa_output_usd_per_1m"),
    ("cacheHitPrice", "aa_cache_hit_usd_per_1m"),
    ("cacheWritePrice", "aa_cache_write_usd_per_1m"),
]


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def flight_text(html):
    """把 Next.js flight 数据解码成可解析的文本。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
    return "".join(chunks).encode().decode("unicode_escape")


def balanced_slice(text, start, open_ch, close_ch):
    """从 start 处的 open_ch 开始，返回到匹配 close_ch 为止（含）的子串。"""
    depth = 0
    j = start
    while j < len(text):
        c = text[j]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
        elif c == '"':
            j += 1
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
        j += 1
    raise ValueError("unbalanced slice")


def parse_model_detail(html, slug):
    """从模型详情页取出该模型自己的数据对象（含 capabilities / 速度 / 价格）。"""
    text = flight_text(html)
    for cp in [m.start() for m in re.finditer(r'"capabilities":\{', text)]:
        before = text[max(0, cp - 3000):cp]
        starts = list(re.finditer(r'\{"id":"[a-f0-9-]{36}"', before))
        if not starts:
            continue
        obj_start = max(0, cp - 3000) + starts[-1].start()
        try:
            obj = json.loads(balanced_slice(text, obj_start, "{", "}"))
        except (ValueError, json.JSONDecodeError):
            continue
        if obj.get("slug") == slug:
            return obj
    return None


def parse_leaderboard(html):
    """leaderboard 页面内嵌的全量模型表（速度/TTFT/价格）。"""
    text = flight_text(html)
    p = text.find('"initialModels":')
    if p < 0:
        return {}
    start = text.index("[", p)
    models = json.loads(balanced_slice(text, start, "[", "]"))
    return {m["slug"]: m for m in models if m.get("slug")}


def r2(v):
    return round(v, 2) if v is not None else None


def main():
    with open("models.json", encoding="utf-8") as f:
        kb = json.load(f)

    print("拉取 leaderboard ...", file=sys.stderr)
    lb = parse_leaderboard(fetch(LEADERBOARD_URL))
    print(f"  leaderboard 模型数: {len(lb)}", file=sys.stderr)

    updated = {}
    for model in kb["models"]:
        slug = model["id"]
        aa_slug = AA_SLUG_OVERRIDES.get(slug, slug)
        entry = {}

        # 六维能力 + 自有速度/价格（详情页）
        try:
            detail = parse_model_detail(fetch(MODEL_URL.format(slug=aa_slug)), aa_slug)
        except Exception as e:
            print(f"  [warn] {slug} 详情页失败: {e}", file=sys.stderr)
            detail = None
        if detail:
            caps = detail.get("capabilities") or {}
            got = {our: r2(caps.get(aa)) for aa, our in CAPABILITY_FIELDS}
            if any(v is not None for v in got.values()):
                got["as_of"] = "2026-10"
                entry["capabilities"] = got
            speed = detail.get("outputSpeedVariance") or {}
            ttft = detail.get("timeToFirstChunkVariance") or {}
            sp = {}
            if speed.get("median") is not None:
                sp["median_tokens_per_s"] = r2(speed["median"])
            if ttft.get("median") is not None:
                sp["median_ttft_seconds"] = r2(ttft["median"])
            if sp:
                sp["as_of"] = "2026-10"
                entry["_speed_extra"] = sp
            pr = {}
            for aa, our in PRICE_FIELDS:
                if detail.get(aa) is not None:
                    pr[our] = r2(detail[aa])
            if pr:
                pr["as_of"] = "2026-10"
                entry["_price_extra"] = pr

        # leaderboard 兜底：速度 / TTFT / 价格（detail 页缺某字段时逐字段回填）
        lm = lb.get(aa_slug) or {}
        sp = entry.pop("_speed_extra", {}) or {}
        if sp.get("median_tokens_per_s") is None and lm.get("medianOutputTokensPerSecond") is not None:
            sp["median_tokens_per_s"] = r2(lm["medianOutputTokensPerSecond"])
        if sp.get("median_ttft_seconds") is None and lm.get("medianTimeToFirstTokenSeconds") is not None:
            sp["median_ttft_seconds"] = r2(lm["medianTimeToFirstTokenSeconds"])
        if sp:
            sp.pop("as_of", None)
            sp["as_of"] = "2026-10"
            entry["_speed_extra"] = sp
        pr = entry.pop("_price_extra", {}) or {}
        for aa, our in PRICE_FIELDS:
            if pr.get(our) is None and lm.get(aa) is not None:
                pr[our] = r2(lm[aa])
        if pr:
            pr.pop("as_of", None)
            pr["as_of"] = "2026-10"
            entry["_price_extra"] = pr

        if entry:
            updated[slug] = entry
        print(f"  {slug}: caps={'Y' if 'capabilities' in entry else '-'} "
              f"speed={len(entry.get('_speed_extra', {})) - 1 if entry.get('_speed_extra') else 0} "
              f"price={len(entry.get('_price_extra', {})) - 1 if entry.get('_price_extra') else 0}",
              file=sys.stderr)

    with open("/tmp/aa-capabilities-draft.json", "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    print(f"\n写入 /tmp/aa-capabilities-draft.json，覆盖 {len(updated)} 个模型", file=sys.stderr)


if __name__ == "__main__":
    main()
