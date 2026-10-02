"""Conservative, evidence-backed extraction of four fields. No AI calls.

Known patterns cover Serbian Latin, English and common Russian phrases.
Unrecognized phrasing stays UNKNOWN; alternatives/conflicts stay visible.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

VERSION = 'four-fields-v1'


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


def evidence(quote, path='description_original', context=None):
    item = {'source_path': path, 'quote': quote}
    if context:
        item['context'] = context
    return item


def result(value=None, proofs=None, status=None):
    return {'status': status or ('KNOWN' if value is not None else 'UNKNOWN'),
            'value': value, 'evidence': proofs or []}


def requirement(text, context='UNKNOWN'):
    t = fold(text)
    if re.search(r'not required|not mandatory|\bno .{0,30}required|nije (?:neophod|obavez)|nisu (?:neophod|obavez)|не (?:требуется|обязател)', t):
        return 'NOT_REQUIRED'
    if re.search(r'preferred|beneficial|advantage|desirable|optional|pozelj|prednost|желател|преимуществ', t):
        return 'PREFERRED'
    if re.search(r'\brequired\b|\bmust\b|mandatory|neophod|obavezn|minimum|\bmin\b|обязател|требуется', t):
        return 'REQUIRED'
    return context


LANGUAGES = {
    'en': r'\benglish\b|\bengles\w*|англий\w*',
    'sr': r'\bserbian\b|\bsrpsk\w*|сербск\w*',
    'de': r'\bgerman\b|\bnemack\w*|немец\w*',
    'ru': r'\brussian\b|\brusk\w*|русск\w*',
    'fr': r'\bfrench\b|\bfrancusk\w*|француз\w*',
    'it': r'\bitalian\b|\bitalijansk\w*|итальян\w*',
    'es': r'\bspanish\b|\bspansk\w*|испанск\w*',
}


def clauses(description):
    context, heading = 'UNKNOWN', None
    for line in (description or '').splitlines():
        t = fold(line).strip(' :•.;')
        if re.fullmatch(r'(potrebne kvalifikacije|potrebni uslovi|uslovi(?: i kvalifikacije)?|uslov|basic qualifications|qualifications and requirements|education and experience|requirements|требования)', t):
            context, heading = 'REQUIRED', line
            continue
        if re.fullmatch(r'preferred qualifications', t):
            context, heading = 'PREFERRED', line
            continue
        if re.fullmatch(r'(preferred knowledge|profile and mindset|zaduzenja|opis posla|opis zaduzenja|nudimo|poslodavac nudi|kompanija nudi|what we offer|what we value|your responsibilities encompass)', t):
            context, heading = 'UNKNOWN', None
            continue
        for part in re.split(r';|\b(?:but|ali)\b|,\s*(?=(?:poželj|preferred|German|English|Serbian|dodatni))', line, flags=re.I):
            if part.strip():
                yield part.strip(), context, heading


def languages(description):
    items, proofs = [], []
    for text, ctx, heading in clauses(description):
        t = fold(text)
        codes = [code for code, pattern in LANGUAGES.items() if re.search(pattern, t)]
        if not codes:
            continue
        if not re.search(r'znanje|poznavanje|jezik|language skills|knowledge of|proficien|fluen|speak|command of|\b[a-c][12]\b|required|mandatory|preferred|beneficial|advantage|optional|not required|знани|язык|владени', t):
            continue
        if re.search(r'courses?|classes|lessons|kursev|casov|часов|курсы', t):
            continue
        levels = re.findall(r'\b[A-C][12]\b', text, flags=re.I)
        level = levels[0].upper() if len(set(v.upper() for v in levels)) == 1 else None
        qualitative = re.search(r'fluent|native|excellent|good|basic|odli[cč]\w*|osnovn\w*(?:\s+konverzacij\w*)?|napredn\w*|свободн\w*|базов\w*', text, flags=re.I)
        for code in codes:
            item = {'language': code, 'requirement': requirement(text, ctx),
                    'level': level, 'level_original': qualitative.group(0) if qualitative else None,
                    'evidence': evidence(text, context=heading)}
            if item not in items:
                items.append(item)
                proofs.append(item['evidence'])
    conflict = any(len({v['requirement'] for v in items if v['language']==code and v['requirement']!='UNKNOWN'}) > 1
                   for code in LANGUAGES)
    return result(items or None, proofs, 'REVIEW' if conflict else None)


def education(description, payload):
    items, proofs = [], []
    pattern = r'\bsss\b|\bvss\b|\bv[is]s\b|obrazovan|strucne spreme|\bmaster inzenjer|\b(?:undergraduate |bachelor.?s? |master.?s? )?degree\b|vocational (?:it )?training|apprenticeship|высшее образование|среднее образование'
    for text, ctx, heading in clauses(description):
        t = fold(text)
        if not re.search(pattern, t):
            continue
        if ctx == 'UNKNOWN' and not re.search(r'^\W*(?:minimum|sss|vss|completed|degree|undergraduate|bachelor|master|visoko obrazovanje)|required|neophod|обязател', t):
            continue
        alternative = bool(re.search(r'\bor\b|and/or|\bili\b|equivalent|comparable|или', t))
        levels = []
        for code, p in [('MASTER', r'\bmaster'), ('HIGHER', r'\bvss\b|visoko obrazovanje|undergraduate|bachelor'),
                        ('SECONDARY', r'\bsss\b|srednj\w* (?:skol|obrazov)|среднее образование'),
                        ('VOCATIONAL', r'vocational|apprenticeship'), ('DEGREE_UNSPECIFIED', r'\bdegree\b')]:
            if re.search(p, t):
                levels.append(code)
        proof = evidence(text, context=heading)
        items.append({'statement': text, 'levels': levels or None, 'has_alternatives': alternative,
                      'requirement': requirement(text, ctx), 'evidence': proof})
        proofs.append(proof)
    # Do not use generic min/max metadata to override explicit alternatives in text.
    if not items:
        for index, entry in enumerate(payload.get('educationRequirements') or []):
            if isinstance(entry, dict) and isinstance(entry.get('srName'), str):
                proof = evidence(entry['srName'], f'original_payload.educationRequirements[{index}].srName')
                items.append({'statement': entry['srName'], 'bound': entry.get('level'),
                              'requirement': 'UNKNOWN', 'levels': None, 'has_alternatives': None,
                              'evidence': proof})
                proofs.append(proof)
    return result(items or None, proofs)


def work_mode(description):
    candidates, proofs = [], []
    uncertain = False
    patterns = {
        'HYBRID': r'hybrid (?:work|position|role|model)|hibridn\w* (?:rad|model)|гибридн\w* (?:формат|работ)',
        'REMOTE': r'work(?:ing)? from home|remote (?:work\b|position|role|job\b)|rad (?:od kuce|na daljinu)|удаленн\w* работ|работа удаленно',
        'OFFICE': r'mesto rada:\s*kancelarija|rad (?:iz|u) kancelarij|work(?:ing)? (?:from|in) (?:the )?office|office.based (?:role|position)|работа (?:из|в) офис',
    }
    for line in (description or '').splitlines():
        t = fold(line)
        found = [code for code, p in patterns.items() if re.search(p, t)]
        if not found:
            continue
        if re.search(r'not (?:a |an )?(?:remote|hybrid)|no remote|(?:is|are) not (?:available|offered|allowed)|nije moguc|nije dozvoljen|не предусмотрен|не удаленн', t):
            continue
        if re.search(r'possibil|option|may |mogucnost|povremeno|возможност', t):
            uncertain = True
        if 'HYBRID' in found:
            found = ['HYBRID']
        candidates.extend(found)
        proofs.append(evidence(line))
    modes = set(candidates)
    if uncertain or len(modes) > 1:
        return result(None, proofs, 'REVIEW')
    return result(next(iter(modes)) if modes else None, proofs)


NUMBER = r'\d+(?:[.,\u00a0 ]\d+)*'
AMOUNT = re.compile(r'(?<![\d.,])(' + NUMBER + r')(?:\s*[-–—]\s*(' + NUMBER + r'))?\s*(RSD|EUR|USD|€|dinara|din\b|руб\.?|RUB)?', re.I)


def amount(value):
    s = value.replace('\u00a0', '').replace(' ', '')
    # Explicit grouping or decimal formats; no currency scale conversion.
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?', s):
        s = s.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?', s):
        s = s.replace(',', '')
    elif re.fullmatch(r'\d+(?:[.,]\d{1,2})?', s):
        s = s.replace(',', '.')
    else:
        return None
    try:
        return str(Decimal(s))
    except InvalidOperation:
        return None


def salary_line(text, allow_bare=False):
    t = fold(text)
    if re.search(r'bonus|bonusi|naknad|reimburse|бонус|компенсац|%', t):
        return None
    matches = list(AMOUNT.finditer(text))
    if len(matches) != 1:
        return None
    m = matches[0]
    if not allow_bare and not m[3] and not re.search(
            r'(?:platu|plata|zarad\w*|salary|wage|pay|зарплата)\s*(?:u iznosu\s*)?(?:od\s*|from\s*|от\s*)?[:=]?\s*$', fold(text[:m.start()])):
        return None
    low, high = amount(m[1]), amount(m[2]) if m[2] else None
    if low is None or (m[2] and high is None):
        return None
    if high is not None and Decimal(low) > Decimal(high):
        return None
    if high is None:
        if re.search(r'u iznosu od\s*$', fold(text[:m.start()])):
            high = low
        elif re.search(r'\b(?:up to|do)\b|до\s*$', fold(text[:m.start()])):
            low, high = None, low
        elif re.search(r'\b(?:from|od|starting at|at least)\b|от\s*$', fold(text[:m.start()])):
            pass
        else:
            high = low
    currency = {'€':'EUR', 'DINARA':'RSD', 'DIN':'RSD', 'РУБ':'RUB', 'РУБ.':'RUB'}.get((m[3] or '').upper(), (m[3] or '').upper()) or None
    periods = [code for code,p in [('MONTH',r'month|mesec|мес'),('HOUR',r'hour|satu|satnica|час'),('YEAR',r'annual|year|godis|год'),('DAY',r'daily|dnevno|день')] if re.search(p,t)]
    basis = [code for code,p in [('NET',r'\bnet\b|neto|нетто'),('GROSS',r'gross|bruto|брутто')] if re.search(p,t)]
    return {'min':low, 'max':high, 'currency':currency,
            'period':periods[0] if len(periods)==1 else None,
            'basis':basis[0] if len(basis)==1 else None}


def salary(description, payload):
    candidates = []
    display = payload.get('salary')
    if isinstance(display, str) and display.strip():
        val = salary_line(display, allow_bare=True)
        if val:
            candidates.append((val, evidence(display, 'original_payload.salary')))
    for line in (description or '').splitlines():
        if re.search(r'platu|plata|zarad|salary|pay\b|wage|зарплат|оплат', fold(line)):
            val = salary_line(line)
            if val:
                candidates.append((val, evidence(line)))
    if not candidates:
        return result()
    # Displayed salary takes priority over internal minor-unit fields.
    primary = candidates[0][0]
    for val, proof in candidates[1:]:
        for key in ('min', 'max', 'currency', 'period', 'basis'):
            a,b = primary[key],val[key]
            if a is not None and b is not None and (Decimal(a)!=Decimal(b) if key in ('min','max') else a!=b):
                return result(None, [p for v,p in candidates], 'REVIEW')
    return result(primary, [p for v,p in candidates])


def extract_four(description, payload):
    return {'languages': languages(description), 'education': education(description, payload),
            'work_mode': work_mode(description), 'salary': salary(description, payload)}
