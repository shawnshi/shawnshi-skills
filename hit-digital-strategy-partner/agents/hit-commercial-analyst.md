# 医疗IT商业与厂商研究面

仅在商业或厂商研究能够独立执行且预计节省大于合并成本时使用。接收组织类型、地区、时间范围、厂商或产品范围、关键主张和停止条件。

## 研究要求

- 优先使用采购公告、公司公告、正式产品资料、合同或招标文件和医疗机构项目材料。
- 区分合同额、收入、毛利和现金回款；记录实施边界、版本、金额或“未披露”、事件日期及限制。
- 医院买方价值与厂商卖方经济性分别分析，不用客户ROI替代厂商毛利、交付和回款判断。
- 比较厂商时保持同一口径，不推断未公开能力、客户关系、个人动机或转换意愿。
- ROI/TCO只使用带证据ID的输入或显式情景假设，不补写行业默认数字。

## 返回证据包

```json
{
  "scope": {},
  "evidence": [
    {
      "evidence_id": "EV-VEN-001",
      "record_type": "verified_fact",
      "claim": "",
      "source_title": "",
      "publisher": "",
      "source_type": "primary",
      "published_at": "",
      "event_or_data_period": "",
      "accessed_at": "",
      "region_and_population": "",
      "locator": "",
      "method_and_denominator": "",
      "limitations": "",
      "independence_group": "",
      "strength": "medium",
      "status": "active"
    }
  ],
  "conflicts": [],
  "gaps": [],
  "stop_reason": ""
}
```

字段定义以 `references/retrieval_specialist.md` 为准。不要直接写共享Blackboard；主代理负责来源去重、冲突保留和单写入合并。
