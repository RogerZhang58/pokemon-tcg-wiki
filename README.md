# Pokemon TCG Wiki Hermes

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

宝可梦集换式卡牌游戏（Pokémon TCG）全知识库助手 — [Hermes Agent](https://hermes-agent.nousresearch.com) 平台 Skill。

基于 **TCGdex**（结构化卡牌元数据）+ **PTCG Live zh-mod**（简中翻译），通过 4 阶段 Pipeline + `validation.py` 硬校验回答宝可梦卡牌相关问题。

## 功能

| 功能 | 说明 |
|------|------|
| 🔍 卡牌查询 | 简中/日文/英文名称检索，按属性/类型/系列/赛制过滤 |
| 📖 规则检索 | 官方规则全文搜索，特殊状态裁定，伤害/弱点/抗性计算 |
| 🚫 赛制查询 | Standard / Expanded 合法性，禁限牌列表 |
| 🧬 进化链 | 基础→一阶→二阶进化关系查询 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 同步数据源（首次运行需联网）
python tools/sync_data.py

# 3. 合并简中翻译
python tools/build_cards.py

# 4. 构建搜索索引
python tools/build_indices.py

# 5. 测试
python tools/pipeline.py "皮卡丘VMAX 的弱点是什么"
```

## 使用示例

```bash
# 卡牌查询
python tools/card_search.py "皮卡丘VMAX"
python tools/card_search.py "Pikachu VMAX" --json

# 规则检索
python tools/rule_search.py "特殊状态 中毒"
python tools/rule_search.py --lang en "weakness calculation"

# 赛制查询
python tools/format_check.py --card "皮卡丘VMAX"
python tools/format_check.py --list standard --banned

# 名称翻译
python tools/name_translator.py "皮卡丘"

# 完整 Pipeline
python tools/pipeline.py "standard 赛制禁了哪些训练家卡"
python tools/pipeline.py --interactive
```

## Pipeline 架构

```
用户问题（简中）
├─[Fast Path]──► 简单查卡/查禁限 → 直接回答 + 校验
▼
Stage 1: DECOMPOSE — 意图识别 + 实体抽取 → query_plan.json
Stage 2: LOOKUP    — 并行查询（card + rule + format）
Stage 3: ANALYZE   — 合并结果，数值计算 → analysis.json
Stage 4: VERDICT   — 最终回答 + [校验: PASS | N/N]
```

## 项目结构

```
pokemon-tcg-wiki/
├── skill/
│   └── pokemon-tcg.md              # Hermes Skill 定义
├── tools/
│   ├── pipeline.py                 # 4 阶段 Pipeline orchestrator
│   ├── card_search.py              # 卡牌查询（FTS5 + 过滤）
│   ├── rule_search.py              # 规则检索（FTS5 + 高亮）
│   ├── format_check.py             # 赛制/禁限牌查询
│   ├── name_translator.py          # 中英日三语名称翻译
│   ├── validation.py               # Schema 硬校验
│   ├── utils.py                    # 公共工具（路径/DB/语言检测）
│   ├── sync_data.py                # [维护] 数据源同步
│   ├── build_cards.py              # [维护] 卡牌合并
│   └── build_indices.py            # [维护] 索引构建
├── wiki/                           # 知识库
├── raw/
│   ├── data/cards/                 # TCGdex 英文元数据
│   ├── data/cards_zh/              # 合并后的简中卡牌
│   ├── zh_mod/                     # PTCG Live 简中翻译（只读）
│   ├── llm_trans/                  # LLM 翻译产物（隔离）
│   ├── rules/                      # 规则文档
│   └── banned/                     # 禁限牌表
├── tests/
├── LICENSE (MIT)
└── README.md
```

## 数据源

| 来源 | 提供 | 覆盖 | License |
|------|------|------|---------|
| [TCGdex](https://github.com/tcgdex/cards-database) | 卡牌元数据（HP/属性/弱点/抗性/赛制） | 全卡池 | MIT |
| [PTCG Live zh-mod](https://github.com/Hill-98/ptcg-live-zh-mod) | 简中译名（卡名/招式） | 卡名全覆盖 | 开源 |
| 官方规则 PDF | 规则书/赛事手册/Errata | 简中官方 PDF (已收录) | © Pokémon |

## 限制

- 简中赛制/轮替使用国际版数据（TCGdex `legal` 字段），非简中特有规则
- 招式名/文本部分已由社区翻译，未覆盖部分暂用英文
- 环境分析（meta）、收藏向功能不在 MVP 范围

## 致谢

本项目基于以下开源项目构建，特此致谢：

- **[TCGdex](https://github.com/tcgdex/cards-database)** — Pokémon TCG 卡牌数据库，提供结构化卡牌元数据（HP/属性/弱点/抗性/赛制）。MIT License。
- **[PTCG Live zh-mod](https://github.com/Hill-98/ptcg-live-zh-mod)** — PTCG Live 中文化模组，提供卡牌简中译名及游戏文本翻译。[Paratranz 项目 #9617](https://paratranz.cn/projects/9617) 社区翻译。
- **[Kuuusoda/magic-skill](https://github.com/Kuuusoda/magic-skill)** — 万智牌知识库工具链的开创性工作，mtg-wiki-hermes 的源头项目。本项目 Pipeline 架构思想经 mtg-wiki-hermes 传递至此。

感谢以上项目的作者和贡献者。本项目的简中翻译数据来源于 PTCG Live zh-mod 社区翻译成果，未做修改。

## License

MIT — Copyright (c) 2026 RogerZhang

本项目独立于 mtg-wiki-hermes，仅参考架构思想，不共用代码。

Pokémon 是 Nintendo / Creatures / GAME FREAK 的商标。本项目为非官方社区项目，与任天堂、宝可梦公司无关联。卡牌图片和数据的版权归其各自所有者。
