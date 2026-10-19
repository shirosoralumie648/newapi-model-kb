#!/usr/bin/env python3
"""从 Artificial Analysis Data API 免费档拉取数据，生成本仓库 models.json 的候选草稿。

用法:
    AA_API_KEY=你的key python3 scripts/fetch-aa-draft.py > draft.json

- 需要 AA API key（免费档 100 请求/24h，全量约 2 页，每天拉一次绰绰有余）
  申请入口: https://artificialanalysis.ai/api-key-management-redirect
- 输出是**草稿**：模型名、别名、档位、点评必须人工审核后再合入 models.json
- 免费档**不含**上下文窗口、开源权重、模态字段（Pro 档才有），这三项继续人工维护
- AA 要求 attribution：展示其数据时标注来源（见 README）
"""

import json
import os
import sys
import urllib.request

API_BASE = "https://artificialanalysis.ai/api/v2"
DOCS_URL = "https://artificialanalysis.ai/data-api/docs"

# 六维能力指数：AA 字段名 -> 本仓库字段名
CAPABILITY_FIELDS = [
    ("artificial_analysis_finance_and_accounting_index", "finance_and_accounting"),
    ("artificial_analysis_strategy_and_ops_index", "strategy_and_ops"),
    ("artificial_analysis_legal_index", "legal"),
    ("artificial_analysis_healthcare_and_medical_index", "healthcare_and_medical"),
    ("artificial_analysis_engineering_index", "engineering"),
    ("artificial_analysis_economics_index", "economics"),
]


def fetch_all_pages(key):
    """免费档每页 200 条，翻完 has_more 为止。"""
    models = []
    last_payload = {}
    page = 1
    while True:
        url = f"{API_BASE}/language/models/free?page={page}"
        req = urllib.request.Request(url, headers={"x-api-key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        models.extend(payload.get("data", []))
        last_payload = payload
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more"):
            break
        page += 1
    return last_payload, models


def first_non_null(*values):
    for v in values:
        if v is not None:
            return v
    return None


def to_draft(payload, rows):
    models = []
    for m in rows:
        ev = m.get("evaluations") or {}
        idx = ev.get("artificial_analysis_intelligence_index")
        tps = (m.get("performance") or {}).get("median_output_tokens_per_second")
        ttft = (m.get("performance") or {}).get("median_time_to_first_token_seconds")
        pricing = m.get("pricing") or {}
        cost = ((m.get("artificial_analysis_intelligence_index_cost") or {}).get("cost_per_task") or {}).get("total_cost")
        entry = {
            "id": m.get("slug") or (m.get("name") or "").lower().replace(".", "-").replace("_", "-"),
            "name": m.get("name"),
            "creator": (m.get("model_creator") or {}).get("name"),
            "kind": "llm",
            "quality": {
                "tier": "S" if (idx or 0) >= 50 else "A" if (idx or 0) >= 40 else "B" if (idx or 0) >= 30 else "C",
                "aa_intelligence_index": idx,
                "as_of": "REVIEW",  # 填抓取月份
            },
        }
        for aa_field, our_field in (("artificial_analysis_coding_index", "aa_coding_index"),
                                    ("artificial_analysis_agentic_index", "aa_agentic_index")):
            if ev.get(aa_field) is not None:
                entry["quality"][our_field] = ev[aa_field]
        # 六维能力指数：全 null 就不写该字段
        caps = {our: ev.get(aa) for aa, our in CAPABILITY_FIELDS}
        if any(v is not None for v in caps.values()):
            caps["as_of"] = "REVIEW"
            entry["capabilities"] = caps
        if tps is not None or ttft is not None:
            speed = {"as_of": "REVIEW"}
            if tps is not None:
                speed["tier"] = "fast" if tps >= 200 else "normal" if tps >= 60 else "slow"
                speed["median_tokens_per_s"] = tps
            if ttft is not None:
                speed["median_ttft_seconds"] = ttft
            entry["speed"] = speed
        if cost is not None or pricing:
            price = {"as_of": "REVIEW"}
            if cost is not None:
                price["tier"] = "budget" if cost <= 0.5 else "mid" if cost <= 2 else "premium"
                price["aa_cost_per_task_usd"] = cost
            for aa_field, our_field in (
                ("price_1m_input_tokens", "aa_input_usd_per_1m"),
                ("price_1m_output_tokens", "aa_output_usd_per_1m"),
                ("price_1m_cache_hit_tokens", "aa_cache_hit_usd_per_1m"),
                ("price_1m_cache_write_tokens", "aa_cache_write_usd_per_1m"),
            ):
                if pricing.get(aa_field) is not None:
                    price[our_field] = pricing[aa_field]
            entry["price"] = price
        entry["context_tokens"] = None   # 免费档不含，人工从 Pro 页/模型文档补
        entry["strengths"] = []          # 人工填写
        entry["blurb"] = {"zh": "TODO 人工改写", "en": "TODO rewrite by hand"}
        entry["aliases"] = [entry["id"]]  # 人工补全站点上的别名
        entry["open_weights"] = False     # 免费档不含 licensing，人工确认
        entry["sources"] = ["https://artificialanalysis.ai/models/" + entry["id"]]
        models.append(entry)
    return {
        "schema_version": 2,
        "updated": "REVIEW",
        "aa_intelligence_index_version": payload.get("intelligence_index_version"),
        "source_note": {
            "zh": "草稿：生成后需人工审核全部条目（含别名/点评/as_of/上下文窗口/开源权重）。",
            "en": "Draft: review every entry (aliases, blurbs, as_of, context, licensing) by hand before merging.",
        },
        "models": models,
    }


if __name__ == "__main__":
    key = os.environ.get("AA_API_KEY")
    if not key:
        sys.exit("缺少 AA_API_KEY 环境变量。到 " + DOCS_URL + " 免费获取。")
    payload, rows = fetch_all_pages(key)
    print(json.dumps(to_draft(payload, rows), ensure_ascii=False, indent=2))
