# walmart_review_extractor_gui.py (v2.3)
# NOTE: VERSION is defined BEFORE any imports to avoid NameError even if an import fails.
VERSION = '2.3'

import json
import re
import csv
import html as htmllib
import os
import math
import random
from datetime import datetime
from collections import Counter

# --------------------- Optional Matplotlib (wordcloud) ---------------------
MATPLOTLIB_OK = True
MATPLOTLIB_ERR = ''
try:
    import matplotlib
    # matplotlib.use('Agg')  # not required for Streamlit
    import matplotlib.pyplot as plt
except Exception as e:
    MATPLOTLIB_OK = False
    MATPLOTLIB_ERR = str(e)

# --------------------- Parsing Patterns ---------------------
MONTHS = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
FULL_MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'

DATE_PATTERNS = [
    re.compile(rf"\b(({MONTHS})\s+\d{{1,2}},\s*\d{{4}})\b"),
    re.compile(rf"\b(({FULL_MONTHS})\s+\d{{1,2}},\s*\d{{4}})\b"),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"),
]

RATING_PAT = re.compile(r"\b(\d(?:\.\d)?)\s*out of\s*5(?:\s*stars?)?\b", re.IGNORECASE)
TITLE_PAT = re.compile(r"^\s*#{2,6}\s*(.+?)\s*$")

ANNOTATION_PAT = re.compile(
    r"^(Verified Purchase|Walmart Associate|Review from\b|Helpful\?|Report$|Top Reviewer$|Write a review$|\[.*?\])",
    re.IGNORECASE,
)

FOOTER_KEYWORDS = [
    "All Departments","Store Directory","Careers","Our Company","Sell on Walmart.com","Help",
    "Product Recalls","Accessibility","Tax Exempt Program","Get the Walmart App","Safety Data Sheet",
    "Terms of Use","Privacy Notice","California Supply Chain Act","Your Privacy Choices",
    "Customer Privacy Center","Notice at Collection","AdChoices","Consumer Health Data Privacy Notices",
    "Brand Shop Directory","Pharmacy","Walmart Business","Walmart In the Know","Delete Account",
]

PAGINATION_HINT = re.compile(
    r"^\s*-\s*\[\d+\]|^\s*All filters\b|^\s*Showing\b|^\s*Most relevant\b|^\s*Next\b|^\s*Previous\b",
    re.IGNORECASE,
)

KEY_CANDIDATES = {
    'rating': ['rating', 'reviewRating', 'ratingValue', 'overallRating', 'overall_rating', 'overall'],
    'reviewText': ['reviewText', 'reviewTextRaw', 'text', 'reviewContent', 'body', 'review_body', 'commentText'],
    'reviewSubmissionTime': ['reviewSubmissionTime', 'submissionTime', 'created', 'reviewCreated',
                             'submissionDate', 'datePublished', 'createdAt', 'submission_date', 'createdDate'],
    'reviewTitle': ['reviewTitle', 'title', 'headline', 'reviewHeader', 'review_title'],
}

# --------------------- Helpers ---------------------

