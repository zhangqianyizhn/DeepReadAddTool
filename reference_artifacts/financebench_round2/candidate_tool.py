import re
from typing import Any, Dict, List, Optional, Set, Tuple

_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

_MONTH_PATTERN = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?'
_MONTH_GROUP = r'(?P<month>' + _MONTH_PATTERN + r')'

_DATE_PATTERNS = [
    re.compile(r'(?<![0-9])(?P<year>(?:19|20)[0-9]{2})[-_/](?P<month>0?[1-9]|1[0-2])[-_/](?P<day>0?[1-9]|[12][0-9]|3[01])(?![0-9])', re.I),
    re.compile(_MONTH_GROUP + r'[ ]+(?P<day>[0-9]{1,2})(?:st|nd|rd|th)?,?[ ]+(?P<year>(?:19|20)[0-9]{2})', re.I),
    re.compile(r'(?P<day>[0-9]{1,2})(?:st|nd|rd|th)?[ ]+' + _MONTH_GROUP + r'[ ]+(?P<year>(?:19|20)[0-9]{2})', re.I),
    re.compile(_MONTH_GROUP + r'[ ]+(?P<year>(?:19|20)[0-9]{2})', re.I),
]

_STOP_COMPANY_TOKENS = {
    '10', '8', 'K', 'Q', '10K', '10Q', '8K', '10-K', '10-Q', '8-K',
    'FY', 'Q1', 'Q2', 'Q3', 'Q4', 'ANNUAL', 'REPORT', 'EARNINGS', 'RELEASE',
    'SOURCE', 'DOCUMENT', 'FILE', 'FILING', 'PDF', 'HTML', 'TXT', 'INC',
    'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LLC', 'PLC', 'GROUP',
    'HOLDINGS', 'THE', 'AND', 'OF', 'FOR', 'COM', 'QUARTER', 'QUARTERLY',
    'RESULTS', 'PRESS', 'STATEMENT', 'FORM', 'ITEM', 'PAGE', 'CURRENT',
    'EXHIBIT', 'EXHIBITS', 'SEC', 'COMMISSION', 'UNITED', 'STATES',
    'WASHINGTON', 'DELAWARE', 'JERSEY', 'INCORPORATED', 'DATED', 'FILED',
}

def _month_number(name):
    return _MONTHS.get(name.lower()[:3], 0)

def _fmt_date(t):
    if t[2]:
        return '%04d-%02d-%02d' % (t[0], t[1], t[2])
    return '%04d-%02d' % (t[0], t[1])

def _extract_date_tuples(text):
    dates = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            gd = m.groupdict()
            year = int(gd['year'])
            month_text = gd['month']
            if month_text.isdigit():
                month = int(month_text)
            else:
                month = _month_number(month_text)
            day_text = gd.get('day')
            day = int(day_text) if day_text else 0
            if month and year:
                tup = (year, month, day)
                if tup not in dates:
                    dates.append(tup)
    return sorted(dates)

def _mask_dates(text):
    masked = text
    for pat in _DATE_PATTERNS:
        masked = pat.sub(' ', masked)
    masked = re.sub(r'dated', ' ', masked, flags=re.I)
    return masked

def _looks_generic_doc_id(doc_id):
    s = doc_id.strip().lower()
    if not s:
        return True
    if s.isdigit():
        return True
    if re.fullmatch(r'(?:doc|document|file)[_-]?[0-9]*', s):
        return True
    if re.fullmatch(r'[a-z]{1,4}[_-]?[0-9]{1,4}', s):
        return True
    return False

def _extract_company_tokens(text):
    masked = _mask_dates(text)
    segments = re.split(r'[^A-Za-z0-9]+', masked)
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
        if seg.isdigit() and len(seg) <= 2:
            continue
        if upper in _STOP_COMPANY_TOKENS:
            continue
        tokens.append(seg)
    return tokens

def _extract_periods(text):
    years = set()
    quarters = set()
    for m in re.finditer(r'(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])', text):
        years.add(int(m.group(0)))
    for m in re.finditer(r'(?<![0-9])(?:19|20)([0-9]{2})[Qq]([1-4])(?![0-9])', text):
        years.add(int(m.group(0)[:4]))
        quarters.add(int(m.group(2)))
    for m in re.finditer(r'(?<![A-Za-z0-9])[Qq]([1-4])(?![0-9])', text):
        quarters.add(int(m.group(1)))
    return years, quarters

