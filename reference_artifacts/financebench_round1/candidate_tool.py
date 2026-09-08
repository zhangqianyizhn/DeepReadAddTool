import re
from typing import Any, Dict, List, Optional, Set, Tuple

_STOP_COMPANY_TOKENS = {
    '10', '8', 'K', 'Q', '10K', '10Q', '8K', '10-K', '10-Q', '8-K',
    'FY', 'Q1', 'Q2', 'Q3', 'Q4', 'ANNUAL', 'REPORT', 'EARNINGS', 'RELEASE',
    'SOURCE', 'DOCUMENT', 'FILE', 'FILING', 'PDF', 'HTML', 'TXT', 'INC',
    'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LLC', 'PLC', 'GROUP',
    'HOLDINGS', 'THE', 'AND', 'OF', 'FOR', 'COM', 'QUARTER', 'QUARTERLY',
    'RESULTS', 'PRESS', 'STATEMENT'
}

def _looks_generic_doc_id(doc_id: str) -> bool:
    s = doc_id.strip().lower()
    if not s:
        return True
    if s.isdigit():
        return True
    if re.fullmatch(r'(?:doc|document|file)[_-]?[0-9]*', s):
        return True
    return False

def _extract_company_tokens(text: str) -> List[str]:
    segments = re.split(r'[^A-Za-z0-9]+', text)
    tokens = []
    for seg in segments:
        if not seg:
            continue
        upper = seg.upper()
        if re.fullmatch(r'(19|20)[0-9]{2}', upper):
            continue
        if re.fullmatch(r'(19|20)[0-9]{2}[Qq][1-4]', upper):
            continue
        if re.fullmatch(r'FY(19|20)[0-9]{2}', upper):
            continue
        if re.fullmatch(r'[Qq][1-4]', upper):
            continue
        if re.fullmatch(r'(?:10|8)-?[KQ]', upper):
            continue
        if upper in _STOP_COMPANY_TOKENS:
            continue
        tokens.append(seg)
    return tokens

def _extract_periods(text: str) -> Tuple[Set[int], Set[int]]:
    years = set()
    quarters = set()
    for m in re.finditer(r'(?<![0-9])(19|20)[0-9]{2}(?![0-9])', text):
        years.add(int(m.group(0)))
    for m in re.finditer(r'(?<![0-9])(19|20)[0-9]{2}[Qq]([1-4])(?![0-9])', text):
        years.add(int(m.group(1)))
        quarters.add(int(m.group(2)))
    for m in re.finditer(r'(?<![A-Za-z0-9])[Qq]([1-4])(?![0-9])', text):
        quarters.add(int(m.group(1)))
    return years, quarters

def _extract_filing_type(text: str) -> Optional[str]:
    up = text.upper()
    if re.search(r'(?<![A-Za-z0-9])10-?K(?![A-Za-z0-9])', up):
        return '10-K'
    if re.search(r'(?<![A-Za-z0-9])10-?Q(?![A-Za-z0-9])', up):
        return '10-Q'
    if re.search(r'(?<![A-Za-z0-9])8-?K(?![A-Za-z0-9])', up):
        return '8-K'
    if re.search(r'EARNINGS[ ]+RELEASE', up):
        return 'earnings'
    if re.search(r'ANNUAL[ ]+REPORT', up):
        return '10-K'
    if re.search(r'QUARTERLY[ ]+REPORT', up):
        return '10-Q'
    return None

def _parse_doc(doc: Dict[str, str]) -> Dict[str, Any]:
    doc_id = doc.get('doc_id', '')
    source_name = doc.get('source_name', '')
    combined = doc_id + ' ' + source_name
    filing_type = _extract_filing_type(combined)
    years, quarters = _extract_periods(combined)

    doc_tokens = _extract_company_tokens(doc_id)
    src_tokens = _extract_company_tokens(source_name)
    if doc_tokens and not _looks_generic_doc_id(doc_id):
        company_tokens = doc_tokens
    elif src_tokens:
        company_tokens = src_tokens
    else:
        company_tokens = doc_tokens or src_tokens

    seen = set()
    uniq = []
    for token in company_tokens:
        key = token.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(token)
    company_tokens = uniq

    company_raw = ' '.join(company_tokens) if company_tokens else doc_id
    company_norm = re.sub(r'[^a-z0-9]+', '', company_raw.lower())
    company_tokens_norm = [re.sub(r'[^a-z0-9]+', '', token.lower()) for token in company_tokens]

    return {
        'doc_id': doc_id,
        'source_name': source_name,
        'company': company_raw,
        'company_norm': company_norm,
        'company_tokens_norm': company_tokens_norm,
        'filing_type': filing_type,
        'years': years,
        'quarters': quarters,
    }

