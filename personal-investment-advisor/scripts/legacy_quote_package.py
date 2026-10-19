"""Offline compatibility bridge for native yf.py --price-only --with-portfolio lists.

Derive quote evidence from timestamped provider info, never history/summary. Keep
history provenance and immutable source bindings; existing auditors remain final.
No networking, input mutation, policy changes or relaxed quote validation.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from portfolio_loader import load_positions, normalize_symbol
from quote_evidence_contract import (
    build_portfolio_snapshot_binding, canonical_json_binding, select_quote_observation,
)
from yf import _expected_position_metadata, build_portfolio_batch_audit


def build_legacy_quote_package(records, portfolio_payload, *, source_binding, now_epoch=None):
    if not isinstance(records, list) or not records:
        raise ValueError('expected a non-empty native legacy records list')
    if portfolio_payload.get('_status') != 'ok':
        raise ValueError('validated positions are required')
    if not isinstance(source_binding, dict) or not source_binding.get('sha256'):
        raise ValueError('original archive binding is required')
    if any(not isinstance(row, dict) for row in records):
        raise ValueError('every source record must be an object')
    old_audit = records[0].get('portfolio_batch_audit')
    if not isinstance(old_audit, dict) or old_audit.get('complete') is not True:
        raise ValueError('complete original native batch audit is required')
    if any(row.get('portfolio_batch_audit') != old_audit for row in records):
        raise ValueError('original per-record batch audits disagree')
    binding = build_portfolio_snapshot_binding(portfolio_payload)
    if old_audit.get('portfolio_snapshot_binding') != binding:
        raise ValueError('original archive is not bound to these positions')
    output_records = []
    for original in records:
        row = copy.deepcopy(original)
        symbol = normalize_symbol(row.get('symbol') or '')
        sources = row.get('data_sources')
        info = row.get('info')
        provenance = row.get('quote_provenance') or {}
        if not isinstance(sources, dict) or not isinstance(info, dict):
            raise ValueError(f'{symbol}: source metadata and provider info are required')
        if (sources.get('price') != 'Yahoo Finance'
                or sources.get('info') != 'Yahoo Finance'
                or sources.get('price_locator') != f'yfinance:{symbol}:history'
                or not isinstance(provenance, dict)
                or provenance.get('tier', 'primary') != 'primary'):
            raise ValueError(f'{symbol}: unsupported source; no fallback/provider relabelling')
        observation = select_quote_observation(info)
        if observation['price'] is None or observation['epoch'] is None:
            raise ValueError(f'{symbol}: timestamped info quote required; no history fallback')
        context = row.get('portfolio_context')
        if not isinstance(context, dict) or context.get('current_price') != observation['price']:
            raise ValueError(f'{symbol}: portfolio price is not the selected info observation')
        # The old locator describes history, whereas portfolio valuation selected
        # an info quote. Split those roles, retaining all original source values.
        row['legacy_history_data_sources'] = copy.deepcopy(sources)
        row['quote_derivation'] = {
            'method': 'timestamped_yfinance_info_observation_v1',
            'archive_binding': copy.deepcopy(source_binding),
            'original_record_binding': canonical_json_binding(original),
            'provider_info_binding': canonical_json_binding(info),
            'selected_observation': observation,
            'history_values_used_for_quote': False,
        }
        row['data_sources'] = {
            **sources, 'price': sources['info'],
            'price_locator': f'yfinance:{symbol}:quote', 'price_adjustment': None,
        }
        del row['portfolio_batch_audit']
        output_records.append(row)
    metadata = _expected_position_metadata(portfolio_payload)
    audit = build_portfolio_batch_audit(
        output_records, requested_count=len(records), expected_symbols=list(metadata),
        portfolio_load_status='ok', portfolio_load_error=None,
        expected_position_metadata=metadata, now_epoch=now_epoch,
        portfolio_snapshot_binding=binding,
    )
    return {
        'status': 'complete' if audit['complete'] else 'incomplete',
        'operation_mode': 'read_only_offline', 'evidence_scope': 'quote_only',
        'records': output_records, 'portfolio_batch_audit': audit,
        'legacy_capture': {
            'archive_binding': copy.deepcopy(source_binding),
            'original_batch_audit': copy.deepcopy(old_audit),
            'original_history_research_status': 'not_promoted',
            'network_requests': 0,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quotes-file', required=True, help='Original native legacy JSON list.')
    parser.add_argument('--positions-file', required=True, help='The same bound positions snapshot.')
    parser.add_argument('--output', required=True, help='New quote-only package; never overwritten.')
    args = parser.parse_args(argv)
    source = Path(args.quotes_file).resolve()
    positions = Path(args.positions_file).resolve()
    output = Path(args.output).resolve()
    if output in {source, positions} or output.exists():
        parser.error('output must be a new path distinct from both inputs')
    try:
        raw = source.read_bytes()
        records = json.loads(raw.decode('utf-8-sig'))
        portfolio = load_positions(str(positions))
        package = build_legacy_quote_package(
            records, portfolio,
            source_binding={'path': str(source), 'sha256': hashlib.sha256(raw).hexdigest()},
        )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f'legacy quote input rejected: {exc}\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': package['status'], 'output': str(output),
                      'evidence_scope': 'quote_only', 'network_requests': 0}))
    return 0 if package['portfolio_batch_audit']['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
