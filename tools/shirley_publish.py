#!/usr/bin/env python3
"""Shirley public data builder + safety check.

Usage:
  python3 tools/shirley_publish.py build RAW_DIR OUT_JSON [--voice-read yes|no] [--note TEXT ...]
      RAW_DIR holds jobs.json, activity.json, properties.json, team.json (the private Shirley datasets).
      Writes OUT_JSON (the public data file) and OUT_JSON.report.json (what was changed / warned / blocked).
      Exit code 0 = passed the 4 hard blocks, 3 = BLOCKED (do not push), 2 = structure problem (do not push).
  python3 tools/shirley_publish.py check OUT_JSON      (re-run the check on a finished file)

Policy (set by Luis, Nov 9 2026): lenient.
  HARD BLOCKS (never pushed): money, phone numbers, email addresses / links, access codes.
  WARNINGS (pushed, listed in the morning summary): family-name + arrival, unknown names, stale / shrunk data,
  dropped fields, scrubbed text.
"""
import json, re, sys, os, datetime

ALLOWED = {
    'jobs': ['date', 'end', 'property', 'who', 'task', 'status', 'source', 'id', 'urgent', 'short'],
    'activity': ['date', 'property', 'person', 'photos', 'first', 'last'],
    'properties': ['property', 'city', 'photos', 'last_activity', 'days_quiet', 'status', 'photos_14d', 'days_worked', 'crew'],
    'team': ['name', 'match', 'aliases', 'role', 'account', 'note'],
}
FORMER = ['Tori Vittori', 'Jessica Blaine']          # never on any page
# Events that are not at a property (staff meetings, unnamed locations): shown by this label, no tile on the page.
NONPROPERTY_MAP = {'Yolanda (CompanyCam login)': 'Team', 'Not stated in the emails': 'Property not named'}
NONPROPERTY = ['Team', 'Property not named']
# Real properties that are valid even with no recent activity (hidden from tiles until they have activity).
KNOWN_PROPS = ['Avanti Chalet', 'Ritz Unit 402', 'Carbondale', 'Elkhorn Escape', "Kiki's"] + NONPROPERTY
# Family names of owners, guests, vendors and staff: public page shows first names only (Luis, Nov 9 2026).
SURNAMES = ['Guber', 'Mothner', 'Sanchez', 'McNicholl', 'Gomez', 'Lapp', 'Caal', 'Hedrick', 'Mora', 'Embry']
STREET_SUFFIX = r'\s+(Road|Rd|Drive|Dr|Court|Ct|Lane|Ln|Avenue|Ave|Street|St|Way|Circle|Cir|Place|Pl)\.?$'

# ---- hard-block patterns -------------------------------------------------
MONEY = re.compile(r'\$|\bUSD\b|\bdollars?\b|\b\d[\d,.]*\s?[kK]\b(?!\w)|\b(invoices?|invoiced|invoicing|profit|billed|billing|owed|payments?|paid|prices?|pricing|costs?|budget|deposit|refund|balance due)\b', re.I)
PHONE = re.compile(r'(\+\d{1,3}[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b|\+\d{1,3}[\s.-]?\d{2,}[\s.-]?\d{3,}')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+|https?://|www\.', re.I)
ACCESS = re.compile(r'\b(gate code|door code|alarm code|lock ?box|pass ?code|combination|password|wi-?fi|keypad code)\b|\b(code|pin)\s*(is|:|#)?\s*\d{3,}', re.I)
HARD = [('money', MONEY), ('phone number', PHONE), ('email or link', EMAIL), ('access code', ACCESS)]

ARRIVAL = re.compile(r'\b(arriv\w*|stay|stays|check-?in|check-?out|guests?|owners?|clients?|family)\b', re.I)
FAMILY = re.compile(r'\b([A-Z][a-z]{2,})s?\s+(family|arrive|arrives|arriving|arrival|stay|stays)\b|\b(owner|guest|client)s?\s+(?:is\s+|are\s+)?([A-Z][a-z]{2,})\b|\b[A-Z][a-z]+ and [A-Z][a-z]+ [A-Z][a-z]{2,}\b')
COMMON = set('The This That Guest Guests Owner Owners Client Clients Family Stay Stays Arrival Arrive Arrives Arriving Visit Cleaning Thanksgiving Waiting Grill Fireplace Nov Oct Dec Jan'.split())

