import re
import math
from collections import Counter, defaultdict

_STOPWORDS = set('''a about after all also am an and any are as at be because been before being both but by can could did do does doing during each for from had has have he her hers him his how i if in into is it its just like may me more most much my no not of on or other our out over she should so some such than that the their them then there these they this those through to too under up very was we were what when where which while who will with would you your i m s t ll ve re d'''.split())

_MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}

_GENERIC = set('''about also always another back been being came come could day days did didnt different do does doing even every feel feels felt from getting go going good got great guys help helped helping here hey high home how im into just know like liked likes looking lot love loved make makes making mean might much need new nice now okay people really right said say says see seem seems seen should something sometimes still stuff take taken taking thing things think thinks thought through today took tried try trying us used use using want wanted wants way went were whats where which who why will would yeah yes yet youre'''.split())

_RELATIVE_PHRASES = ('last sunday','last monday','last tuesday','last wednesday','last thursday','last friday','last saturday','last weekend','last week','last month','last year','this weekend','this week','next weekend','next week','yesterday','today','tomorrow')

_LIFE_STRONG = {'child','children','kid','kids','childhood'}
_LIFE_WEAK = {'young','younger','teen','teens','teenage','boy'}
_COLLAB_CUES = {'both','all','together','shared','same','also'}
_NAMED_SPEAKER_BONUS = 3.0

def _norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text).lower()).strip()

def _tokens(text):
    return re.findall(r'[a-z0-9]+', str(text).lower())

def _stem_token(token):
    t = str(token).lower()
    if len(t) <= 3:
        return t
    if t.endswith('ing') and len(t) > 5:
        base = t[:-3]
        if base.endswith('e') and len(base) > 3 and base[-2] not in 'aeiou':
            base = base[:-1]
        if len(base) > 1 and base[-1] == base[-2] and base[-1] in 'bcdfgkmnprst':
            base = base[:-1]
        return base
    if t.endswith('ed') and len(t) > 4:
        base = t[:-2]
        if base.endswith('e') and len(base) > 3:
            base = base[:-1]
        if len(base) > 1 and base[-1] == base[-2] and base[-1] in 'bcdfgkmnprst':
            base = base[:-1]
        return base
    return t

def _quoted_phrases(question):
    dq = chr(34)
    sq = chr(39)
    return re.findall(dq + '([^' + dq + ']+)' + dq, question) + re.findall(sq + '([^' + sq + ']+)' + sq, question)

def _speakers(corpus):
    out = set()
    for doc in corpus or []:
        for page in doc.get('pages') or []:
            sp = str(page.get('speaker') or '').strip()
            if sp:
                out.add(sp)
    return out

def _matching_speakers(question, corpus):
    qt = set(_tokens(question))
    out = set()
    for sp in _speakers(corpus):
        st = set(_tokens(sp))
        if st and st.issubset(qt):
            out.add(sp)
    return out

def _session_index(question):
    toks = _tokens(question)
    for i, t in enumerate(toks):
        if t == 'session':
            if i + 1 < len(toks) and toks[i + 1] == '#':
                if i + 2 < len(toks) and toks[i + 2].isdigit():
                    return int(toks[i + 2])
            elif i + 1 < len(toks) and toks[i + 1].isdigit():
                return int(toks[i + 1])
    return None

def _date_literal(question):
    m = re.search(r'([12][0-9]{3})[-/]([0-9]{1,2})[-/]([0-9]{1,2})', question)
    if m:
        y = int(m.group(1)); mo = int(m.group(2)); d = int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return '%04d-%02d-%02d' % (y, mo, d)
    toks = _tokens(question)
    for i, t in enumerate(toks):
        if t in _MONTHS:
            mo = _MONTHS[t]
            if i + 2 < len(toks) and toks[i + 1].isdigit() and len(toks[i + 2]) == 4:
                d = int(toks[i + 1]); y = int(toks[i + 2])
                if 1 <= d <= 31 and 1900 <= y <= 2100:
                    return '%04d-%02d-%02d' % (y, mo, d)
            if i > 0 and i + 1 < len(toks) and toks[i - 1].isdigit() and len(toks[i + 1]) == 4:
                d = int(toks[i - 1]); y = int(toks[i + 1])
                if 1 <= d <= 31 and 1900 <= y <= 2100:
                    return '%04d-%02d-%02d' % (y, mo, d)
            if i + 1 < len(toks) and len(toks[i + 1]) == 4:
                y = int(toks[i + 1])
                if 1900 <= y <= 2100:
                    return '%04d-%02d' % (y, mo)
    for t in toks:
        if len(t) == 4 and t.isdigit():
            return t
    return None

