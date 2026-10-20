#!/usr/bin/env python3
"""从 AA Data API + 公开详情页构建全量 models.json（每个 effort 变体单独成条）。

用法:
    AA_API_KEY=你的key python3 scripts/build-aa-kb.py

数据来源:
    - AA Data API 免费档: intelligence/coding/agentic/六维指数、价格、速度
    - AA 公开详情页（任一页面内嵌全量库）: 上下文窗口、模态、开源权重、许可证、推理 token 数

注意:
    - 每个 slug（含 effort 变体）单独成条，id 即 AA slug
    - blurb 为自动生成，标注「待润色」；前端可据此提示人工复核
    - 免费档不含 license/context，这两项来自详情页
"""

import json
import os
import re
import sys
import urllib.request

API_BASE = "https://artificialanalysis.ai/api/v2"
# 这两个页面内嵌全量模型库（700+ 条）；其他模型页只带同尺寸对比的 ~28 条
FULL_LIBRARY_PAGES = [
    "https://artificialanalysis.ai/models/solar-pro4",
    "https://artificialanalysis.ai/models/deepseek-v4-1-flash-non-reasoning",
]
OUT = "models.json"

# 旧版 52 条 KB 中人工整理的 id，AA 全量里没有同名 slug；
# 挂到对应 AA 条目上做别名，保证站点按旧名仍能匹配。
LEGACY_ALIASES = {
    "gpt-5-5-instant-06-26": ["gpt-5-5-instant"],
    "nova-2-0-pro-reasoning-medium": ["nova-2-0-pro-preview"],
    "solar-pro4": ["solar-pro-4"],
}

CAPABILITY_FIELDS = [
    ("artificial_analysis_finance_and_accounting_index", "finance_and_accounting"),
    ("artificial_analysis_strategy_and_ops_index", "strategy_and_ops"),
    ("artificial_analysis_legal_index", "legal"),
    ("artificial_analysis_healthcare_and_medical_index", "healthcare_and_medical"),
    ("artificial_analysis_engineering_index", "engineering"),
    ("artificial_analysis_economics_index", "economics"),
]
PRICE_FIELDS = [
    ("price_1m_input_tokens", "aa_input_usd_per_1m"),
    ("price_1m_output_tokens", "aa_output_usd_per_1m"),
    ("price_1m_cache_hit_tokens", "aa_cache_hit_usd_per_1m"),
    ("price_1m_cache_write_tokens", "aa_cache_write_usd_per_1m"),
]


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def fetch_api_rows(key):
    rows = []
    page = 1
    while True:
        url = f"{API_BASE}/language/models/free?page={page}"
        payload = json.loads(fetch(url, {"x-api-key": key, "Accept": "application/json"}))
        rows.extend(payload.get("data", []))
        if not (payload.get("pagination") or {}).get("has_more"):
            return rows, payload
        page += 1


def balanced(text, start, open_ch, close_ch):
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
    raise ValueError("unbalanced")


def fetch_detail_library():
    """详情页内嵌全量模型库，提取 slug -> 详情对象。优先全量页，不足再换。"""
    best = {}
    for page in FULL_LIBRARY_PAGES:
        try:
            html = fetch(page).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  [warn] {page} 失败: {e}", file=sys.stderr)
            continue
        chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
        text = "".join(chunks).encode().decode("unicode_escape")
        out = {}
        for cp in [m.start() for m in re.finditer(r'"capabilities":\{', text)]:
            before = text[max(0, cp - 4000):cp]
            starts = list(re.finditer(r'\{"id":"[a-f0-9-]{36}"', before))
            if not starts:
                continue
            try:
                obj = json.loads(balanced(text, max(0, cp - 4000) + starts[-1].start(), "{", "}"))
            except (ValueError, json.JSONDecodeError):
                continue
            if "slug" in obj and "capabilities" in obj:
                out.setdefault(obj["slug"], obj)
        if len(out) > len(best):
            best = out
        if len(best) >= 600:
            break
    return best


def r2(v):
    return round(v, 2) if v is not None else None


def speed_tier(tps):
    if tps is None:
        return None
    return "fast" if tps >= 200 else "normal" if tps >= 60 else "slow"


def price_tier(cost):
    if cost is None:
        return None
    return "budget" if cost <= 0.5 else "mid" if cost <= 2 else "premium"


def tier(idx):
    if idx is None:
        return "C"
    return "S" if idx >= 50 else "A" if idx >= 40 else "B" if idx >= 30 else "C"