def _parse_question(question: str) -> Dict[str, Any]:
    years = set()
    quarters = set()

    for m in re.finditer(r'(?<![0-9])(19|20)[0-9]{2}(?![0-9])', question):
        years.add(int(m.group(0)))
    for m in re.finditer(r'(?:FY|FISCAL(?:[ ]+YEAR)?[ ]+)(19|20)[0-9]{2}', question, re.IGNORECASE):
        years.add(int(m.group(1)))
    for m in re.finditer(r'(?<![0-9])(19|20)[0-9]{2}[Qq]([1-4])(?![0-9])', question):
        years.add(int(m.group(1)))
        quarters.add(int(m.group(2)))
    for m in re.finditer(r'(?<![A-Za-z0-9])[Qq]([1-4])(?![0-9])', question):
        quarters.add(int(m.group(1)))

    word_quarters = {
        'first': 1, '1st': 1,
        'second': 2, '2nd': 2,
        'third': 3, '3rd': 3,
        'fourth': 4, '4th': 4,
    }
    for word, quarter_num in word_quarters.items():
        if re.search(word + r'[ ]+quarter', question, re.IGNORECASE):
            quarters.add(quarter_num)

    up = question.upper()
    filing_type = None
    if re.search(r'(?<![A-Za-z0-9])10-?K(?![A-Za-z0-9])', up) or re.search(r'ANNUAL[ ]+REPORT', up):
        filing_type = '10-K'
    elif re.search(r'(?<![A-Za-z0-9])10-?Q(?![A-Za-z0-9])', up) or re.search(r'QUARTERLY[ ]+REPORT', up) or re.search(r'QUARTER[ ]+ENDED', up):
        filing_type = '10-Q'
    elif re.search(r'(?<![A-Za-z0-9])8-?K(?![A-Za-z0-9])', up):
        filing_type = '8-K'
    elif re.search(r'EARNINGS[ ]+RELEASE', up):
        filing_type = 'earnings'

    return {'years': years, 'quarters': quarters, 'filing_type': filing_type}

def run(question: str, documents: List[Dict[str, str]], top_k: int = 5) -> Dict[str, Any]:
    parsed_q = _parse_question(question)
    normalized_q = re.sub(r'[^a-z0-9]+', '', question.lower())
    q_tokens = set(re.findall(r'[a-z0-9]+', question.lower()))

    scored = []
    for doc in documents:
        meta = _parse_doc(doc)
        company_norm = meta['company_norm']
        company_tokens_norm = meta['company_tokens_norm']

        company_score = 0.0
        company_match = False
        if company_norm:
            if len(company_norm) >= 3 and company_norm in normalized_q:
                company_score = 1.0
                company_match = True
            elif company_norm in q_tokens:
                company_score = 1.0
                company_match = True
        if not company_match and company_tokens_norm:
            if all(token in q_tokens for token in company_tokens_norm):
                company_score = 1.0
                company_match = True

        if parsed_q['years']:
            if meta['years'] & parsed_q['years']:
                year_score = 1.0
                year_match = True
            else:
                year_score = 0.0
                year_match = False
        else:
            year_score = 0.5
            year_match = None

        if parsed_q['quarters']:
            if meta['quarters'] & parsed_q['quarters']:
                quarter_score = 1.0
                quarter_match = True
            else:
                quarter_score = 0.0
                quarter_match = False
        else:
            quarter_score = 0.5
            quarter_match = None

        if parsed_q['filing_type']:
            if meta['filing_type'] == parsed_q['filing_type']:
                filing_score = 1.0
                filing_match = True
            else:
                filing_score = 0.0
                filing_match = False
        else:
            filing_score = 0.5
            filing_match = None

        score = 3.0 * company_score + 1.5 * year_score + 1.0 * quarter_score + 1.0 * filing_score

        reasons = []
        if company_match:
            reasons.append('company=' + meta['company'])
        if year_match is True:
            reasons.append('year=' + str(sorted(meta['years'] & parsed_q['years'])[0]))
        if quarter_match is True:
            reasons.append('quarter=' + str(sorted(meta['quarters'] & parsed_q['quarters'])[0]))
        if filing_match is True:
            reasons.append('filing_type=' + str(meta['filing_type']))
        if not reasons:
            reasons.append('no strong match')

        scored.append({
            'doc_id': doc.get('doc_id', ''),
            'source_name': doc.get('source_name', ''),
            'company': meta['company'],
            'fiscal_year': sorted(meta['years']),
            'fiscal_quarter': sorted(meta['quarters']),
            'filing_type': meta['filing_type'],
            'score': round(score, 4),
            'match_reasons': reasons,
            'company_match': company_match,
            'year_match': year_match,
            'quarter_match': quarter_match,
            'filing_type_match': filing_match,
        })

    scored.sort(key=lambda item: (-item['score'], item['doc_id']))
    results = scored[:max(0, top_k)]

    company_matched = [r for r in scored if r['company_match']]
    year_matched = [r for r in scored if r['year_match'] is True]
    strong_candidates = [r for r in scored if r['company_match'] and (r['year_match'] is True or r['filing_type_match'] is True)]

    if results:
        top = results[0]
        message = 'Top candidate: ' + top['doc_id'] + ' (score ' + str(top['score']) + '). Use this doc_id as the scope for subsequent searches.'
    else:
        message = 'No documents provided.'

    return {
        'query_parsed': {
            'years': sorted(parsed_q['years']),
            'quarters': sorted(parsed_q['quarters']),
            'filing_type': parsed_q['filing_type'],
        },
        'document_count': len(documents),
        'results': results,
        'coverage': {
            'company_matched_count': len(company_matched),
            'year_matched_count': len(year_matched),
            'strong_candidate_count': len(strong_candidates),
            'company_matched_doc_ids': [r['doc_id'] for r in company_matched],
        },
        'message': message,
    }
