import re

# Regexes
EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
PHONE_RE = re.compile(r'(\+?\d{1,3}[-.\s]?)?(\(?\d{2,4}\)?[-.\s]?)?[\d\-.\s]{6,14}\d')
URL_RE = re.compile(
    r'((?:https?://)?(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[A-Za-z0-9#?&=._\-/%+]*)?)',
    re.IGNORECASE
)

SECTION_TITLES = [
    'education','projects','technical skills','skills','achievements','coding profiles',
    'positions of responsibility','experience','projects','education','achievements','positions'
]

def normalize_url(u):
    if not u:
        return ""
    if not u.startswith('http'):
        return 'https://' + u.lstrip('/')
    return u

def find_email(text):
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""

def find_phone(text, links=None):
    # Try from text first
    candidates = PHONE_RE.findall(text)
    flat = []
    for c in candidates:
        if isinstance(c, tuple):
            flat.append("".join(c))
        else:
            flat.append(c)

    if flat:
        cleaned = [re.sub(r'[^+\d]', '', s) for s in flat]
        cleaned = [s for s in cleaned if len(re.sub(r'\D', '', s)) >= 7]
        if cleaned:
            phone = max(cleaned, key=len)
            if phone.startswith('91') and len(phone) == 12:
                phone = '+91-' + phone[2:]
            elif len(phone) == 10:
                phone = '+91-' + phone
            elif phone.startswith('+91') and len(phone) == 13:
                phone = '+91-' + phone[3:]
            return phone

    # Try from PDF links
    if links:
        for l in links:
            if l.lower().startswith('tel:'):
                num = l[4:]
                num = re.sub(r'[^+\d]', '', num)
                if num.startswith('91') and len(num) == 12:
                    return '+91-' + num[2:]
                elif len(num) == 10:
                    return '+91-' + num
                elif num.startswith('+91') and len(num) == 13:
                    return '+91-' + num[3:]
                else:
                    return '+' + num

    return ""

def find_urls(text):
    return [m[0] for m in URL_RE.findall(text)]

def guess_name_from_header(lines):
    # lines is list of top header lines
    for line in lines[:6]:
        # skip lines that are clearly email/phone/urls
        if EMAIL_RE.search(line) or PHONE_RE.search(line) or URL_RE.search(line):
            continue
        # likely name: short, letters, <=4 words
        if 1 <= len(line.split()) <= 4 and re.search(r'[A-Za-z]', line):
            return line.strip()
    # fallback: first non-empty line
    return lines[0].strip() if lines else ""

def tag_line(line):
    low = line.strip().lower()
    if not line.strip():
        return 'blank'
    if EMAIL_RE.search(line) or line.strip().startswith('mailto:'):
        return 'contact:email'
    if PHONE_RE.search(line) or line.strip().startswith('tel:'):
        return 'contact:phone'
    if URL_RE.search(line):
        return 'link'
    # If it looks like a section title
    for t in SECTION_TITLES:
        if low.strip().startswith(t):
            return f'section:{t}'
    # bullet detection
    if line.strip().startswith(('•','-','*')) or re.match(r'^\d+\.', line.strip()):
        return 'bullet'
    # else generic paragraph
    return 'paragraph'

def sequential_parse(text, external_links=None):
    """
    Parse text line-by-line and produce ordered blocks with inferred tags.
    Returns:
      - ordered: list of {type, text}
      - summary fields like name, email, phone, linkedin, github, etc.
    """
    lines = [l.rstrip() for l in text.splitlines()]

    # Extract any external links first
    urls_from_text = find_urls(text)
    all_links = []
    if external_links:
        for l in external_links:
            if l not in all_links:
                all_links.append(l)
    for u in urls_from_text:
        if u not in all_links:
            all_links.append(u)

    # Build ordered list
    ordered = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        lt = tag_line(line)
        entry = {'type': lt, 'text': line.strip(), 'line_no': i}
        # try to attach extracted simple fields
        if lt == 'contact:email':
            # normalize mailto:
            email = re.sub(r'^mailto:', '', line.strip(), flags=re.I)
            entry['email'] = EMAIL_RE.search(email).group(0) if EMAIL_RE.search(email) else email
        if lt == 'contact:phone':
            phone = re.sub(r'^tel:', '', line.strip(), flags=re.I)
            entry['phone'] = re.sub(r'[^+\d]', '', phone)
        if lt == 'link':
            # capture all urls on this line
            urls = find_urls(line)
            entry['urls'] = [normalize_url(u) for u in urls]
        ordered.append(entry)

    # Post-process: try to detect header block (top few lines before first section)
    # Identify first section line index
    first_section_idx = None
    for idx, e in enumerate(ordered):
        if e['type'].startswith('section:'):
            first_section_idx = idx
            break
    header_lines = []
    if first_section_idx is None:
        # no explicit sections found; consider first 4 lines as header
        header_lines = [e['text'] for e in ordered[:4]]
    else:
        header_lines = [e['text'] for e in ordered[:first_section_idx]]

    name = guess_name_from_header(header_lines)

    # Gather email / phone if not explicitly marked
    email = find_email(text)
    phone = find_phone(text)

    # collect link-based profiles
    linkedin = ""
    github = ""
    for u in all_links:
        lu = u.lower()
        if 'linkedin.com' in lu:
            linkedin = normalize_url(u)
        if 'github.com' in lu:
            github = normalize_url(u)

    # For backward compatibility, also extract education/projects/skills/achievements from sections
    # Simple heuristics: collect text under a section title until next section title
    sections = {}
    cur_section = None
    for e in ordered:
        if e['type'].startswith('section:'):
            cur_section = e['type'].split(':',1)[1]
            sections.setdefault(cur_section, [])
        else:
            if cur_section:
                sections.setdefault(cur_section, []).append(e['text'])
            else:
                # lines before first section can be considered header content
                sections.setdefault('header', []).append(e['text'])

    # simple extractors that return lists
    def extract_education(section_lines):
        candidates = []
        for l in section_lines:
            if re.search(r'\b(Bachelor|B\.A|B\.S|BSc|BE|BTech|Master|M\.S|MSc|MBA|PhD|CGPA|Percentage|Senior School)\b', l, re.I) or re.search(r'\b(20\d{2}|19\d{2})\b', l):
                candidates.append(l)
        return candidates if candidates else section_lines[:4]

    def extract_projects(section_lines):
        # join and split by blank lines or project delimiters (—, — etc)
        raw = "\n".join(section_lines)
        parts = [p.strip() for p in re.split(r'\n-{2,}|\n\n+|\n\s*–\s*|\n\s*-\s*', raw) if p.strip()]
        return parts[:20]

    def extract_skills(section_lines):
        raw = " ".join(section_lines)
        items = re.split(r'[,•\n;]+', raw)
        items = [i.strip() for i in items if i.strip()]
        # dedupe preserving order
        seen = []
        for it in items:
            if it.lower() not in [s.lower() for s in seen]:
                seen.append(it)
        return seen[:100]

    education = extract_education(sections.get('education', []))
    projects = extract_projects(sections.get('projects', []) or sections.get('project', []))
    skills = extract_skills(sections.get('technical skills', []) or sections.get('skills', []))
    achievements = sections.get('achievements', []) or sections.get('honors', [])

    return {
        'ordered': ordered,
        'name': name,
        'email': email,
        'phone': phone,
        'linkedin': linkedin,
        'github': github,
        'education': education,
        'projects': projects,
        'skills': skills,
        'achievements': achievements,
        'raw_links': all_links,
        'sections': sections
    }