def strengths_for(ev, detail):
    tags = []
    coding = ev.get("artificial_analysis_coding_index")
    agentic = ev.get("artificial_analysis_agentic_index")
    if coding is not None and coding >= 60:
        tags.append("coding")
    if agentic is not None and agentic >= 40:
        tags.append("agent")
    intel = ev.get("artificial_analysis_intelligence_index")
    if intel is not None and intel >= 50:
        tags.append("reasoning")
    if detail.get("inputModalityImage"):
        tags.append("vision")
    if detail.get("inputModalitySpeech") or detail.get("inputModalityVideo"):
        tags.append("audio")
    if detail.get("isOpenWeights"):
        tags.append("open-weights")
    tps = detail.get("outputSpeedVariance") or {}
    if tps.get("median") is not None and tps["median"] >= 200:
        tags.append("fast")
    if detail.get("contextWindowTokens") and detail["contextWindowTokens"] >= 256000:
        tags.append("long-context")
    return tags[:6]


def blurb_for(name, creator, ev, detail, is_variant, base_name):
    intel = ev.get("artificial_analysis_intelligence_index")
    coding = ev.get("artificial_analysis_coding_index")
    agentic = ev.get("artificial_analysis_agentic_index")
    parts_zh = []
    parts_en = []
    if intel is not None:
        parts_zh.append(f"AA 智力指数 {intel:.1f}")
        parts_en.append(f"AA index {intel:.1f}")
    if coding is not None:
        parts_zh.append(f"编码 {coding:.1f}")
        parts_en.append(f"coding {coding:.1f}")
    if agentic is not None:
        parts_zh.append(f"Agent {agentic:.1f}")
        parts_en.append(f"agent {agentic:.1f}")
    tps = (detail.get("outputSpeedVariance") or {}).get("median")
    if tps is not None:
        parts_zh.append(f"{tps:.0f} tok/s")
        parts_en.append(f"{tps:.0f} tok/s")
    ctx = detail.get("contextWindowTokens")
    if ctx:
        parts_zh.append(f"{ctx // 1000}k 上下文")
        parts_en.append(f"{ctx // 1000}k ctx")
    suffix = "（自动生成，待人工润色）" if parts_zh else "（自动生成，待人工润色）"
    tag = "[变体] " if is_variant else ""
    zh = f"{tag}{name}：" + "，".join(parts_zh) + suffix
    en = f"{tag}{name}: " + ", ".join(parts_en) + " (auto-generated, pending review)"
    return {"zh": zh[:120] if len(zh) > 120 else zh, "en": en[:160] if len(en) > 160 else en}


def normalize_slug(slug):
    """KB id 必须是 kebab-case，只含 a-z0-9-。"""
    s = slug.lower().replace(".", "-").replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s if s and s[0].isalnum() else "m-" + s


