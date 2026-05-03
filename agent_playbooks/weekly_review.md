# Claude Code 每周复盘流程

目标：复盘核心指数的 qlib 数据、策略表现和信号变化，形成中文周报。

## 核心标的

```text
CN_000510   中证A500指数
CN_000300   沪深300指数
HK_HSTECH   恒生科技指数
US_NDX      纳斯达克100指数
US_GSPC     标普500指数
```

## 默认步骤

1. 检查数据一致性。

```bash
python main.py qlib-consistency \
  --json-output reports/weekly_qlib_consistency.json
```

2. 检查核心标的数据健康。

```bash
python main.py qlib-health \
  --universe CN_000510 CN_000300 HK_HSTECH US_NDX US_GSPC \
  --start 2024-01-01 \
  --end 2026-05-01 \
  --json-output reports/weekly_qlib_health.json
```

3. 对关注标的运行策略搜索。

```bash
python main.py strategy-search \
  --symbol 000510 \
  --market CN \
  --asset-type INDEX \
  --start 2024-01-01 \
  --end 2026-05-01 \
  --objective composite \
  --output reports/csi_a500_weekly_strategy_search.md \
  --json-output reports/csi_a500_weekly_strategy_search.json
```

4. 总结：

- 本周哪些标的数据有异常。
- 哪些策略最近表现变好或变差。
- 是否有明显信号切换。
- 下周需要重点观察的推翻条件。

## 安全边界

周报只做研究复盘，不做自动交易安排。