def _extract_filing_type(text):
    up = text.upper()
    if re.search(r'(?<![A-Za-z0-9])10-?K(?![A-Za-z0-9])', up):
        return '10-K'
    if re.search(r'(?<![A-Za-z0-9])10-?Q(?![A-Za-z0-9])', up):
        return '10-Q'
    if re.search(r'(?<![A-Za-z0-9])8-?K(?![A-Za-z0-9])', up):
        return '8-K'
    if re.search(r'(?<![A-Za-z0-9])EARNINGS(?![A-Za-z0-9])', up):
        return 'earnings'
    if re.search(r'(?<![A-Za-z0-9])ANNUAL[ ]+REPORT(?![A-Za-z0-9])', up):
        return '10-K'
    if re.search(r'(?<![A-Za-z0-9])QUARTERLY[ ]+REPORT(?![A-Za-z0-9])', up):
        return '10-Q'
    return None

def _company_aliases(tokens_norm):
    aliases = set()
    if not tokens_norm:
        return aliases
    aliases.add(''.join(tokens_norm))
    aliases.add(' '.join(tokens_norm))
    initials = ''.join(t[0] for t in tokens_norm if t)
    if len(initials) >= 2:
        aliases.add(initials)
        aliases.add('n'.join(list(initials)))
        aliases.add('and'.join(list(initials)))
        if len(tokens_norm) >= 2:
            aliases.add(tokens_norm[0] + 'n' + tokens_norm[-1])
            aliases.add(tokens_norm[0][0] + 'n' + tokens_norm[-1][0])
    return aliases

def _proper_tokens(question):
    out = set()
    for t in re.findall(r'[A-Za-z0-9]+', question):
        if not t or t.islower() or t.isdigit():
            continue
        if re.fullmatch(r'(?:FY|FISCAL|Q)[0-9]+', t, re.I):
            continue
        out.add(t.lower())
    return out

def _parse_question(question):
    years = set()
    quarters = set()
    for m in re.finditer(r'(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])', question):
        years.add(int(m.group(0)))
    for m in re.finditer(r'(?:FY|FISCAL(?:[ ]+YEAR)?[ ]+)((?:19|20)[0-9]{2})', question, re.I):
        years.add(int(m.group(1)))
    for m in re.finditer(r'(?<![0-9])(?:19|20)([0-9]{2})[Qq]([1-4])(?![0-9])', question):
        years.add(int(m.group(0)[:4]))
        quarters.add(int(m.group(2)))
    for m in re.finditer(r'(?<![A-Za-z0-9])[Qq]([1-4])(?![0-9])', question):
        quarters.add(int(m.group(1)))
    word_quarters = {'first': 1, '1st': 1, 'second': 2, '2nd': 2, 'third': 3, '3rd': 3, 'fourth': 4, '4th': 4}
    for word, qnum in word_quarters.items():
        if re.search(word + r'[ ]+quarter', question, re.I):
            quarters.add(qnum)
    dates = _extract_date_tuples(question)
    filing_type = _extract_filing_type(question)
    normalized_q = re.sub(r'[^a-z0-9]+', '', question.lower())
    q_tokens = set(re.findall(r'[a-z0-9]+', question.lower()))
    proper_tokens = _proper_tokens(question)
    return {'years': years, 'quarters': quarters, 'filing_type': filing_type,
            'dates': dates, 'normalized_q': normalized_q, 'q_tokens': q_tokens,
            'proper_tokens': proper_tokens}

def _parse_doc(doc):
    doc_id = doc.get('doc_id', '')
    source_name = doc.get('source_name', '')
    combined = doc_id + ' ' + source_name
    filing_type = _extract_filing_type(combined)
    years, quarters = _extract_periods(combined)
    dates = _extract_date_tuples(combined)
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
    aliases = _company_aliases(company_tokens_norm)
    return {'doc_id': doc_id, 'source_name': source_name, 'company': company_raw,
            'company_norm': company_norm, 'company_tokens_norm': company_tokens_norm,
            'aliases': aliases, 'filing_type': filing_type, 'years': years,
            'quarters': quarters, 'dates': dates,
            'document_dates': [_fmt_date(d) for d in dates]}

def _date_tuple_match(a, b):
    if a == b:
        return True
    if a[2] == 0 and a[0] == b[0] and a[1] == b[1]:
        return True
    if b[2] == 0 and a[0] == b[0] and a[1] == b[1]:
        return True
    return False

