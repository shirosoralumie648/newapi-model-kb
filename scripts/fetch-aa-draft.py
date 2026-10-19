#!/usr/bin/env python3
"""从 Artificial Analysis Data API 拉取语言模型榜单，生成本仓库 models.json 的候选草稿。

用法:
    AA_API_KEY=你的key python3 scripts/fetch-aa-draft.py > draft.json

- 需要 AA API key（免费档 100 请求/天，每天拉一次绰绰有余）: https://artificialanalysis.ai/api-key-management-redirect
- 输出是**草稿**：模型名、别名、档位、点评都需要人工审核后再合入 models.json。
- AA 要求 attribution：展示其数据时标注来源（见 README）。
"""

import json
import os
import sys
import urllib.request

API_URL = "https://artificialanalysis.ai/api/v2/language/models"
DOCS_URL = "https://artificialanalysis.ai/data-api/docs"


def fetch_models():
    key = os.environ.get("AA_API_KEY")
    if not key:
        sys.exit("缺少 AA_API_KEY 环境变量。到 " + DOCS_URL + " 免费获取。")
    req = urllib.request.Request(API_URL, headers={"x-api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def to_draft(payload):
    """把 AA 响应折算成本仓库条目结构的草稿。字段名以 AA OpenAPI 实际返回为准:
    https://artificialanalysis.ai/api/v2/openapi
    """
    models = []
    for m in payload.get("data", []):
        idx = m.get("artificial_analysis_intelligence_index")
        tps = m.get("median_output_tokens_per_second")
        cost = m.get("cost_per_task_usd")
        entry = {
            "id": m.get("slug") or (m.get("model_name") or "").lower().replace(".", "-").replace("_", "-"),
            "name": m.get("model_name"),
            "creator": m.get("creator"),
            "kind": "llm",
            "context_tokens": m.get("context_window"),
            "quality": {
                "tier": "S" if (idx or 0) >= 50 else "A" if (idx or 0) >= 40 else "B" if (idx or 0) >= 30 else "C",
                "aa_intelligence_index": idx,
                "as_of": "REVIEW",  # 填抓取月份
            },
        }
        if tps is not None:
            entry["speed"] = {
                "tier": "fast" if tps >= 200 else "normal" if tps >= 60 else "slow",
                "median_tokens_per_s": tps,
                "as_of": "REVIEW",
            }
        if cost is not None:
            entry["price"] = {
                "tier": "budget" if cost <= 0.5 else "mid" if cost <= 2 else "premium",
                "aa_cost_per_task_usd": cost,
                "as_of": "REVIEW",
            }
        entry["strengths"] = []          # 人工填写
        entry["blurb"] = {"zh": "TODO 人工改写", "en": "TODO rewrite by hand"}
        entry["aliases"] = [entry["id"]]  # 人工补全站点上的别名
        entry["open_weights"] = False     # 人工确认
        entry["sources"] = ["https://artificialanalysis.ai/models/" + entry["id"]]
        models.append(entry)
    return {
        "schema_version": 1,
        "updated": "REVIEW",
        "aa_intelligence_index_version": payload.get("intelligence_index_version"),
        "source_note": {
            "zh": "草稿：生成后需人工审核全部条目（含别名/点评/as_of）。",
            "en": "Draft: review every entry (aliases, blurbs, as_of) by hand before merging.",
        },
        "models": models,
    }


if __name__ == "__main__":
    print(json.dumps(to_draft(fetch_models()), ensure_ascii=False, indent=2))