def main():
    key = os.environ.get("AA_API_KEY")
    if not key:
        sys.exit("缺少 AA_API_KEY 环境变量")

    print("拉取 API 全量 ...", file=sys.stderr)
    rows, payload = fetch_api_rows(key)
    print(f"  {len(rows)} 条", file=sys.stderr)
    print("拉取详情页全量库 ...", file=sys.stderr)
    details = fetch_detail_library()
    print(f"  {len(details)} 条", file=sys.stderr)

    models = []
    seen_ids = set()
    for row in rows:
        slug = row["slug"]
        det = details.get(slug) or {}
        ev = row.get("evaluations") or {}
        perf = row.get("performance") or {}
        pricing = row.get("pricing") or {}
        cost = ((row.get("artificial_analysis_intelligence_index_cost") or {}).get("cost_per_task") or {}).get("total_cost")

        kb_id = normalize_slug(slug)
        if kb_id in seen_ids:
            continue
        seen_ids.add(kb_id)

        name = row.get("name") or slug
        creator = (row.get("model_creator") or {}).get("name") or "Unknown"

        quality = {"tier": tier(ev.get("artificial_analysis_intelligence_index")), "as_of": "2026-10"}
        if ev.get("artificial_analysis_intelligence_index") is not None:
            quality["aa_intelligence_index"] = r2(ev["artificial_analysis_intelligence_index"])
        if ev.get("artificial_analysis_coding_index") is not None:
            quality["aa_coding_index"] = r2(ev["artificial_analysis_coding_index"])
        if ev.get("artificial_analysis_agentic_index") is not None:
            quality["aa_agentic_index"] = r2(ev["artificial_analysis_agentic_index"])

        entry = {
            "id": kb_id,
            "name": name[:80],
            "creator": creator[:60],
            "kind": "llm",
            "context_tokens": det.get("contextWindowTokens") or 0,
        }
        modalities = {"in": ["text"], "out": ["text"]}
        if det.get("inputModalityImage"):
            modalities["in"].append("image")
        if det.get("inputModalitySpeech"):
            modalities["in"].append("audio")
        if det.get("inputModalityVideo"):
            modalities["in"].append("video")
        if det.get("outputModalityImage"):
            modalities["out"].append("image")
        entry["modalities"] = modalities
        entry["quality"] = quality

        tps = (det.get("outputSpeedVariance") or {}).get("median") or perf.get("median_output_tokens_per_second")
        sp = {}
        if tps is not None:
            sp["median_tokens_per_s"] = r2(tps)
        ttft = (det.get("timeToFirstChunkVariance") or {}).get("median") or perf.get("median_time_to_first_token_seconds")
        if ttft is not None:
            sp["median_ttft_seconds"] = r2(ttft)
        if sp:
            t = speed_tier(sp.get("median_tokens_per_s"))
            if t:
                sp["tier"] = t
            sp["as_of"] = "2026-10"
            entry["speed"] = {k: sp[k] for k in ["tier", "median_tokens_per_s", "median_ttft_seconds", "as_of"] if k in sp}

        pr = {}
        if cost is not None:
            pr["aa_cost_per_task_usd"] = r2(cost)
        for aa, our in PRICE_FIELDS:
            v = pricing.get(aa)
            if v is None and det:
                v = det.get({"price_1m_input_tokens": "price1mInputTokens",
                             "price_1m_output_tokens": "price1mOutputTokens",
                             "price_1m_cache_hit_tokens": "cacheHitPrice",
                             "price_1m_cache_write_tokens": "cacheWritePrice"}[aa])
            if v is not None:
                pr[our] = r2(v)
        if pr:
            t = price_tier(pr.get("aa_cost_per_task_usd"))
            if t:
                pr["tier"] = t
            pr["as_of"] = "2026-10"
            entry["price"] = {k: pr[k] for k in ["tier", "aa_cost_per_task_usd", "aa_input_usd_per_1m",
                                                 "aa_output_usd_per_1m", "aa_cache_hit_usd_per_1m",
                                                 "aa_cache_write_usd_per_1m", "as_of"] if k in pr}

        caps = {}
        for aa, our in CAPABILITY_FIELDS:
            v = ev.get(aa)
            if v is None and det:
                v = (det.get("capabilities") or {}).get({
                    "finance_and_accounting": "financeAndAccounting",
                    "strategy_and_ops": "strategyAndOps",
                    "legal": "legal",
                    "healthcare_and_medical": "healthcareAndMedical",
                    "engineering": "engineering",
                    "economics": "economics",
                }[our])
            if v is not None:
                caps[our] = r2(v)
        if caps:
            caps["as_of"] = "2026-10"
            entry["capabilities"] = {k: caps[k] for k in [f for _, f in CAPABILITY_FIELDS] + ["as_of"] if k in caps}

        entry["strengths"] = strengths_for(ev, det)

        # effort 变体：把同一 release 的其他 effort 收进 quality.variants
        is_variant = bool(re.search(r"-(low|medium|high|xhigh|max)$", slug))
        base_name = (det.get("release") or {}).get("name") or re.sub(r"\s*\([^)]*\)\s*$", "", name)
        entry["blurb"] = blurb_for(name, creator, ev, det, is_variant, base_name)

        aliases = [slug, name]
        if det.get("release", {}).get("slug") and det["release"]["slug"] != slug:
            aliases.append(det["release"]["slug"])
        aliases.extend(LEGACY_ALIASES.get(slug, []))
        entry["aliases"] = list(dict.fromkeys(a for a in aliases if a))[:8]
        entry["open_weights"] = bool(det.get("isOpenWeights"))
        entry["sources"] = [f"https://artificialanalysis.ai/models/{slug}"]

        # 约束：name <=80, creator <=60, aliases>=1
        if not entry["name"]:
            entry["name"] = slug
        models.append(entry)

    out = {
        "schema_version": 2,
        "updated": "2026-10-20",
        "aa_intelligence_index_version": str(payload.get("intelligence_index_version") or ""),
        "source_note": {
            "zh": "质量分、六维能力、编码/Agent 分、速度与价格整理自 Artificial Analysis（2026-10）；blurb 为自动生成待人工润色。具体价格以站点自身定价为准。",
            "en": "Quality, six capability indexes, coding/agentic scores, speed and price from Artificial Analysis (Oct 2026); blurbs auto-generated pending review. Actual prices are set by the site.",
        },
        "models": models,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"写入 {OUT}: {len(models)} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