def _digits(s):
    return ''.join(ch for ch in str(s) if ch.isdigit())

def _date_match(u, literal):
    dt = str(u.get('date_time') or '')
    if literal in dt:
        return True
    ndt = _digits(dt)
    nlit = _digits(literal)
    return bool(nlit and ndt and nlit in ndt)

def _build_utterances(corpus):
    out = []
    for doc in corpus or []:
        doc_id = str(doc.get('doc_id') or '')
        source_name = str(doc.get('source_name') or '')
        title = str(doc.get('title') or '')
        for page in doc.get('pages') or []:
            text = str(page.get('text') or '')
            if not text.strip():
                continue
            unit_index = page.get('unit_index', page.get('page_number'))
            page_number = page.get('page_number', unit_index)
            session_index = page.get('session_index')
            try:
                session_index = int(session_index)
            except Exception:
                session_index = None
            speaker = str(page.get('speaker') or '')
            dia_id = str(page.get('dia_id') or '')
            section_name = str(page.get('section_name') or '')
            date_time = str(page.get('date_time') or '')
            out.append({
                'doc_id': doc_id, 'source_name': source_name, 'title': title,
                'unit_index': unit_index, 'page_number': page_number,
                'session_index': session_index, 'speaker': speaker,
                'dia_id': dia_id, 'section_name': section_name,
                'date_time': date_time, 'text': text
            })
    return out

def _filter_utterances(utts, speakers, session_index, date_literal):
    had_filters = bool(speakers) or session_index is not None or bool(date_literal)
    strict = []
    for u in utts:
        if speakers and u['speaker'] not in speakers:
            continue
        if session_index is not None and u['session_index'] != session_index:
            continue
        if date_literal and not _date_match(u, date_literal):
            continue
        strict.append(u)
    if strict:
        return strict, False
    out = utts
    if speakers:
        f = [u for u in out if u['speaker'] in speakers]
        if f:
            out = f
    if session_index is not None:
        f = [u for u in out if u['session_index'] == session_index]
        if f:
            out = f
    if date_literal:
        f = [u for u in out if _date_match(u, date_literal)]
        if f:
            out = f
    return out, had_filters

def _idf_map(utts):
    n = max(1, len(utts))
    df = Counter()
    for u in utts:
        toks = set(_tokens(u.get('text', '')))
        all_toks = set(toks)
        for t in toks:
            all_toks.add(_stem_token(t))
        for t in all_toks:
            df[t] += 1
    return {t: 1.0 + math.log((n + 1.0) / (cnt + 1.0)) for t, cnt in df.items()}

def _detect_life_stage(question):
    qs = set(_tokens(question))
    if qs & _LIFE_STRONG:
        return 'child'
    return None

def _life_stage_score(text, mode):
    if mode is None:
        return 0.0
    ts = set(_tokens(text))
    if ts & _LIFE_STRONG:
        return 1.5
    if ts & _LIFE_WEAK:
        return -2.0
    return 0.0

def _base_score(u, content_tokens, idf, quoted_phrases, question_norm, life_stage):
    score = 0.0
    reasons = []
    raw_toks = _tokens(u.get('text', '') + ' ' + u.get('section_name', ''))
    hay = set(raw_toks)
    stem_hay = set(_stem_token(t) for t in hay)
    speaker_toks = set(_tokens(u.get('speaker', '')))
    speaker_hits = []
    hits = []
    for t in content_tokens:
        if t in speaker_toks:
            speaker_hits.append(t)
        if t in hay or _stem_token(t) in stem_hay:
            hits.append(t)
    if speaker_hits:
        score += _NAMED_SPEAKER_BONUS
        reasons.append('speaker match: ' + ', '.join(sorted(set(speaker_hits))[:3]))
    if hits:
        for t in set(hits):
            w = idf.get(t, 0.0)
            st = _stem_token(t)
            if st in idf and idf[st] > w:
                w = idf[st]
            score += w
        reasons.append('query terms: ' + ', '.join(sorted(set(hits))[:6]))
    text_norm = _norm(u.get('text', ''))
    for phrase in quoted_phrases:
        np = _norm(phrase)
        if np and np in text_norm:
            score += 20.0
            reasons.append('quoted phrase matched')
    if question_norm and question_norm in text_norm:
        score += 10.0
        reasons.append('whole-question phrase matched')
    toks = _tokens(u.get('text', ''))
    if hits and len(toks) <= 5:
        score += 1.5
    ls = _life_stage_score(u.get('text', ''), life_stage)
    if ls:
        score += ls
        reasons.append('life-stage qualifier scored')
    return score, reasons

