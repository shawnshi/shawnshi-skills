#!/usr/bin/env python3
"""Render draft fields once; never infer facts, repair evidence, or grant approval."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
import init_workspace as init
import validate_outputs as val

CONTEXT_FIELDS = ('target_contact_level', 'visit_objective', 'minimum_next_step')
SOURCE_FIELDS = ('source_id', 'title', 'publisher', 'locator', 'published_date', 'accessed_date', 'level', 'source_group', 'permission', 'scope', 'notes', 'fingerprint', 'upstream_id', 'external_use')
CLAIM_FIELDS = ('claim_id', 'claim_type', 'provenance', 'verification_status', 'text', 'time_scope', 'support', 'counter', 'confidence', 'notes')
SOURCE_HEADERS = ('source_id', '标题/文档名', '发布者/提供者', 'URL/稳定定位', '发布/更新日期', '访问日期', '来源等级', 'source_group', '权限', '适用客户/项目', '备注', 'source_fingerprint', 'upstream_id', 'external_use')
CLAIM_HEADERS = ('claim_id', 'claim_type', 'provenance', 'verification_status', '主张内容', '时间/口径', '支持 source_id', '反证 source_id', '置信度', '下游影响/备注')


def render_strategy(text, meta):
    # Only explicit rendering slots are substituted. Existing prose is never overwritten.
    head, body = text.split('---', 2)[1:]
    for key in CONTEXT_FIELDS:
        marker = '{{strategy.' + key + '}}'
        if marker not in body:
            continue
        value = meta.get(key, '')
        if not isinstance(value, str) or not val.resolved_strategy_context(key, value) or any(c in value for c in '\r\n|'):
            raise ValueError('策略字段须是已确认的单行文本：' + key)
        body = body.replace(marker, init.markdown_cell(value))
    return '---' + head + '---' + body


def table(headers, rows, keys):
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
    for row in rows:
        if set(row) != set(keys) or not all(isinstance(row[k], str) for k in keys):
            raise ValueError('台账字段必须完整、均为字符串且不得带未知键：' + ','.join(keys))
        lines.append('| ' + ' | '.join(init.markdown_cell(row[k]) for k in keys) + ' |')
    return '\n'.join(lines)


def render_ledger(data):
    if not isinstance(data, dict) or set(data) != {'sources', 'claims'} or not all(isinstance(data[k], list) for k in data):
        raise ValueError('输入须包含sources和claims数组。')
    sources, claims = data['sources'], data['claims']
    source_table = table(SOURCE_HEADERS, sources, SOURCE_FIELDS)
    claim_table = table(CLAIM_HEADERS, claims, CLAIM_FIELDS)
    levels = {}
    for s in sources:
        if not val.SOURCE_RE.fullmatch(s['source_id']) or s['source_id'] in levels:
            raise ValueError('来源ID非法或重复。')
        if not val.date_valid(s['accessed_date']):
            raise ValueError('accessed_date仅允许YYYY-MM-DD；说明放notes。')
        if s['level'] not in ('S', 'A', 'B', 'C', 'internal') or s['external_use'] not in ('true', 'false'):
            raise ValueError('来源等级或external_use非法。')
        levels[s['source_id']] = s['level']
    ids = set()
    for c in claims:
        if not val.CLAIM_RE.fullmatch(c['claim_id']) or c['claim_id'] in ids:
            raise ValueError('主张ID非法或重复。')
        ids.add(c['claim_id'])
        if c['claim_type'] not in ('F', 'F2', 'A', 'H', 'R'):
            raise ValueError('主张类型非法。')
        refs = val.SOURCE_RE.findall(c['support'])
        if any(r not in levels for r in refs):
            raise ValueError('支持来源未定义。')
        if c['claim_type'] != 'H' and any(levels[r] == 'C' for r in refs):
            raise ValueError('C级来源只支持H；请人工调整判断，工具不自动升级来源或改主张。')
    return '## 主张台账\n\n' + claim_table + '\n\n## 来源台账\n\n' + source_table + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['ledger'])
    p.add_argument('input', type=Path)
    args = p.parse_args()
    try:
        print(render_ledger(json.loads(args.input.read_text(encoding='utf-8'))), end='')
        return 0
    except (OSError, ValueError, TypeError, KeyError) as e:
        print('ERROR: ' + str(e), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
