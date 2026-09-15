import re
import json
from typing import List, Dict, Any, Optional, Tuple

def run(question: str, corpus: list, top_k: int = 5) -> dict:
    if top_k is None or top_k < 1:
        top_k = 1
    units = _collect_units(corpus)
    table_units = [u for u in units if _is_table_like(u)]
    if not table_units:
        return {'results': [], 'query': question, 'top_k': top_k, 'note': 'No table-like content found in corpus.'}
    refs = _extract_table_refs(question)
    scored = []
    for u in table_units:
        s = _score_unit(u, question, refs)
        if s > 0:
            scored.append((s, u))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for s, u in scored[:top_k]:
        text = _format_table_text(u)
        data = _get_table_data(u)
        reasons = _build_reasons(u, question, refs, data)
        result = {
            'doc_id': u.get('doc_id'),
            'source_name': u.get('source_name'),
            'node_id': u.get('node_id'),
            'unit_index': u.get('unit_index'),
            'page_number': u.get('page_number'),
            'title': u.get('section_name') or u.get('title') or u.get('node_id'),
            'score': round(s, 4),
            'text': text[:2000],
            'reasons': reasons
        }
        results.append(result)
    if not results:
        return {'results': [], 'query': question, 'top_k': top_k, 'note': 'No table content matched the question.'}
    return {'results': results, 'query': question, 'top_k': top_k}

def _collect_units(corpus: list) -> list:
    units = []
    for doc in corpus:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get('doc_id') or doc.get('id')
        source = doc.get('source_name') or doc.get('source')
        sections = doc.get('sections') or []
        section_node = {}
        for sec in sections:
            if isinstance(sec, dict):
                title = sec.get('title') or sec.get('section_name')
                node_id = sec.get('node_id')
                if title and node_id:
                    section_node[str(title).strip().lower()] = node_id
        pages = doc.get('pages') or doc.get('text_units') or doc.get('units') or []
        if isinstance(pages, dict):
            pages = [pages]
        if not pages and isinstance(doc.get('text'), str):
            pages = [doc]
        for page in pages:
            if not isinstance(page, dict):
                continue
            unit = dict(page)
            if 'doc_id' not in unit:
                unit['doc_id'] = doc_id
            if 'source_name' not in unit:
                unit['source_name'] = source
            sec_name = unit.get('section_name') or unit.get('title') or unit.get('section')
            if sec_name and str(sec_name).strip().lower() in section_node:
                unit.setdefault('node_id', section_node[str(sec_name).strip().lower()])
            units.append(unit)
    return units

def _is_table_like(unit: dict) -> bool:
    if str(unit.get('type') or '').lower() in ('table', 'figure'):
        return True
    if str(unit.get('kind') or '').lower() in ('table', 'figure'):
        return True
    if _get_table_data(unit):
        return True
    text = unit.get('text') or ''
    section = unit.get('section_name') or unit.get('title') or ''
    node = unit.get('node_id') or ''
    combined = ' '.join([str(section), str(node), str(text)]).lower()
    if re.search(r'\btable\b|\btabref\b|\bfigure\b|\bfig\.?\b', combined):
        return True
    if re.search(r'\.(png|jpe?g|gif|pdf)\b|image', combined):
        return True
    return False

def _get_table_data(unit: dict):
    for key in ('table', 'rows', 'data', 'cells', 'content'):
        val = unit.get(key)
        if isinstance(val, list) and val and all(isinstance(r, list) for r in val):
            return val
        if isinstance(val, dict):
            for subkey in ('rows', 'data', 'cells'):
                sub = val.get(subkey)
                if isinstance(sub, list) and sub and all(isinstance(r, list) for r in sub):
                    return sub
    text = unit.get('text') or ''
    return _extract_table_rows(text)