def walk_text(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_text(v, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_text(v, f'{path}[{i}]')
    elif isinstance(obj, str):
        yield path, obj

def short_prop(p):
    s = re.sub(r'\s*\(.*?\)\s*', ' ', str(p)).strip()
    return re.sub(STREET_SUFFIX, '', s, flags=re.I).strip()

def scrub_money(text, log, where):
    """Remove parentheticals and sentences that mention money; keep the operational rest."""
    if not isinstance(text, str) or not MONEY.search(text):
        return text
    orig = text
    text = re.sub(r'\s*\([^)]*\)', lambda m: '' if MONEY.search(m.group(0)) else m.group(0), text)
    parts = re.split(r'(?<=[.!?])\s+', text)
    parts = [p for p in parts if not MONEY.search(p)]
    out = ' '.join(parts).strip()
    out = re.sub(r'\s+([.,;:])', r'\1', out)
    log.append({'where': where, 'removed': orig, 'kept': out})
    return out

def build(raw_dir, out_path, voice_read=None, notes=None, now=None):
    report = {'blocked': [], 'warnings': [], 'scrubbed': [], 'dropped_fields': [], 'info': []}
    raw = {k: json.load(open(os.path.join(raw_dir, k + '.json'))) for k in ALLOWED}
    # structure sanity (protects the page; not a policy rule)
    if not isinstance(raw['jobs'], list) or not raw['jobs'] or not isinstance(raw['activity'], list) or not raw['activity']:
        report['blocked'].append({'rule': 'structure', 'detail': 'jobs or activity is empty or not a list'})
        json.dump(report, open(out_path + '.report.json', 'w'), indent=1)
        return 2, report

    # full-name -> first-name map from team + activity people
    first = {}
    for t in raw['team']:
        if t.get('match'):
            first[t['match']] = t['name']
    for a in raw['activity']:
        p = a.get('person', '')
        if p and p not in first:
            first[p] = p.split()[0]
    # property map (full -> short)
    names = set()
    for k in ('jobs', 'activity', 'properties'):
        for r in raw[k]:
            if r.get('property'):
                names.add(r['property'])
    pmap = {n: NONPROPERTY_MAP.get(n, short_prop(n)) for n in names}

    def clean_text(t, where):
        if not isinstance(t, str):
            return t
        for full in sorted(pmap, key=len, reverse=True):
            if full != pmap[full]:
                t = t.replace(full, pmap[full])
        for sn in SURNAMES:
            t = re.sub(r"\b([A-Z][a-z]+(?: and [A-Z][a-z]+)?) " + sn + r"\b", r"\1", t)
        for full, fn in sorted(first.items(), key=lambda x: -len(x[0])):
            t = t.replace(full, fn)
        for f in FORMER:
            if f in t:
                report['warnings'].append({'rule': 'former contact', 'where': where, 'text': t})
        return scrub_money(t, report['scrubbed'], where)

    out = {}
    for k, allowed in ALLOWED.items():
        rows = []
        for i, r in enumerate(raw[k]):
            dropped = sorted(set(r) - set(allowed))
            if dropped:
                report['dropped_fields'].append({'dataset': k, 'row': i, 'fields': dropped})
            n = {f: r[f] for f in allowed if f in r}
            if 'property' in n:
                n['property'] = pmap.get(n['property'], short_prop(n['property']))
            if k == 'properties':
                n['city'] = ''                      # no city on the public page
            if k == 'activity' and n.get('person') in first:
                n['person'] = first[n['person']]
            if k == 'team' and n.get('match') in first:
                n['match'] = first[n['match']]
            if k == 'team':
                n['note'] = ''                      # internal notes stay private
                n.pop('note')
            for f in ('task', 'short', 'who', 'crew'):
                if f in n:
                    n[f] = clean_text(n[f], f'{k}[{i}].{f}')
            if k == 'jobs' and not str(n.get('task', '')).strip():
                n['task'] = n.get('short') or 'Visit'
            rows.append(n)
        out[k] = rows
    # team.match now holds first names; activity.person too, so they still line up

    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    dates = [a['date'] for a in out['activity']]
    out['meta'] = {
        'generated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'as_of': max(dates) if dates else None,
        'run_date': now.replace(tzinfo=datetime.timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).strftime('%Y-%m-%d'),
        'voice_read': voice_read,
        'notes': notes or [],
        'non_properties': NONPROPERTY,
    }
    json.dump(out, open(out_path, 'w'), indent=1, ensure_ascii=False)
    rc, rep2 = check(out_path, report=report, prev_path=out_path + '.prev')
    return rc, rep2

def check(path, report=None, prev_path=None):
    report = report or {'blocked': [], 'warnings': [], 'scrubbed': [], 'dropped_fields': [], 'info': []}
    data = json.load(open(path))
    # HARD BLOCKS
    for where, text in walk_text({k: v for k, v in data.items() if k != 'meta'}):
        for rule, pat in HARD:
            m = pat.search(text)
            if m:
                report['blocked'].append({'rule': rule, 'where': where, 'match': m.group(0), 'text': text[:200]})
    for where, text in walk_text(data.get('meta', {})):
        for rule, pat in HARD:
            if pat.search(text):
                report['blocked'].append({'rule': rule, 'where': 'meta.' + where, 'text': text[:200]})
    # WARNINGS (lenient: never block)
    known = set()
    for r in data['jobs']:
        known.update(re.findall(r'[A-Z][a-z]{2,}', r.get('who', '')))
    for t in data['team']:
        known.add(t['name'])
    for r in data['jobs']:
        for f in ('task', 'short', 'who'):
            txt = r.get(f) or ''
            for m in FAMILY.finditer(txt):
                cap = [g for g in m.groups() if g and g[0].isupper()]
                cap = [c for c in cap if c not in COMMON and c not in {t['name'] for t in data['team']}]
                if cap or re.search(r'[A-Z][a-z]+ and [A-Z][a-z]+ [A-Z][a-z]{2,}', txt):
                    report['warnings'].append({'rule': 'family name near guest/owner/arrival', 'where': f"job {r.get('id')}.{f}", 'text': txt[:200], 'date': r.get('date')})
                    break
    for r in data['properties']:
        n = r.get('property', '')
        if not re.match(r'^\d', n) and n not in KNOWN_PROPS:
            report['warnings'].append({'rule': 'unusual property name', 'text': n})
    for r in data['jobs']:
        n = r.get('property', '')
        if not re.match(r'^\d', n) and n not in KNOWN_PROPS:
            report['warnings'].append({'rule': 'unusual property name', 'where': f"job {r.get('id')}", 'text': n})
    stale = None
    try:
        today = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=7)
        asof = datetime.datetime.strptime(data['meta']['as_of'], '%Y-%m-%d')
        if (today - asof).days >= 2:
            stale = (today - asof).days
            report['warnings'].append({'rule': 'stale data', 'detail': f'newest photo day is {data["meta"]["as_of"]} ({stale} days old)'})
    except Exception:
        pass
    if prev_path and os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path))
            if len(data['jobs']) < 0.5 * len(prev['jobs']):
                report['warnings'].append({'rule': 'shrunk data', 'detail': f'jobs {len(prev["jobs"])} -> {len(data["jobs"])}'})
        except Exception:
            pass
    json.dump(report, open(path + '.report.json', 'w'), indent=1, ensure_ascii=False)
    rc = 3 if report['blocked'] else 0
    return rc, report

def main(argv):
    if len(argv) >= 4 and argv[1] == 'build':
        vr = None; notes = []
        a = argv[4:]
        i = 0
        while i < len(a):
            if a[i] == '--voice-read': vr = (a[i + 1].lower() == 'yes'); i += 2
            elif a[i] == '--note': notes.append(a[i + 1]); i += 2
            else: i += 1
        rc, rep = build(argv[2], argv[3], vr, notes)
    elif len(argv) >= 3 and argv[1] == 'check':
        rc, rep = check(argv[2])
    else:
        print(__doc__); return 1
    print('RESULT:', {0: 'PASSED', 3: 'BLOCKED', 2: 'STRUCTURE PROBLEM'}[rc])
    print(f"blocked={len(rep['blocked'])} warnings={len(rep['warnings'])} scrubbed={len(rep['scrubbed'])} dropped_fields={len(rep['dropped_fields'])}")
    for b in rep['blocked']: print('  BLOCK', b)
    for w in rep['warnings']: print('  WARN ', w)
    return rc

if __name__ == '__main__':
    sys.exit(main(sys.argv))
