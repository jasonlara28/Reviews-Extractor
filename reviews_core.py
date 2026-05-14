# reviews_core.py
# v5:
#  - ignore non-review labels (Incentivized Review, Verified Purchase)
#  - parse ALL __NEXT_DATA__ blocks (multi-page append)
#  - replace noisy bigrams with meaningful 3–4 word phrases
#  - sentiment: 5★ => 1.0, 1★ => -1.0, plus shipping-vs-product conflict -> neutral

import json
import re
import html as htmllib
from datetime import datetime
from collections import Counter
import random

# --------------------- Optional Matplotlib (wordcloud) ---------------------
MATPLOTLIB_OK = True
MATPLOTLIB_ERR = ''
try:
    import matplotlib
    import matplotlib.pyplot as plt
except Exception as e:
    MATPLOTLIB_OK = False
    MATPLOTLIB_ERR = str(e)

# --------------------- Candidate keys ---------------------
KEY_CANDIDATES = {
    'rating': ['rating', 'reviewRating', 'ratingValue', 'overallRating', 'overall_rating', 'overall'],
    'reviewText': ['reviewText', 'reviewTextRaw', 'text', 'reviewContent', 'body', 'review_body', 'commentText'],
    'reviewSubmissionTime': ['reviewSubmissionTime', 'submissionTime', 'created', 'reviewCreated',
                             'submissionDate', 'datePublished', 'createdAt', 'submission_date', 'createdDate'],
    'reviewTitle': ['reviewTitle', 'title', 'headline', 'reviewHeader', 'review_title'],
}

# Strings that appear on Walmart pages but are NOT review bodies.
IGNORE_REVIEW_TEXT = {
    'verified purchase',
    'seller verified purchase',
    'incentivized review',
    'review collected as part of a promotion',
    'promotion',
    'report',
    'helpful?',
}

# --------------------- Date normalization ---------------------

def normalize_date(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.strip()
    for fmt in ('%b %d, %Y', '%B %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except Exception:
            pass
    return s

def _coalesce(obj: dict, keys):
    for k in keys:
        if k in obj and obj[k] not in (None, ''):
            v = obj[k]
            if isinstance(v, dict) and 'ratingValue' in v and v['ratingValue'] not in (None, ''):
                return v['ratingValue']
            return v
    return None

def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None

# --------------------- Review extraction ---------------------

def _is_noise_reviewtext(txt: str) -> bool:
    if not isinstance(txt, str):
        return False
    t = txt.strip().lower()
    if not t:
        return True
    t = t.replace('\u00a0', ' ')
    if t in IGNORE_REVIEW_TEXT:
        return True
    # short label-like strings that contain the bad tokens
    if len(t) <= 40 and any(x in t for x in ['verified purchase', 'seller verified purchase', 'incentivized review']):
        return True
    return False

def _maybe_add_review(d: dict, out: list):
    review_text = _coalesce(d, KEY_CANDIDATES['reviewText'])
    if review_text is None:
        return

    if isinstance(review_text, str):
        review_text = htmllib.unescape(review_text)
        if _is_noise_reviewtext(review_text):
            return
        if not review_text.strip():
            return

    rating = _coalesce(d, KEY_CANDIDATES['rating'])
    sub_time = _coalesce(d, KEY_CANDIDATES['reviewSubmissionTime'])
    title = _coalesce(d, KEY_CANDIDATES['reviewTitle'])

    out.append({
        'rating': rating if rating is not None else '',
        'reviewText': htmllib.unescape(str(review_text)) if review_text is not None else '',
        'reviewSubmissionTime': normalize_date(str(sub_time)) if sub_time is not None else '',
        'reviewTitle': htmllib.unescape(str(title)) if title is not None else '',
    })

def _walk_json(o, out: list):
    if isinstance(o, dict):
        _maybe_add_review(o, out)
        for v in o.values():
            _walk_json(v, out)
    elif isinstance(o, list):
        for item in o:
            _walk_json(item, out)

def _extract_all_next_data(text: str):
    out = []
    for m in re.finditer(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                         text, flags=re.DOTALL | re.IGNORECASE):
        blob = htmllib.unescape(m.group(1))
        try:
            out.append(json.loads(blob))
        except Exception:
            continue
    return out

def _find_json_objects(raw: str):
    results = []
    key_regex = re.compile(r'(\"reviewText\"|\"reviewTitle\"|\"reviewSubmissionTime\"|\"datePublished\"|\"ratingValue\")')

    for m in key_regex.finditer(raw):
        start = raw.rfind('{', 0, m.start())
        if start == -1:
            continue
        depth = 0
        end = None
        for i in range(start, min(len(raw), start + 40000)):
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
                results.append(json.loads(frag))
            except Exception:
                continue
    return results

def extract_from_json(text: str):
    out = []

    # raw JSON
    try:
        data = json.loads(text)
        _walk_json(data, out)
    except Exception:
        pass

    # ALL Next blocks (multi-page)
    for nd in _extract_all_next_data(text):
        _walk_json(nd, out)

    # heuristic scan
    raw = htmllib.unescape(text)
    for obj in _find_json_objects(raw):
        _walk_json(obj, out)

    # de-dupe
    seen = set()
    deduped = []
    for r in out:
        rt = (r.get('reviewText', '') or '').strip()
        if not rt or _is_noise_reviewtext(rt):
            continue
        key = (rt[:220], r.get('reviewSubmissionTime', ''), str(r.get('rating', '')))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return deduped

def extract_reviews(text: str):
    return extract_from_json(text or '')

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
    'perfect','reliable','consistent','creamy','rich','smooth','best','favorite','yummy','recommend','recommended',
    'quick','easy','fresh','fast','crisp','crispy','value','affordable','pleased','satisfied','fantastic','outstanding',
    'perfectly','balanced','nice',
])

