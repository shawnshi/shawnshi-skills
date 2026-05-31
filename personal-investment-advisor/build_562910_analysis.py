import json

with open('562910_raw.json', 'r', encoding='utf-8') as f:
    raw_data = json.load(f)[0]

top_positions = raw_data.get('portfolio_summary', {}).get('top_positions_by_weight', [])
if not top_positions:
    top_positions = [
      {'symbol': '588000.SS', 'name': '科创50ETF华夏', 'weight': 0.2437},
      {'symbol': '513390.SS', 'name': '纳指100ETF博时', 'weight': 0.165},
      {'symbol': 'INTC', 'name': '英特尔', 'weight': 0.1474},
      {'symbol': '513500.SS', 'name': '标普500ETF博时', 'weight': 0.1445},
      {'symbol': '562910.SS', 'name': '高端制造ETF', 'weight': 0.1103}
    ]

analysis = {
  'stock_name': '高端制造ETF',
  'stock_code': '562910',
  'market_type': 'ETF',
  'research_mode': 'trading_mode',
  'sentiment_score': 45,
  'trend_prediction': '看多',
  'operation_advice': '持有',
  'decision_type': 'hold',
  'confidence_level': '中',
  'confidence_details': {
    'score': 65,
    'data_quality': '高',
    'technical_alignment': '中',
    'valuation_support': '高',
    'actionability': '中'
  },
  'freshness_flags': {
    'price_data_fresh': True,
    'info_data_fresh': True,
    'news_data_fresh': True,
    'portfolio_data_fresh': True,
    'stale_inputs': []
  },
  'evidence_items': [
    {
      'fact': 'RSI降至30.57，处于超卖区间',
      'connection': '技术性超卖',
      'deduction': '短期有反弹需求',
      'source_type': 'price',
      'freshness': 'T0',
      'confidence': '高'
    },
    {
      'fact': '当前价格0.97低于成本价0.985，浮亏约1.52%',
      'connection': '浮亏状态',
      'deduction': '在超卖区域不宜割肉',
      'source_type': 'portfolio',
      'freshness': 'T0',
      'confidence': '高'
    }
  ],
  'dashboard': {
    'core_conclusion': {
      'one_sentence': '技术面超卖，价格低于均线但偏离率不高，持筹者可等待反弹。',
      'signal_type': '看多',
      'time_sensitivity': '低',
      'position_advice': {
        'has_position': True,
        'advice': '浮亏较小且进入超卖区，建议持仓等待反弹。'
      }
    },
    'qualitative_analysis': {
      'bull_case': '高端制造板块估值处于历史低位，政策底线支撑强。',
      'bear_case': '短期均线空头排列，市场情绪低迷，未见明显反转信号。',
      'catalysts': ['宏观数据回暖', '稳增长政策落地']
    },
    'data_perspective': {
      'trend_status': {'status': '震荡下行'},
      'price_position': {
        'current_price': 0.97,
        'support_level': 0.95,
        'resistance_level': 0.99,
        'position': '低位'
      },
      'volume_analysis': {'status': '缩量'},
      'chip_structure': {'chip_health': '不适用(非A股)'},
      'valuation': {'status': '偏低'}
    },
    'intelligence': {
      'news_sentiment': '中性',
      'institutional_moves': '中性',
      'macro_impact': '偏多'
    },
    'battle_plan': {
      'sniper_points': {
        'support_1': 0.95,
        'support_2': 0.92,
        'resistance_1': 0.99,
        'stop_loss': 0.90,
        'take_profit': 1.05
      },
      'position_strategy': {'suggested_position': '持有待涨'},
      'action_checklist': ['观察是否跌破0.95支撑', '观察反弹量能']
    }
  },
  'analysis_summary': '高端制造ETF短期经历调整后RSI进入超卖区间，目前浮亏1.5%左右。均线呈空头排列但存在乖离，短期反弹概率较大，建议继续持有观察。',
  'risk_warning': '若宏观情绪持续悲观，可能向下测试0.95支撑。',
  'short_term_outlook': '震荡',
  'medium_term_outlook': '看多',
  'search_performed': False,
  'data_sources': {
    'price': 'Yahoo',
    'info': 'Yahoo',
    'news': 'Yahoo',
    'portfolio': 'Local'
  },
  'data_gaps': ['筹码增强字段不适用(非A股)'],
  'portfolio_context': raw_data.get('portfolio_context', {
    'has_position': True,
    'quantity': 10000.0,
    'avg_cost': 0.985,
    'current_price': 0.97,
    'market_value': 9700.0,
    'cost_basis': 9850.0,
    'unrealized_pnl': -150.0,
    'unrealized_pnl_pct': -0.0152,
    'position_status': 'matched'
  }),
  'position_advice': {
    'holding_view': '轻微浮亏',
    'action_for_holder': '持有',
    'cost_basis_view': '成本偏高但可控',
    'risk_to_holder': '持续阴跌风险',
    'next_action_trigger': ['反弹至MA10(0.99)遇阻减仓', '跌破0.95严格止损']
  },
  'portfolio_summary': {
    'total_positions': 12,
    'tracked_weight': 1.0001,
    'market_exposure': {'美股': 0.1526, 'A股': 0.1103, 'A股ETF': 0.6025, 'CASH': 0.1347},
    'top_positions_by_weight': top_positions,
    'concentration_score': 0.1532,
    'concentration_bucket': 'medium'
  },
  'portfolio_risk': {
    'concentration_risk': '高',
    'market_exposure_risk': '中',
    'style_drift_risk': '低',
    'liquidity_risk': '中'
  },
  'portfolio_fit': {
    'action_in_portfolio': 'hold',
    'allocation_impact': 'none',
    'rationale': '作为底仓继续持有'
  }
}

with open('562910_analysis.json', 'w', encoding='utf-8') as f:
    json.dump(analysis, f, ensure_ascii=False, indent=2)
print("Analysis JSON written to 562910_analysis.json")