def normalize_date(s: str) -> str:
    s = s.strip()
    for fmt in ('%b %d, %Y', '%B %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except Exception:
            pass
    return s


def parse_date_from_line(line: str) -> str:
    for pat in DATE_PATTERNS:
        m = pat.search(line)
        if m:
            return normalize_date(m.group(1))
    return ''


def coalesce(obj, keys):
    for k in keys:
        if k in obj and obj[k] not in (None, ''):
            v = obj[k]
            if isinstance(v, dict) and 'ratingValue' in v and v['ratingValue'] not in (None, ''):
                return v['ratingValue']
            return v
    return None


def clean_annotation_line(line: str) -> bool:
    if ANNOTATION_PAT.match(line):
        return True
    if line.strip().lower() in ('report','write a review','top reviewer'):
        return True
    return False


def is_footer_line(line: str) -> bool:
    low = line.strip().lower()
    if any(k.lower() == low for k in FOOTER_KEYWORDS):
        return True
    if len(line) <= 3 and line.isalpha():
        return True
    return False


def scrub_text(txt: str) -> str:
    txt = re.sub(r"\s*\[.*?\]\s*", " ", txt)
    txt = re.sub(r"\b(Verified Purchase|Walmart Associate)\b", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

# --------------------- JSON Extraction ---------------------

def walk_json(o, results):
    if isinstance(o, dict):
        rating = coalesce(o, KEY_CANDIDATES['rating'])
        if isinstance(rating, dict) and 'ratingValue' in rating:
            rating = rating['ratingValue']
        reviewText = coalesce(o, KEY_CANDIDATES['reviewText'])
        reviewSubmissionTime = coalesce(o, KEY_CANDIDATES['reviewSubmissionTime'])
        reviewTitle = coalesce(o, KEY_CANDIDATES['reviewTitle'])

        txt = str(reviewText).strip() if reviewText is not None else ''
        if txt:
            txt = scrub_text(txt)

        if txt:
            results.append({
                'rating': rating if isinstance(rating, (int, float, str)) else '',
                'reviewText': txt,
                'reviewSubmissionTime': str(reviewSubmissionTime).strip() if reviewSubmissionTime is not None else '',
                'reviewTitle': str(reviewTitle).strip() if reviewTitle is not None else '',
            })
        for v in o.values():
            walk_json(v, results)

    elif isinstance(o, list):
        for item in o:
            walk_json(item, results)


def find_json_objects(raw: str):
    results = []
    key_regex = re.compile(r'(\"reviewText\"|\"reviewTitle\"|\"datePublished\"|\"reviewSubmissionTime\"|\"ratingValue\")')
    for m in key_regex.finditer(raw):
        start = raw.rfind('{', 0, m.start())
        if start == -1:
            continue
        end = None
        depth = 0
        for i in range(start, min(len(raw), start + 20000)):
            ch = raw[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end:
            frag = raw[start:end]
            try:
                obj = json.loads(frag)
                results.append(obj)
            except Exception:
                continue
    return results


def extract_from_json(text: str):
    results = []
    try:
        data = json.loads(text)
        walk_json(data, results)
    except Exception:
        pass
    if not results:
        un = htmllib.unescape(text)
        if un != text:
            try:
                data = json.loads(un)
                walk_json(data, results)
            except Exception:
                pass
    for block in re.findall(r'<script[^>]*application/(?:ld\+json|json)[^>]*>(.*?)</script>', text, flags=re.IGNORECASE|re.DOTALL):
        blk = htmllib.unescape(block)
        try:
            data = json.loads(blk)
            walk_json(data, results)
        except Exception:
            continue
    for m in re.finditer(r'data-[a-zA-Z-]+="(\{.*?\})"', text, flags=re.DOTALL):
        blob = htmllib.unescape(m.group(1))
        try:
            data = json.loads(blob)
            walk_json(data, results)
        except Exception:
            pass
    for obj in find_json_objects(htmllib.unescape(text)):
        walk_json(obj, results)

    unique, seen = [], set()
    for r in results:
        if not r.get('reviewText'):
            continue
        key = (r.get('reviewText','')[:160], r.get('reviewSubmissionTime',''))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

# --------------------- HTML Fallback ---------------------

def extract_from_html(text: str):
    raw = htmllib.unescape(text).replace('\r\n', '\n')
    lines = [ln.strip() for ln in raw.split('\n') if ln.strip()]
    results = []
    cur = None

    def flush():
        nonlocal cur
        if not cur:
            return
        body = cur.get('reviewText','').strip()
        if body:
            body = '\n'.join([l for l in body.splitlines() if not clean_annotation_line(l)])
            body = scrub_text(body)
        cur['reviewText'] = body
        if cur.get('reviewText'):
            results.append(cur)
        cur = None

    for raw_line in lines:
        if PAGINATION_HINT.search(raw_line) or is_footer_line(raw_line):
            flush();
            continue
        d = parse_date_from_line(raw_line)
        if d:
            flush(); cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': d}; continue
        mrat = RATING_PAT.search(raw_line)
        if mrat:
            if not cur:
                cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': ''}
            else:
                if cur.get('reviewText'):
                    flush(); cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': ''}
            cur['rating'] = mrat.group(1)
            continue
        mt = TITLE_PAT.match(raw_line)
        if mt:
            if not cur:
                cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': ''}
            if not cur.get('reviewTitle'):
                cur['reviewTitle'] = mt.group(1).strip()
            continue
        if clean_annotation_line(raw_line):
            if not cur:
                cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': ''}
            continue
        if not cur:
            cur = {'rating':'', 'reviewTitle':'', 'reviewText':'', 'reviewSubmissionTime': ''}
        cur['reviewText'] = (cur['reviewText'] + '\n' if cur['reviewText'] else '') + raw_line

    flush()

    unique, seen = [], set()
    for r in results:
        key = (r.get('reviewText','')[:160], r.get('reviewSubmissionTime',''))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

# --------------------- Orchestrator ---------------------

def extract_reviews(text: str):
    js = extract_from_json(text)
    if js:
        return js
    return extract_from_html(text)

# --------------------- Sentiment & Keywords ---------------------
STOPWORDS = set([
    'a','about','above','after','again','against','all','am','an','and','any','are','as','at','be','because','been',
    'before','being','below','between','both','but','by','can','cannot','could','did','do','does','doing','down',
    'during','each','few','for','from','further','had','has','have','having','he','her','here','hers','herself','him',
    'himself','his','how','i','if','in','into','is','it','its','itself','me','more','most','my','myself','no','nor',
    'not','of','off','on','once','only','or','other','our','ours','ourselves','out','over','own','same','she','should',
    'so','some','such','than','that','the','their','theirs','them','themselves','then','there','these','they','this',
    'those','through','to','too','under','until','up','very','was','we','were','what','when','where','which','while',
    'who','whom','why','with','would','you','your','yours','yourself','yourselves',
    "it's","its","i'm","we're","you're","they're","i've","we've","you've","they've",
    "i'll","we'll","you'll","they'll","i'd","we'd","you'd","they'd",
    'will','just','really','though','sure','maybe','kinda','sorta','bit','lot','also','etc','ok','okay','still',
])

POS_WORDS = set([
    'good','great','excellent','amazing','awesome','delicious','tasty','love','loved','loving','like','liked','wonderful',
    'perfect','reliable','consistent','creamy','rich','smooth','best','favorite','go-to','yummy','recommend','recommended',
    'quick','easy','fresh','fast','crisp','crispy','value','affordable','pleased','satisfied','fantastic','outstanding',
    'five-star','perfectly','nostalgic','balanced','nice',
])

NEG_WORDS = set([
    'bad','worse','worst','bland','gross','greasy','soggy','stale','burnt','disappointing','disappointed','dislike',
    'hated','hate','hard','tough','rubbery','overcooked','undercooked','cold','salty','too-salty','sweet','too-sweet',
    'bitter','sour','grainy','expensive','pricey','costly','missing','broken','dented','damaged','late','slow','poor',
    'terrible','awful','mediocre','meh','boring','lack','lacks','lacking','issue','issues','problem','problems','wrong',
    'empty','watery','thin','thick','runny','inedible','never','again','explode','exploded','substitute','charged','pour',
])


def normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.lower()
    s = re.sub(r'https?://\S+', ' ', s)
    s = s.replace('&amp;', ' & ').replace('&nbsp;', ' ')
    s = re.sub(r"[^a-z0-9\s']", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def token_filter(tokens):
    return [w for w in tokens if w and w not in STOPWORDS and len(w) > 2]


def text_sentiment_score(text: str) -> float:
    t = normalize_text(text)
    if not t:
        return 0.0
    tokens = token_filter(t.split())
    if not tokens:
        return 0.0
    pos = sum(1 for w in tokens if w in POS_WORDS)
    neg = sum(1 for w in tokens if w in NEG_WORDS)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def rating_score(val) -> float:
    try:
        r = float(val)
        r = max(1.0, min(5.0, r))
        return (r - 3.0) / 2.0
    except Exception:
        return 0.0


def label_from_score(s: float) -> str:
    if s >= 0.2:
        return 'positive'
    if s <= -0.2:
        return 'negative'
    return 'neutral'


def compute_sentiment(rows):
    enriched = []
    for r in rows:
        txt = r.get('reviewText','') or ''
        ts = text_sentiment_score(txt)
        rs = rating_score(r.get('rating',''))
        combined = 0.6*rs + 0.4*ts
        enriched.append({
            'rating': r.get('rating',''),
            'reviewText': txt,
            'reviewSubmissionTime': r.get('reviewSubmissionTime',''),
            'reviewTitle': r.get('reviewTitle',''),
            'text_score': round(ts, 3),
            'rating_score': round(rs, 3),
            'combined_score': round(combined, 3),
            'sentiment': label_from_score(combined),
        })
    return enriched


def extract_keywords_and_bigrams(texts, top_n_words=100, top_n_bigrams=50):
    all_tokens = []
    for txt in texts:
        t = normalize_text(txt)
        if not t:
            continue
        toks = token_filter(t.split())
        all_tokens.extend(toks)
    word_freq = Counter(all_tokens)

    bigram_freq = Counter()
    for i in range(len(all_tokens)-1):
        a, b = all_tokens[i], all_tokens[i+1]
        if a in STOPWORDS or b in STOPWORDS:
            continue
        if len(a) <= 2 or len(b) <= 2:
            continue
        bigram = f"{a} {b}"
        bigram_freq[bigram] += 1

    top_words = word_freq.most_common(top_n_words)
    top_bigrams = bigram_freq.most_common(top_n_bigrams)
    return top_words, top_bigrams


def render_wordcloud_png(freq_items, out_path):
    if not MATPLOTLIB_OK:
        with open(out_path.replace('.png','_NOTE.txt'),'w',encoding='utf-8') as f:
            f.write('Wordcloud skipped: Matplotlib not installed. ' + (MATPLOTLIB_ERR or ''))
        return

    if not freq_items:
        fig, ax = plt.subplots(figsize=(10,6))
        ax.text(0.5,0.5,'No terms',ha='center',va='center',fontsize=18)
        ax.set_axis_off(); fig.savefig(out_path, dpi=200, bbox_inches='tight'); plt.close(fig)
        return

    random.seed(42)
    fig, ax = plt.subplots(figsize=(12,8))
    ax.set_axis_off(); ax.set_xlim(0,1); ax.set_ylim(0,1)

    occupied = []
    def place_word(ax, text, font_size):
        for _ in range(300):
            x = random.uniform(0.05, 0.95)
            y = random.uniform(0.05, 0.95)
            t = ax.text(x, y, text, fontsize=font_size, ha='center', va='center', alpha=0.9)
            fig.canvas.draw()
            bbox = t.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(ax.transData.inverted())
            if not any(bbox.overlaps(ob) for ob in occupied):
                occupied.append(bbox)
                return True
            t.remove()
        return False

    max_cnt = max(c for _, c in freq_items)
    for token, cnt in freq_items:
        size = 12 + int(38 * (cnt / max_cnt))
        if not place_word(ax, token, size):
            ax.text(random.uniform(0.05,0.95), random.uniform(0.05,0.95), token, fontsize=10, ha='center', va='center', alpha=0.6)

    fig.savefig(out_path, dpi=200, bbox_inches='tight'); plt.close(fig)

# --------------------- Export helpers ---------------------

def export_with_sentiment(rows, save_path):
    base, _ = os.path.splitext(save_path)
    csv_plain = save_path
    csv_sent = base + '_with_sentiment.csv'
    csv_words = base + '_top_keywords.csv'
    csv_bigrams = base + '_top_bigrams.csv'
    png_wordcloud = base + '_wordcloud.png'

    fieldnames = ['rating','reviewText','reviewSubmissionTime','reviewTitle']
    with open(csv_plain, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames); w.writeheader()
        for r in rows: w.writerow({k: r.get(k,'') for k in fieldnames})

    enriched = compute_sentiment(rows)
    field2 = fieldnames + ['text_score','rating_score','combined_score','sentiment']
    with open(csv_sent, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=field2); w.writeheader()
        for r in enriched: w.writerow({k: r.get(k,'') for k in field2})

    texts = [r.get('reviewText','') or '' for r in rows]
    top_words, top_bigrams = extract_keywords_and_bigrams(texts)
    with open(csv_words, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['word','count']); [w.writerow(x) for x in top_words]
    with open(csv_bigrams, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['bigram','count']); [w.writerow(x) for x in top_bigrams]

    wc_items = top_words[:60] + top_bigrams[:30]
    render_wordcloud_png(wc_items, png_wordcloud)

    return csv_plain, csv_sent, csv_words, csv_bigrams, png_wordcloud


from io import BytesIO

def render_wordcloud_bytes(freq_items):
    """Return a PNG (bytes) for the simple matplotlib-based word cloud used in the desktop app."""
    if not MATPLOTLIB_OK:
        return b''

    if not freq_items:
        fig, ax = plt.subplots(figsize=(10,6))
        ax.text(0.5,0.5,'No terms',ha='center',va='center',fontsize=18)
        ax.set_axis_off()
        bio = BytesIO()
        fig.savefig(bio, dpi=200, bbox_inches='tight', format='png')
        plt.close(fig)
        return bio.getvalue()

    random.seed(42)
    fig, ax = plt.subplots(figsize=(12,8))
    ax.set_axis_off(); ax.set_xlim(0,1); ax.set_ylim(0,1)

    occupied = []
    def place_word(ax, text, font_size):
        for _ in range(300):
            x = random.uniform(0.05, 0.95)
            y = random.uniform(0.05, 0.95)
            t = ax.text(x, y, text, fontsize=font_size, ha='center', va='center', alpha=0.9)
            fig.canvas.draw()
            bbox = t.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(ax.transData.inverted())
            if not any(bbox.overlaps(ob) for ob in occupied):
                occupied.append(bbox)
                return True
            t.remove()
        return False

    max_cnt = max(c for _, c in freq_items)
    for token, cnt in freq_items:
        size = 12 + int(38 * (cnt / max_cnt))
        if not place_word(ax, token, size):
            ax.text(random.uniform(0.05,0.95), random.uniform(0.05,0.95), token, fontsize=10, ha='center', va='center', alpha=0.6)

    bio = BytesIO()
    fig.savefig(bio, dpi=200, bbox_inches='tight', format='png')
    plt.close(fig)
    return bio.getvalue()