NEG_WORDS = set([
    'bad','worse','worst','bland','gross','greasy','soggy','stale','burnt','disappointing','disappointed','dislike',
    'hated','hate','hard','tough','rubbery','overcooked','undercooked','cold','salty','sweet',
    'bitter','sour','grainy','expensive','pricey','costly','missing','broken','dented','damaged','late','slow','poor',
    'terrible','awful','mediocre','meh','boring','lack','lacks','lacking','issue','issues','problem','problems','wrong',
    'empty','watery','thin','thick','runny','inedible','never','again','substitute',
])

# Shipping/service adjustment
SHIPPING_TERMS = {
    'shipping','ship','delivery','delivered','arrived','arrival','carrier','fedex','ups','usps',
    'customer service','support','refund','return','replacement','damaged','broken','missing','late','delay','delays'
}
SHIPPING_NEG_HINTS = {
    'terrible','awful','bad','late','delay','delays','damaged','broken','missing','no help','no support','customer service'
}

def normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.lower()
    s = re.sub(r'https?://\S+', ' ', s)
    s = s.replace('&amp;', '&')
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

def _has_shipping_issue(title: str, text: str) -> bool:
    t = normalize_text((title or '') + ' ' + (text or ''))
    if not t:
        return False
    has_term = any(term.replace(' ', '') in t.replace(' ', '') or term in t for term in SHIPPING_TERMS)
    if not has_term:
        return False
    has_neg = any(h in t for h in SHIPPING_NEG_HINTS) or 'shipping was' in t or 'delivery was' in t
    return has_neg

def _has_product_praise(text: str) -> bool:
    t = normalize_text(text or '')
    if not t:
        return False
    if 'great product' in t or 'great products' in t or 'product is great' in t:
        return True
    toks = token_filter(t.split())
    return sum(1 for w in toks if w in POS_WORDS) >= 2

