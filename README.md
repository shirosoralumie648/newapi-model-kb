# newapi-model-kb

模型知识库：为 new-api / newapi-rev 的**模型广场**提供「帮用户选模型」的策展数据——别名映射、质量/速度/价格档位、擅长标签、一句话点评。

## 这是什么

网关站上的模型动辄上百个，用户不知道该选哪个。本仓库人工维护一份模型知识数据，站点侧每日拉取一次，在模型广场卡片上展示徽标（质量档/速度档/擅长标签）与详情（适用场景、数据日期）。

- **数据来源**：质量分、速度、任务成本参考 [Artificial Analysis](https://artificialanalysis.ai)（AA Intelligence Index v4.3.2，2026-10 快照），经人工整理；价格档位仅作参考，**具体价格一律以站点自身定价为准**。
- **定位**：只做展示参考，**不参与计费、不影响路由**。
- **分发**：GitHub raw / jsDelivr，站点侧无需注册任何外部 API key。

```
https://raw.githubusercontent.com/shirosoralumie648/newapi-model-kb/main/models.json
https://cdn.jsdelivr.net/gh/shirosoralumie648/newapi-model-kb@main/models.json
```

## 档位定义（按当前市场相对水平，非绝对分）

| 维度 | 取值 | 划线（2026-10） |
| --- | --- | --- |
| 质量档 | S / A / B / C | AA 智力指数 ≥50 = S；40–49 = A；30–39 = B；<30 = C |
| 速度档 | fast / normal / slow | 中位输出 ≥200 tok/s = fast；60–199 = normal；<60 = slow |
| 价格档 | budget / mid / premium | AA 每任务成本 ≤$0.5 = budget；$0.5–2 = mid；>$2 = premium |

推理档位变体（max / xhigh / high / medium / low）记录在 `quality.variants`，同一模型不同档位分差可能很大（如 Opus 5.5：max 58 → low 42）。

## 数据结构

见 `schema.json`（JSON Schema 2020-12）。关键字段：

- `id`：规范 slug（kebab-case）
- `aliases`：站点上可能出现的各种模型名（点号/横杠变体、带 effort 后缀、带厂前缀），网关用它把自家模型名对上知识条目
- `quality` / `speed` / `price`：档位 + 原始参考值 + `as_of` 数据日期
- `strengths`：语言中立枚举标签（`coding` `agent` `chinese` `cheap`…），多语言文案由前端 i18n 负责
- `blurb`：一句话点评，`zh`/`en` 双语，其余语言回退 `en`
- `open_weights`：是否开源权重

## 六维能力评分（radar）

`capabilities` 存 AA 的六个**职业能力指数**（免费档即可拉取）：财务会计 / 战略运营 / 法律 / 医疗健康 / 工程 / 经济。

- 取值为 AA 原始值（当前量级约 0~65，随版本演进，**前端不要写死上限**）
- AA 约定：模型缺任一依赖评估时该维为 `null`（未测 ≠ 零分）；医疗健康维覆盖模型较少属正常
- 前端雷达图建议按数据集内各维最大值**相对归一化**；任一维缺失的模型不画雷达，显示「数据不全」
- 这六个指数与智力指数**分开版本化**，各条目用 `capabilities.as_of` 记录快照月份
- 同批新增：`quality.aa_coding_index` / `aa_agentic_index`（编码分、Agent 分，**仅 AA Data API 提供，公开页面无此字段，当前未填**）、`speed.median_ttft_seconds`（首 chunk 延迟，推理模型含思考时间，与 AA 榜单口径一致）、`price` 的缓存命中/写入与每百万 token 参考价

## 维护流程

1. **半自动草稿**：`scripts/fetch-aa-draft.py` 用你自己的 AA API key（免费档 100 次/天足够）拉取最新榜单，生成候选条目草稿。
2. **能力数据**：`scripts/fetch-aa-capabilities.py` 无需 key，从 AA 公开页面抓取六维能力、TTFT 与每百万 token 价格，输出 `/tmp/aa-capabilities-draft.json`（只补不覆盖已有字段）。
3. **人工审核**：核对模型名、别名映射、档位、点评措辞；**点评必须人工改写**，不直接照搬机器文案。
4. **提交**：更新顶层 `updated` 与各条目 `as_of`，PR 合并后即全网生效。

## 归属与合规

- 本仓库数据整理自 Artificial Analysis 公开数据，使用时必须保留出处标注（AA 要求 attribution，前端展示一条来源链接即可）。
- 本仓库与 Artificial Analysis 无从属关系；如其条款变化导致不能再镜像分数，将降级为「链接引用 + 自整理档位」。
- 本仓库整理后的数据（档位、别名、点评、结构）以 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 发布。
