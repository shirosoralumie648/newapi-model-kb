# newapi-model-kb

模型知识库：为 new-api / newapi-rev 的**模型广场**提供「帮用户选模型」的策展数据——别名映射、质量/速度/价格档位、擅长标签、一句话点评。

## 这是什么

网关站上的模型动辄上百个，用户不知道该选哪个。本仓库维护一份模型知识数据，站点侧每日拉取一次，在模型广场卡片上展示徽标（质量档/速度档/擅长标签）与详情（适用场景、数据日期）。

当前覆盖 **AA 全量 706 个模型条目**（含 effort 变体，每个变体单独成条）。

- **数据来源**：质量分、六维能力、编码/Agent 分、速度、任务成本、上下文窗口与模态均来自 [Artificial Analysis](https://artificialanalysis.ai)（AA Intelligence Index v4.3，2026-10 快照）；价格档位仅作参考，**具体价格一律以站点自身定价为准**。
- **blurb 为自动生成，标注「待人工润色」**，后续由维护者逐条改写。
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

推理档位变体（max / xhigh / high / medium / low）**单独成条**（如 `claude-opus-5-5`、`claude-opus-5-5-low`），同一模型不同档位分差可能很大（如 Opus 5.5：max 57.6 → low 42.3）。同一 release 的各变体通过 `aliases` 中的基础 slug 互相可达。

## 数据结构

见 `schema.json`（JSON Schema 2020-12）。关键字段：

- `id`：规范 slug（kebab-case）
- `aliases`：站点上可能出现的各种模型名（点号/横杠变体、带 effort 后缀、带厂前缀），网关用它把自家模型名对上知识条目
- `quality` / `speed` / `price`：档位 + 原始参考值 + `as_of` 数据日期
- `strengths`：语言中立枚举标签（`coding` `agent` `chinese` `cheap`…），多语言文案由前端 i18n 负责
- `blurb`：一句话点评，`zh`/`en` 双语，其余语言回退 `en`
- `open_weights`：是否开源权重

## 六维能力评分（radar）

`capabilities` 存 AA 的六个**职业能力指数**：财务会计 / 战略运营 / 法律 / 医疗健康 / 工程 / 经济。

- 取值为 AA 原始值（当前量级约 0~65，随版本演进，**前端不要写死上限**）
- AA 约定：模型缺任一依赖评估时该维为 `null`（未测 ≠ 零分）；医疗健康维覆盖模型较少属正常
- 前端雷达图建议按数据集内各维最大值**相对归一化**；任一维缺失的模型不画雷达，显示「数据不全」
- 这六个指数与智力指数**分开版本化**，各条目用 `capabilities.as_of` 记录快照月份
- `quality.aa_coding_index` / `aa_agentic_index`：编码分、Agent 分，来自 AA Data API（258 / 167 个条目有值）
- `speed.median_ttft_seconds`：首 chunk 延迟，推理模型含思考时间，与 AA 榜单口径一致
- `price` 的缓存命中/写入与每百万 token 参考价

## 维护流程

1. **全量构建**：`AA_API_KEY=... python3 scripts/build-aa-kb.py` —— 从 AA Data API 拉全量条目，并从公开详情页补齐上下文窗口/模态/开源权重/许可证，重建 `models.json`（当前 706 条）。
2. **人工润色**：`blurb` 目前是自动生成的占位文案（末尾带「自动生成，待人工润色」），逐条改写后去掉该标注即可。
3. **提交**：更新顶层 `updated` 与各条目 `as_of`，PR 合并后即全网生效。

> 旧版辅助脚本：`scripts/fetch-aa-draft.py`（带 key 的草稿）、`scripts/fetch-aa-capabilities.py`（无 key 抓公开页）、`scripts/merge-aa-capabilities.py`（只补不覆盖合并）。全量重建用 `build-aa-kb.py` 即可。

## 归属与合规

- 本仓库数据整理自 Artificial Analysis 公开数据，使用时必须保留出处标注（AA 要求 attribution，前端展示一条来源链接即可）。
- 本仓库与 Artificial Analysis 无从属关系；如其条款变化导致不能再镜像分数，将降级为「链接引用 + 自整理档位」。
- 本仓库整理后的数据（档位、别名、点评、结构）以 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 发布。
