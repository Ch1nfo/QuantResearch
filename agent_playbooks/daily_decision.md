# Claude Code 日常决策流程

目标：生成单标的中文研究决策报告，不自动交易，不调用券商接口。

## 默认步骤

1. 先检查 qlib 数据一致性。

```bash
python main.py qlib-consistency \
  --json-output reports/qlib_consistency.json
```

2. 生成当天策略信号快照。

```bash
python main.py signal-snapshot \
  --symbol 000510 \
  --market CN \
  --asset-type INDEX \
  --as-of 2026-04-30 \
  --strategies kdj bollinger ma_cross macd rsi \
  --output reports/signals/csi_a500_20260430.md \
  --json-output reports/signals/csi_a500_20260430.json
```

3. 生成中文决策报告。

```bash
python main.py decision-report \
  --symbol 000510 \
  --market CN \
  --asset-type INDEX \
  --as-of 2026-04-30 \
  --strategies kdj bollinger ma_cross macd rsi dca \
  --output reports/decisions/csi_a500_20260430.md \
  --json-output reports/decisions/csi_a500_20260430.json
```

4. 读取 JSON 和 Markdown，用中文解释：

- 今天的结论是买入/增持、卖出/减仓、观望/持有，还是暂不决策。
- 哪些策略支持这个结论。
- 数据健康是否通过。
- 最近真实成交是什么。
- 建议目标仓位是多少。
- 什么条件会推翻当前结论。

## 安全边界

- 不连接券商。
- 不自动下单。
- 不把报告说成确定收益。
- 如果数据健康失败，必须先解释为什么暂不决策。