def compute_sentiment(rows):
    enriched = []
    for r in rows:
        txt = r.get('reviewText', '') or ''
        title = r.get('reviewTitle', '') or ''

        ts = float(text_sentiment_score(txt))
        rating_val = r.get('rating', '')
        rating_num = _to_float(rating_val)
        rs = rating_score(rating_num if rating_num is not None else rating_val)

        combined = 0.6 * rs + 0.4 * ts

        # Force extremes per your rule
        if rating_num == 5:
            combined = 1.0
        elif rating_num == 1:
            combined = -1.0

        # Shipping vs product conflict -> neutralize (3–4 stars)
        shipping_conflict = (rating_num in (3, 4) and _has_shipping_issue(title, txt) and _has_product_praise(txt))
        if shipping_conflict:
            combined = 0.15  # neutral zone

        # Keep your clamps for low/high ratings
        if rating_num is not None and rating_num <= 2:
            combined = min(combined, 0.0)
        if rating_num is not None and rating_num >= 4:
            combined = max(combined, 0.3)

        # Label rules
        if rating_num is not None and rating_num >= 4:
            label = 'positive'
        elif rating_num is not None and rating_num <= 2:
            label = 'negative'
        else:
            if combined >= 0.3:
                label = 'positive'
            elif combined < 0.0:
                label = 'negative'
            else:
                label = 'neutral'

        if shipping_conflict:
            label = 'neutral'

        enriched.append({
            'rating': rating_val,
            'reviewText': txt,
            'reviewSubmissionTime': r.get('reviewSubmissionTime', ''),
            'reviewTitle': title,
            'text_score': round(ts, 3),
            'rating_score': round(rs, 3),
            'combined_score': round(combined, 3),
            'sentiment': label,
        })

    return enriched

# -------- Phrase extraction (replaces bigrams) --------

def extract_top_phrases(texts, top_n=25, ngram_min=3, ngram_max=4):
    generic = {'love','product','products','able','get','got','find','found','use','using','work','works','working','would','recommend'}
    counts = Counter()

    for txt in texts:
        t = normalize_text(txt)
        if not t:
            continue
        toks = [w for w in t.split() if w and w not in STOPWORDS]
        if len(toks) < ngram_min:
            continue

        for n in range(ngram_min, ngram_max + 1):
            for i in range(0, len(toks) - n + 1):
                gram = toks[i:i+n]
                if gram[0] in generic or gram[-1] in generic:
                    continue
                if all(w in generic for w in gram):
                    continue
                counts[' '.join(gram)] += 1

    # Keep only phrases that repeat
    filtered = [(p, c) for p, c in counts.items() if c >= 2]
    filtered.sort(key=lambda x: (-x[1], x[0]))
    return filtered[:top_n]

def extract_keywords_and_bigrams(texts, top_n_words=25, top_n_bigrams=25):
    """
    Backward-compatible name.
    Returns: (top_words, top_phrases)
    """
    all_tokens = []
    for txt in texts:
        t = normalize_text(txt)
        if not t:
            continue
        all_tokens.extend(token_filter(t.split()))

    top_words = Counter(all_tokens).most_common(top_n_words)
    top_phrases = extract_top_phrases(texts, top_n=top_n_bigrams)
    return top_words, top_phrases

# -------- Word cloud --------
from io import BytesIO

def render_wordcloud_bytes(freq_items, fig_size=(4.6, 3.2)):
    if not MATPLOTLIB_OK:
        return b''

    if not freq_items:
        fig, ax = plt.subplots(figsize=fig_size)
        ax.text(0.5, 0.5, 'No terms', ha='center', va='center', fontsize=12)
        ax.set_axis_off()
        bio = BytesIO()
        fig.savefig(bio, dpi=200, bbox_inches='tight', format='png')
        plt.close(fig)
        return bio.getvalue()

    random.seed(42)
    fig, ax = plt.subplots(figsize=fig_size)
    ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    occupied = []

    def place_word(text, font_size):
        for _ in range(180):
            x = random.uniform(0.10, 0.90)
            y = random.uniform(0.15, 0.85)
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
        size = 9 + int(18 * (cnt / max_cnt))
        if not place_word(token, size):
            ax.text(random.uniform(0.10, 0.90), random.uniform(0.15, 0.85), token,
                    fontsize=8, ha='center', va='center', alpha=0.55)

    bio = BytesIO()
    fig.savefig(bio, dpi=220, bbox_inches='tight', format='png')
    plt.close(fig)
    return bio.getvalue()