def _expand_query(utts, idf, content_tokens, seeds, max_terms=12):
    originals = set(content_tokens)
    counts = Counter()
    for u in seeds:
        for t in set(_tokens(u.get('text', ''))):
            if t in originals or t in _STOPWORDS or len(t) < 4:
                continue
            counts[t] += 1
    scored = []
    for t, c in counts.items():
        if c < 2 or t in _GENERIC:
            continue
        scored.append((math.log(1.0 + c) * idf.get(t, 1.0), c, t))
    scored.sort(reverse=True)
    out = []
    seen = set()
    for weight, c, t in scored:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_terms:
            break
    return out

def _sortable_key(u):
    val = u.get('unit_index')
    if val is None:
        val = u.get('page_number')
    try:
        return (0, int(val))
    except Exception:
        return (1, str(val))

def _build_session_groups(utts):
    groups = defaultdict(list)
    for u in utts:
        if u.get('session_index') is None:
            continue
        groups[(u['doc_id'], u['session_index'])].append(u)
    for lst in groups.values():
        lst.sort(key=_sortable_key)
    return groups

def _context_score(u, groups, terms, idf):
    session_index = u.get('session_index')
    if session_index is None:
        return 0.0, '', 0
    lst = groups.get((u['doc_id'], session_index))
    if not lst:
        return 0.0, '', 0
    idx = None
    for j, n in enumerate(lst):
        if n is u:
            idx = j
            break
    if idx is None:
        return 0.0, '', 0
    neighbors = lst[max(0, idx - 3):idx] + lst[idx + 1:idx + 4]
    score = 0.0
    parts = []
    for n in neighbors:
        nt = set(_tokens(n.get('text', '')))
        snt = set(_stem_token(t) for t in nt)
        hits = []
        for t in terms:
            if t in nt or _stem_token(t) in snt:
                hits.append(t)
        if not hits:
            continue
        for t in hits:
            w = idf.get(t, 0.5)
            st = _stem_token(t)
            if st in idf and idf[st] > w:
                w = idf[st]
            score += w
        snippet = str(n.get('speaker') or '') + ': ' + n.get('text', '')
        parts.append(snippet[:240])
    ctx_text = ' | '.join(parts)[:1000]
    return score, ctx_text, len(parts)

def _relative_phrases(text):
    tn = ' ' + _norm(text) + ' '
    out = []
    for phrase in _RELATIVE_PHRASES:
        if (' ' + phrase + ' ') in tn:
            out.append(phrase)
    return out[:3]

def _name_collisions(utts):
    by_speaker = defaultdict(set)
    for u in utts:
        if u.get('speaker'):
            by_speaker[u['speaker']].add((str(u.get('doc_id') or ''), str(u.get('source_name') or '')))
    out = {}
    for sp, docs in by_speaker.items():
        if len(docs) > 1:
            out[sp] = [{'doc_id': d, 'source_name': s} for d, s in sorted(docs)]
    return out

def _identity_key(res):
    return (str(res.get('doc_id') or ''), str(res.get('unit_index') or ''), str(res.get('speaker') or ''), str(res.get('date_time') or ''), res.get('text', '')[:80])

def _select_results(ranked, top_k, speakers, collab_cue=False, question_norm=''):
    if not ranked:
        return []
    selected = []
    seen = set()

    def add(score, res):
        k = _identity_key(res)
        if k in seen:
            return False
        selected.append((score, res, len(selected)))
        seen.add(k)
        return True

    if len(speakers) >= 2 and collab_cue:
        ordered = sorted(speakers, key=lambda sp: -question_norm.rfind(sp.lower()))
        progressed = True
        while len(selected) < top_k and progressed:
            progressed = False
            for sp in ordered:
                if len(selected) >= top_k:
                    break
                for score, res in ranked:
                    if res.get('speaker') == sp and add(score, res):
                        progressed = True
                        break
        for score, res in ranked:
            if len(selected) >= top_k:
                break
            add(score, res)
        return selected[:top_k]

    if len(speakers) >= 2:
        speaker_list = sorted(speakers)
        base = top_k // len(speaker_list)
        rem = top_k % len(speaker_list)
        quotas = {sp: base + (1 if i < rem else 0) for i, sp in enumerate(speaker_list)}
        for sp in speaker_list:
            count = 0
            for score, res in ranked:
                if len(selected) >= top_k:
                    break
                if res.get('speaker') == sp and count < quotas[sp] and add(score, res):
                    count += 1
        for score, res in ranked:
            if len(selected) >= top_k:
                break
            add(score, res)
    else:
        session_counts = Counter()
        session_limit = max(3, top_k)
        for score, res in ranked:
            if len(selected) >= top_k:
                break
            k = _identity_key(res)
            if k in seen:
                continue
            skey = (res.get('doc_id'), res.get('session_index'))
            if session_counts[skey] >= session_limit:
                continue
            add(score, res)
            session_counts[skey] += 1
    return selected[:top_k]

