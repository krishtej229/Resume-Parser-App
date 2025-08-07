from flask import Flask, render_template, request
from utils.parser import sequential_parse
import os
from werkzeug.utils import secure_filename
import PyPDF2
from collections import OrderedDict
import json
import re

app = Flask(__name__, template_folder='../frontend/templates', static_folder='../frontend/static')

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'txt'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def calculate_resume_score(parsed):
    score = 0
    total = 0

    # Define fields with weights
    important_fields = {
        'name': 10,
        'email': 10,
        'phone': 10,
        'linkedin': 10,
        'github': 10,
        'education': 15,
        'projects': 15,
        'skills': 15,
        'achievements': 5
    }

    for field, weight in important_fields.items():
        total += weight
        value = parsed.get(field)
        if isinstance(value, str) and value.strip():
            score += weight
        elif isinstance(value, list) and len(value) > 0:
            score += weight

    return round((score / total) * 100, 2)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_profile_links(links):
    github_profile = None
    linkedin_profile = None

    for link in links:
        # Check for GitHub profile link
        github_match = re.match(r'https?://(www\.)?github\.com/[^/]+/?$', link)
        if github_match and not github_profile:
            github_profile = github_match.group(0)

        # Check for LinkedIn profile link (not company or jobs or posts)
        linkedin_match = re.match(r'https?://(www\.)?linkedin\.com/in/[^/]+/?', link)
        if linkedin_match and not linkedin_profile:
            linkedin_profile = linkedin_match.group(0)

    return github_profile, linkedin_profile

def extract_text_from_pdf(path):
    text = []
    with open(path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
    return "\n".join(text)

def extract_links_from_pdf(path):
    import re
    links = []
    with open(path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            annots = page.get("/Annots")
            if annots:
                for a in annots:
                    try:
                        obj = a.get_object()
                        if "/A" in obj and "/URI" in obj["/A"]:
                            uri = obj["/A"]["/URI"]
                            if isinstance(uri, str):
                                links.append(uri)
                    except Exception:
                        continue
    # ✅ Remove duplicates & filter only valid links
    clean_links = []
    for l in links:
        if l.lower().startswith(("http", "mailto:", "tel:")):
            clean_links.append(l)
    return list(dict.fromkeys(clean_links))  # keep order, no duplicates

@app.route('/', methods=['GET', 'POST'])
def index():
    pretty_json = None
    parsed = None
    if request.method == 'POST':
        pasted_text = request.form.get('resume_text', '').strip()
        file = request.files.get('resume_file')
        content, links = "", []

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            if filename.lower().endswith('.pdf'):
                content = extract_text_from_pdf(path)
                links = extract_links_from_pdf(path)
            else:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
        elif pasted_text:
            content = pasted_text

        if content:
            parsed = sequential_parse(content, external_links=links)
            
            # ✅ Final cleanup of raw_links — remove anything too short or invalid
            clean_links = []
            for l in parsed.get('raw_links', []):
                l = l.strip()
                if len(l) < 5:  # too short to be a valid link
                    continue
                if not l.lower().startswith(("http", "mailto:", "tel:")):
                    continue
                clean_links.append(l)
            parsed['raw_links'] = clean_links
            
            # ✅ Extract GitHub and LinkedIn profile links (ignore projects/repos)
            github_profile, linkedin_profile = extract_profile_links(clean_links)
            if github_profile:
                parsed['github'] = github_profile
            if linkedin_profile:
                parsed['linkedin'] = linkedin_profile

            # ✅ Force override email & phone from raw_links if available
            for l in parsed.get('raw_links', []):
                # Fix email from mailto:
                if l.lower().startswith('mailto:'):
                    clean_email = l[7:].strip()  # remove 'mailto:' and spaces
                    # Optional: lowercase for consistency
                    clean_email = clean_email.lower()
                    parsed['email'] = clean_email

                # Fix phone from tel:
                if l.lower().startswith('tel:'):
                    num = l[4:]  # strip 'tel:'
                    num = re.sub(r'[^0-9]', '', num)  # keep only digits
                    if num.startswith('91') and len(num) == 12:
                        parsed['phone'] = '+91-' + num[2:]
                    elif len(num) == 10:
                        parsed['phone'] = '+91-' + num
                    elif num.startswith('+91') and len(num) == 13:
                        parsed['phone'] = '+91-' + num[3:]
                    else:
                        parsed['phone'] = '+' + num

            # Build ordered output dict in the exact key order the user wants
            resume_score = calculate_resume_score(parsed)
            parsed['ai_resume_score'] = resume_score
            output = OrderedDict()
            output['name'] = parsed.get('name', '')
            output['email'] = parsed.get('email', '')
            output['phone'] = parsed.get('phone', '')
            output['linkedin'] = parsed.get('linkedin', '')
            output['github'] = parsed.get('github', '')
            output['education'] = parsed.get('education', [])
            output['projects'] = parsed.get('projects', [])
            output['skills'] = parsed.get('skills', [])
            output['achievements'] = parsed.get('achievements', [])
            output['raw_links'] = parsed.get('raw_links', [])
            output['ordered'] = parsed.get('ordered', [])
            output['ai_resume_score'] = resume_score

            # pretty JSON string (for display)
            pretty_json = json.dumps(output, indent=2, ensure_ascii=False)

    return render_template('index.html', parsed=parsed, pretty_json=pretty_json)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
