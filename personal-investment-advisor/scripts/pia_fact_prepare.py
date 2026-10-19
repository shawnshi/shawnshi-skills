"""Explicit raw-capture projections: numeric consistency, never publisher authentication."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PureWindowsPath

from artifact_io import atomic_bytes
from source_timing_contract import aware, verify_source_capture

VERSION = 'pia_fact_projection_v1'
TRANSFORM = 'sec_companyfacts_calendar_identity_v1'


class FactError(ValueError):
    pass


def no_links(path):
    path = Path(path).absolute()
    for part in [*reversed(path.parents), path]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise FactError('linked_path_forbidden')
    return path


def bounded_path(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise FactError('relative_posix_path_required')
    path = Path(relative)
    if path.is_absolute() or PureWindowsPath(relative).drive or '..' in path.parts:
        raise FactError('path_escape')
    target = no_links(root / path).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise FactError('path_escape_or_not_file')
    return target


def load(raw):
    from thesis_source_binding import _json
    return _json(raw)


def store(path, raw):
    path = no_links(path)
    if path.exists():
        if path.read_bytes() != raw:
            raise FactError('artifact_conflict:' + path.name)
    else:
        atomic_bytes(path, raw)
    return path


def render(document):
    return json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def exact_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, float)):
        raise FactError('numeric_value_required')
    d = Decimal(str(value))
    if not d.is_finite():
        raise FactError('finite_value_required')
    if d == d.to_integral_value():
        return int(d)
    f = float(d)
    if not Decimal(str(f)) == d:
        raise FactError('standard_json_number_not_lossless')
    return f


def capture(root, receipt):
    path = bounded_path(root, receipt['raw_artifact'])
    verified = verify_source_capture(path, source_locator=receipt['source_locator'],
                                    availability_observed_at=receipt['availability_observed_at'],
                                    retrieved_at=receipt['retrieved_at'], expected_sha256=receipt['content_sha256'])
    for key in ('contract_version', 'verification_method', 'byte_count'):
        if receipt.get(key) != verified[key]:
            raise FactError('capture_receipt_mismatch:' + key)
    if not aware(receipt['retrieved_at']) <= aware(receipt['verified_at']) <= datetime.now(timezone.utc):
        raise FactError('capture_verification_time_invalid')
    return path.read_bytes()


def pointer(document, value):
    if not isinstance(value, str) or not value.startswith('/'):
        raise FactError('json_pointer_required')
    current = document
    try:
        for token in value[1:].split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(current, list):
                if not re.fullmatch(r'0|[1-9][0-9]*', token):
                    raise FactError('invalid_array_pointer')
                current = current[int(token)]
            else:
                current = current[token]
    except (KeyError, IndexError, TypeError) as exc:
        raise FactError('raw_pointer_not_found') from exc
    return current


def period_label(row):
    end = date.fromisoformat(row['end'])
    start = date.fromisoformat(row['start']) if row.get('start') else None
    if start and start > end:
        raise FactError('reversed_period')
    if end.month == 12 and end.day == 31 and (start is None or start == date(end.year, 1, 1)):
        return str(end.year)
    if start and start.year == end.year and start.day == 1 and start.month in (1, 4, 7, 10):
        month = start.month + 2
        if end == date(end.year, month, calendar.monthrange(end.year, month)[1]):
            return f'{end.year}Q{(month - 1) // 3 + 1}'
    return (start.isoformat() + '/' if start else '') + end.isoformat()


def project(spec, root):
    import sec_edgar_fundamentals as sec
    if not isinstance(spec, dict) or spec.get('transform') != TRANSFORM:
        raise FactError('unknown_transform')
    if not isinstance(spec.get('selections'), list) or not all(isinstance(s, dict) for s in spec['selections']):
        raise FactError('explicit_selection_list_required')
    if not isinstance(spec.get('captures'), dict) or set(spec['captures']) != {'ticker_map', 'companyfacts'}:
        raise FactError('explicit_native_captures_required')
    as_of = sec.parse_as_of(spec['as_of'])
    sec._validate_as_of(as_of, datetime.now(timezone.utc))
    receipts = spec['captures']
    documents = {name: load(capture(root, receipts[name])) for name in ('ticker_map', 'companyfacts')}
    if not all(isinstance(d, dict) for d in documents.values()):
        raise FactError('native_json_object_required')
    symbol, cik = spec['symbol'], spec['cik']
    if not isinstance(symbol, str) or not isinstance(cik, str) or not re.fullmatch(r'[0-9]{10}', cik):
        raise FactError('explicit_identity_required')
    def native_cik(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'[0-9]{1,10}', str(value)) or int(value) == 0:
            raise FactError('invalid_native_cik')
        return str(int(value)).zfill(10)
    matches = [native_cik(r['cik_str']) for r in documents['ticker_map'].values()
               if isinstance(r, dict) and r.get('ticker') == symbol]
    if matches != [cik] or native_cik(documents['companyfacts']['cik']) != cik:
        raise FactError('symbol_cik_mismatch_or_ambiguous')
    if receipts['ticker_map'].get('source_provider') != 'SEC EDGAR' or receipts['companyfacts'].get('source_provider') != 'SEC EDGAR':
        raise FactError('provider_mismatch')
    if receipts['ticker_map']['source_locator'] != sec.TICKER_MAP_URL or receipts['companyfacts']['source_locator'] != sec.COMPANYFACTS_URL.format(cik=cik):
        raise FactError('locator_identity_mismatch')
    for receipt in receipts.values():
        retrieved = aware(receipt['retrieved_at'])
        if (retrieved > as_of if isinstance(as_of, datetime) else retrieved.date() > as_of):
            raise FactError('historical_availability_not_proven')
    rows, provenance, pending = [], [], []
    seen = {}
    for selection in spec['selections']:
        metric = selection['metric']
        raw_pointer = selection['raw_pointer']
        match = re.fullmatch(r'/facts/us-gaap/([^/]+)/units/([^/]+)/(0|[1-9][0-9]*)', raw_pointer)
        if not match:
            raise FactError('native_metric_pointer_required')
        tag, unit_token, _ = match.groups()
        unit = unit_token.replace('~1', '/').replace('~0', '~')
        row = pointer(documents['companyfacts'], raw_pointer)
        if not isinstance(row, dict) or 'val' not in row:
            raise FactError('native_fact_required')
        if metric not in sec.TAG_CANDIDATES or tag not in sec.TAG_CANDIDATES[metric]:
            raise FactError('metric_semantics_mismatch')
        if unit not in sec.PREFERRED_UNITS[metric]:
            raise FactError('native_unit_not_supported')
        if row.get('form') not in ('10-K', '10-K/A', '10-Q', '10-Q/A') or any(k in row for k in ('segment', 'dimensions', 'scope')):
            raise FactError('unsupported_form_or_scope')
        if selection.get('scope') != 'consolidated' or selection.get('unit') != unit:
            raise FactError('scope_or_unit_mismatch')
        if bool(row.get('start')) == (metric == 'stockholders_equity'):
            raise FactError('metric_duration_or_instant_mismatch')
        label = period_label(row)
        if selection.get('period') != label:
            raise FactError('period_mapping_mismatch')
        end, filed = date.fromisoformat(row['end']), date.fromisoformat(row['filed'])
        if end > filed or filed > sec._filed_cutoff(as_of) or filed > aware(receipts['companyfacts']['retrieved_at']).date():
            raise FactError('fact_not_available_at_cutoff')
        try:
            value = exact_number(row['val'])
        except FactError as exc:
            pending.append({'raw_pointer': raw_pointer, 'reason': str(exc)})
            continue
        fact = {'symbol': symbol, 'metric': metric, 'value': value, 'unit': unit, 'period': label, 'scope': 'consolidated'}
        key = (symbol, metric, unit, label, 'consolidated')
        if key in seen:
            if seen[key] != value:
                raise FactError('conflicting_facts')
            raise FactError('duplicate_fact_selection')
        seen[key] = value
        rows.append(fact)
        provenance.append({'output_pointer': f'/facts/{len(rows)-1}', 'raw_pointer': raw_pointer,
                           'capture': 'companyfacts', 'filed': row['filed'], 'publication_precision': 'unknown',
                           'published_at': None, 'period_start': row.get('start'), 'period_end': row['end'],
                           'form': row['form'], 'accession': row.get('accn')})
    return {'schema_version': VERSION, 'role': 'derived', 'verification': 'source_bound_numeric_consistency',
            'facts': rows, 'provenance': provenance, 'projection': spec, 'pending': pending,
            'limitations': ['Not publisher authentication; capture timestamps do not prove historical availability.',
                            'Filed is a reported date, not an exact publication timestamp; fiscal periods are not relabeled as calendar periods.']}


def verify_fact_projection(document, evidence_root):
    root = no_links(evidence_root).resolve(strict=True)
    if not isinstance(document, dict) or document.get('schema_version') != VERSION:
        raise FactError('projection_schema_required')
    recomputed = project(document['projection'], root)
    def comparable(value):
        if isinstance(value, bool):
            return ('boolean', value)
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        if isinstance(value, list):
            return [comparable(v) for v in value]
        if isinstance(value, dict):
            return {k: comparable(v) for k, v in value.items()}
        return value
    if comparable(document) != comparable(recomputed):
        raise FactError('projection_mismatch')
    return recomputed


def native_spec(snapshot, ticker_receipt, company_receipt, raw):
    """Produce native selections automatically, without asking users to type known facts."""
    import sec_edgar_fundamentals as sec
    payload = load(raw)
    gaap = payload.get('facts', {}).get('us-gaap', {})
    selections = []
    for metric in sec.TAG_CANDIDATES:
        select = sec._latest_instant_fact if metric == 'stockholders_equity' else sec._latest_annual_fact
        chosen = select(gaap, sec.TAG_CANDIDATES[metric], sec.PREFERRED_UNITS[metric], sec.parse_as_of(snapshot['as_of']))
        if chosen is None:
            continue
        tag, unit = chosen['concept'], chosen['unit']
        for index, row in enumerate(gaap[tag]['units'][unit]):
            if sec._fact_payload(tag, unit, row) == chosen:
                token = unit.replace('~', '~0').replace('/', '~1')
                selections.append({'metric': metric, 'raw_pointer': f'/facts/us-gaap/{tag}/units/{token}/{index}',
                                   'period': period_label(row), 'unit': unit, 'scope': 'consolidated'})
                break
    return {'transform': TRANSFORM, 'symbol': snapshot['symbol'], 'cik': snapshot['cik'],
            'as_of': snapshot['as_of'], 'captures': {'ticker_map': ticker_receipt, 'companyfacts': company_receipt},
            'selections': selections}


def pdf_candidates(root, item) -> dict:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError, PdfStreamError
    raw = capture(root, item['capture'])
    base = {'raw_artifact': item['capture']['raw_artifact'], 'content_sha256': hashlib.sha256(raw).hexdigest(), 'verified': False}
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return dict(base, status='encrypted', candidates=[])
        pages = []
        budget, limit = 0, 100000
        partial = len(reader.pages) > 100
        for index, page in enumerate(reader.pages[:100]):
            text = page.extract_text() or ''
            available = limit - budget
            if len(text) > available:
                partial = True
            text = text[:available]
            budget += len(text)
            resources = page.get('/Resources', {})
            resources = resources.get_object() if hasattr(resources, 'get_object') else resources
            objects = resources.get('/XObject', {})
            objects = objects.get_object() if hasattr(objects, 'get_object') else objects
            has_image = any(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values())
            content = page.get_contents()
            kind = 'text' if text.strip() else 'image_without_text' if has_image else 'blank' if content is None or not content.get_data().strip() else 'unextracted_content'
            pages.append({'page': index + 1, 'span': [0, len(text)], 'text': text,
                          'content_kind': kind, 'role': 'candidate', 'verified': False})
            if budget >= limit:
                partial = True
                break
        if partial:
            status = 'partial'
        elif any(p['text'].strip() for p in pages):
            status = 'candidates'
        elif any(p['content_kind'] == 'image_without_text' for p in pages):
            status = 'scan_ocr_unavailable'
        elif all(p['content_kind'] == 'blank' for p in pages):
            status = 'blank'
        else:
            status = 'text_unavailable_ocr_not_attempted'
        gaps = [{'page': p['page'], 'kind': p['content_kind']} for p in pages
                if p['content_kind'] in ('image_without_text', 'unextracted_content')]
        return dict(base, status=status, candidates=pages, coverage_complete=not partial and not gaps,
                    extraction_gaps=gaps,
                    limitations=['Text extraction is not semantic verification; no OCR capability used.'])
    except (PdfReadError, PdfStreamError, ValueError, TypeError, NotImplementedError) as exc:
        return dict(base, status='unsupported' if isinstance(exc, NotImplementedError) else 'corrupt',
                    candidates=[], error={'type': type(exc).__name__, 'message': str(exc)})


def prepare_facts(input_file, evidence_root, task_dir):
    root = no_links(evidence_root).resolve(strict=True)
    source, task = no_links(input_file).resolve(strict=True), no_links(task_dir).resolve()
    if not root.is_dir():
        raise FactError('explicit_evidence_root_directory_required')
    data = load(source.read_bytes())
    if not isinstance(data, dict) or not isinstance(data.get('projections', []), list) or not isinstance(data.get('pdfs', []), list):
        raise FactError('explicit_input_object_and_lists_required')
    projections, pending, candidates, errors = [], [], [], []
    for index, spec in enumerate(data.get('projections', [])):
        try:
            # Unknown semantic mappings remain candidates, not verified projections.
            known, unknown = [], []
            import sec_edgar_fundamentals as sec
            for selection in spec['selections']:
                if selection['metric'] not in sec.TAG_CANDIDATES:
                    unknown.append(selection)
                else:
                    known.append(selection)
            prepared = project(dict(spec, selections=known), root)
            verify_fact_projection(prepared, root)
            raw = render(prepared)
            digest = hashlib.sha256(raw).hexdigest()
            path = store(task / 'fact_prepare' / (digest + '.json'), raw)
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            errors.append({'projection_index': index, 'category': 'projection_input_or_source_error',
                           'type': type(exc).__name__, 'message': str(exc)})
            continue
        projections.append({'file': str(path), 'content_sha256': digest, 'document': prepared})
        pending.extend({'kind': 'semantic_mapping_confirmation', 'selection': s} for s in unknown)
        pending.extend(prepared['pending'])
    for item in data.get('pdfs', []):
        candidates.append(pdf_candidates(root, item))
    if not projections and not candidates and not pending and not errors:
        raise FactError('explicit_capture_selections_required')
    return {'status': 'incomplete' if errors or pending or candidates or not any(p['document']['facts'] for p in projections) else 'complete',
            'errors': errors,
            'decision_scope': 'research_only', 'projections': projections, 'candidates': candidates,
            'facts_automatic': [f for p in projections for f in p['document']['facts']],
            'rules_need_confirmation': pending, 'publisher_authenticated': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-file', 'evidence-root', 'task-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_facts(args.input_file, args.evidence_root, args.task_dir)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'status': 'failed', 'errors': [type(exc).__name__ + ':' + str(exc)]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