def run(question, corpus, top_k=5):
    try:
        top_k = max(1, min(int(top_k), 25))
    except Exception:
        top_k = 5
    question = str(question or '')
    all_utts = _build_utterances(corpus)
    metadata = {'query': question, 'utterance_count': len(all_utts), 'searched': 'utterance_text plus same-session context'}
    if not all_utts:
        metadata['filtered_count'] = 0
        metadata['results_count'] = 0
        return {'results': [], 'metadata': metadata}
    idf = _idf_map(all_utts)
    content_tokens = [t for t in _tokens(question) if t not in _STOPWORDS and len(t) > 1]
    speakers = _matching_speakers(question, corpus)
    session_index = _session_index(question)
    date_literal = _date_literal(question)
    search_utts, relaxed = _filter_utterances(all_utts, speakers, session_index, date_literal)
    quoted_phrases = _quoted_phrases(question)
    question_norm = _norm(question)
    life_stage = _detect_life_stage(question)
    collab_cue = bool(set(_tokens(question)) & _COLLAB_CUES)
    scored = []
    for u in search_utts:
        s, reasons = _base_score(u, content_tokens, idf, quoted_phrases, question_norm, life_stage)
        scored.append((s, u, reasons))
    scored.sort(key=lambda item: (-item[0], _sortable_key(item[1])))
    positive = [item for item in scored if item[0] > 0]
    seeds = [u for s, u, r in positive[:max(5, min(15, top_k * 2))]]
    expansion = _expand_query(all_utts, idf, content_tokens, seeds) if len(seeds) >= 2 else []
    groups = _build_session_groups(search_utts)
    terms = content_tokens + expansion
    ranked = []
    for s, u, reasons in scored:
        hay = set(_tokens(u.get('text', '') + ' ' + u.get('section_name', '')))
        stem_hay = set(_stem_token(t) for t in hay)
        total = s
        exp_hits = []
        for t in expansion:
            if t in hay or _stem_token(t) in stem_hay:
                exp_hits.append(t)
        if exp_hits:
            total += sum(idf.get(t, 0.5) * 0.6 for t in exp_hits)
        ctx_score, ctx_text, ctx_n = _context_score(u, groups, terms, idf)
        if ctx_score > 0:
            total += ctx_score * 0.4
        unit_index = u.get('unit_index')
        node_id = u.get('dia_id') or str(unit_index if unit_index is not None else u.get('page_number'))
        extra_reasons = []
        if exp_hits:
            extra_reasons.append('expanded co-occurring terms: ' + ', '.join(exp_hits[:4]))
        if ctx_score > 0:
            extra_reasons.append('same-session context adds evidence')
        res = {
            'doc_id': u['doc_id'],
            'node_id': node_id,
            'unit_index': unit_index,
            'page_number': u.get('page_number'),
            'title': u.get('title', ''),
            'score': round(total, 4),
            'text': u.get('text', '')[:800],
            'context_text': ctx_text,
            'neighbor_count': ctx_n,
            'source_name': u.get('source_name', ''),
            'speaker': u.get('speaker', ''),
            'session_index': u.get('session_index'),
            'date_time': u.get('date_time', ''),
            'section_name': u.get('section_name', ''),
            'is_summary': 'summary' in (u.get('section_name', '') or '').lower(),
            'relative_phrases': _relative_phrases(u.get('text', '')),
            'reasons': (reasons[:4] + extra_reasons)[:6]
        }
        ranked.append((total, res))
    ranked.sort(key=lambda item: (-item[0], _sortable_key(item[1])))
    selected = _select_results(ranked, top_k, speakers, collab_cue, question_norm)
    selected.sort(key=lambda item: (-item[0], item[2]))
    results = [r for s, r, i in selected[:top_k]]
    metadata['filtered_count'] = len(search_utts)
    metadata['speakers_filter'] = sorted(speakers)
    metadata['session_index_filter'] = session_index
    metadata['date_filter'] = date_literal
    metadata['collaborative_cue'] = collab_cue
    metadata['expansion_terms'] = expansion
    metadata['relaxed_filters'] = relaxed
    metadata['name_collisions'] = _name_collisions(all_utts)
    metadata['results_count'] = len(results)
    return {'results': results, 'metadata': metadata}
