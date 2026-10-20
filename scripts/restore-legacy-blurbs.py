#!/usr/bin/env python3
"""把旧版人工撰写的 blurb / strengths 恢复到当前 models.json（LLM 润色后执行）。

用法:
    python3 scripts/restore-legacy-blurbs.py <旧版备份.json>

旧版 52 条是人工写的，比自动生成质量高；新旧 id 不一致时按别名映射。
只恢复 blurb 和 strengths，不碰分数、价格等其他字段。
"""

import json
import sys

NEW = "models.json"


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: restore-legacy-blurbs.py <旧版备份.json>")
    old = json.load(open(sys.argv[1], encoding="utf-8"))
    new = json.load(open(NEW, encoding="utf-8"))

    alias = {}
    for m in new["models"]:
        for a in m["aliases"]:
            alias.setdefault(a, m["id"])
    new_by_id = {m["id"]: m for m in new["models"]}

    restored = 0
    for om in old["models"]:
        target_id = om["id"] if om["id"] in new_by_id else next(
            (alias[a] for a in om["aliases"] if a in alias), None)
        if not target_id:
            print(f"  [skip] {om['id']} 无对应", file=sys.stderr)
            continue
        target = new_by_id[target_id]
        target["blurb"] = om["blurb"]
        if om.get("strengths"):
            target["strengths"] = om["strengths"]
        restored += 1

    with open(NEW, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已恢复 {restored} 条人工 blurb/strengths", file=sys.stderr)


if __name__ == "__main__":
    main()