def _extract_table_rows(text: str):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and all(isinstance(r, list) for r in data):
            return data
    except Exception:
        pass
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    if all('|' in ln for ln in lines):
        rows = []
        for ln in lines:
            cells = [c.strip() for c in ln.strip('|').split('|')]
            rows.append(cells)
        return rows
    if all('\t' in ln for ln in lines):
        return [[c.strip() for c in ln.split('\t')] for ln in lines]
    if all(',' in ln for ln in lines):
        split = [ln.split(',') for ln in lines]
        if len(set(len(r) for r in split)) == 1:
            if any(_looks_numeric(c) for r in split for c in r):
                return [[c.strip() for c in r] for r in split]
    if all(re.search(r'\s{2,}', ln) for ln in lines):
        rows = [re.split(r'\s{2,}', ln) for ln in lines]
        if len(set(len(r) for r in rows)) == 1:
            return rows
    return None

def _looks_numeric(s: str) -> bool:
    s = str(s).strip().replace(',', '').replace('%', '')
    try:
        float(s)
        return True
    except Exception:
        return False

def _extract_table_refs(text: str) -> set:
    refs = set()
    patterns = [
        (r'\btable\s*\.?\s*(\d+)', 'table'),
        (r'\btabref\s*\.?\s*(\d+)', 'tabref'),
        (r'\bfig(?:ure)?\s*\.?\s*(\d+)', 'figure')
    ]
    for pat, prefix in patterns:
        for m in re.finditer(pat, str(text), re.I):
            refs.add(prefix + m.group(1))
    return refs

def _unit_has_ref(unit: dict, refs: set) -> bool:
    if not refs:
        return False
    hay = ' '.join([
        str(unit.get('section_name') or ''),
        str(unit.get('node_id') or ''),
        str(unit.get('title') or ''),
        str(unit.get('caption') or ''),
        str(unit.get('text') or '')
    ]).lower()
    hay = re.sub(r'[\s\.\-_]+', '', hay)
    for ref in refs:
        if ref in hay:
            return True
    return False

def _tokenize(text: str) -> set:
    return set(re.findall(r'[a-z0-9]+', str(text).lower()))

def _score_unit(unit: dict, question: str, refs: set) -> float:
    score = 0.0
    text = unit.get('text') or ''
    section = unit.get('section_name') or unit.get('title') or ''
    node = unit.get('node_id') or ''
    caption = unit.get('caption') or ''
    haystack = ' '.join([str(section), str(node), str(caption), str(text)])
    q_tokens = _tokenize(question)
    h_tokens = _tokenize(haystack)
    if q_tokens:
        overlap = len(q_tokens & h_tokens)
        score += overlap * 2.0
    if _unit_has_ref(unit, refs):
        score += 20.0
    if _get_table_data(unit):
        score += 10.0
    q_lower = str(question).lower()
    if re.search(r'\d', q_lower) or any(w in q_lower for w in ['how many', 'list', 'accuracy', 'loss', 'score', 'bleu', 'values', 'results', 'performance']):
        if _get_table_data(unit):
            score += 5.0
    sec_tokens = _tokenize(section)
    if q_tokens and sec_tokens:
        score += len(q_tokens & sec_tokens) * 1.5
    return score

def _format_table_text(unit: dict) -> str:
    text = unit.get('text') or ''
    data = _get_table_data(unit)
    if data:
        body = '\n'.join('\t'.join(str(c) for c in row) for row in data)
        caption = unit.get('caption') or unit.get('title') or ''
        if caption:
            return str(caption) + '\n' + body
        return body
    return text

def _build_reasons(unit: dict, question: str, refs: set, data) -> list:
    reasons = []
    if _unit_has_ref(unit, refs):
        reasons.append('matches table reference in question')
    text = unit.get('text') or ''
    section = unit.get('section_name') or unit.get('title') or ''
    node = unit.get('node_id') or ''
    caption = unit.get('caption') or ''
    haystack = ' '.join([str(section), str(node), str(caption), str(text)])
    q_tokens = _tokenize(question)
    h_tokens = _tokenize(haystack)
    overlap = len(q_tokens & h_tokens)
    if overlap:
        reasons.append(f'keyword overlap: {overlap} terms')
    if data:
        reasons.append('structured table rows detected')
    else:
        if re.search(r'\.(png|jpe?g|gif|pdf)\b|image', text.lower()):
            reasons.append('image-only table/figure; no structured rows in corpus')
    return reasons