def _match_company(meta, parsed_q):
    company_norm = meta['company_norm']
    aliases = meta['aliases']
    normalized_q = parsed_q['normalized_q']
    q_tokens = parsed_q['q_tokens']
    proper = parsed_q['proper_tokens']
    if not company_norm:
        return 0.0, False
    if len(company_norm) >= 3 and company_norm in normalized_q:
        return 1.0, True
    if company_norm in q_tokens:
        return 1.0, True
    for alias in aliases:
        if len(alias) >= 2 and (alias in normalized_q or alias in proper):
            return 1.0, True
    for tok in proper:
        if len(tok) >= 3:
            if company_norm.startswith(tok) or tok.startswith(company_norm):
                return 1.0, True
    return 0.0, False

def run(question, documents, top_k=5):
    parsed_q = _parse_question(question)
    scored = []
    for doc in documents:
        meta = _parse_doc(doc)
        company_score, company_match = _match_company(meta, parsed_q)

        if parsed_q['years']:
            inter_years = meta['years'] & parsed_q['years']
            if inter_years:
                year_score = 1.0
                year_match = True
            else:
                year_score = 0.0
                year_match = False
        else:
            year_score = 0.5
            year_match = None

        if parsed_q['quarters']:
            inter_q = meta['quarters'] & parsed_q['quarters']
            if inter_q:
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

        date_score = 0.0
        date_match = False
        if parsed_q['dates'] and meta['dates']:
            for qd in parsed_q['dates']:
                for dd in meta['dates']:
                    if _date_tuple_match(qd, dd):
                        date_score = 1.0
                        date_match = True
                        break
                if date_match:
                    break

        score = 3.0 * company_score + 1.5 * year_score + 1.0 * quarter_score + 1.0 * filing_score + 2.0 * date_score

        reasons = []
        if company_match:
            reasons.append('company=' + meta['company'])
        if year_match is True:
            reasons.append('year=' + str(sorted(inter_years)[0]))
        if quarter_match is True:
            reasons.append('quarter=' + str(sorted(inter_q)[0]))
        if filing_match is True:
            reasons.append('filing_type=' + str(meta['filing_type']))
        if date_match:
            reasons.append('date=' + meta['document_dates'][0])
        if not reasons:
            reasons.append('no strong match')

        match_count = sum([
            1 if company_match else 0,
            1 if year_match is True else 0,
            1 if quarter_match is True else 0,
            1 if filing_match is True else 0,
            1 if date_match else 0,
        ])

        scored.append({
            'doc_id': doc.get('doc_id', ''),
            'source_name': doc.get('source_name', ''),
            'company': meta['company'],
            'fiscal_year': sorted(meta['years']),
            'fiscal_quarter': sorted(meta['quarters']),
            'filing_type': meta['filing_type'],
            'document_dates': meta['document_dates'],
            'score': round(score, 4),
            'match_reasons': reasons,
            'company_match': company_match,
            'year_match': year_match,
            'quarter_match': quarter_match,
            'filing_type_match': filing_match,
            'date_match': date_match,
            'match_count': match_count,
        })

    scored.sort(key=lambda item: (-item['score'], -item['match_count'], item['doc_id']))
    results = scored[:max(0, top_k)]

    company_matched = [r for r in scored if r['company_match']]
    year_matched = [r for r in scored if r['year_match'] is True]
    quarter_matched = [r for r in scored if r['quarter_match'] is True]
    filing_matched = [r for r in scored if r['filing_type_match'] is True]
    date_matched = [r for r in scored if r['date_match']]
    strong_candidates = [r for r in scored if r['company_match'] and (r['year_match'] is True or r['filing_type_match'] is True or r['quarter_match'] is True or r['date_match'])]

    if results:
        top = results[0]
        message = 'Top candidate: ' + top['doc_id'] + ' (score ' + str(top['score']) + '). Scope subsequent searches to this doc_id and check other strong candidates for guidance/quarterly questions.'
    else:
        message = 'No documents provided.'

    return {
        'query_parsed': {
            'years': sorted(parsed_q['years']),
            'quarters': sorted(parsed_q['quarters']),
            'filing_type': parsed_q['filing_type'],
            'dates': [_fmt_date(d) for d in parsed_q['dates']],
        },
        'document_count': len(documents),
        'results': results,
        'coverage': {
            'company_matched_count': len(company_matched),
            'year_matched_count': len(year_matched),
            'quarter_matched_count': len(quarter_matched),
            'filing_type_matched_count': len(filing_matched),
            'date_matched_count': len(date_matched),
            'strong_candidate_count': len(strong_candidates),
            'company_matched_doc_ids': [r['doc_id'] for r in company_matched],
            'strong_candidate_doc_ids': [r['doc_id'] for r in strong_candidates],
        },
        'message': message,
    }
