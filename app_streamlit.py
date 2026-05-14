import streamlit as st
import pandas as pd

from reviews_core import (
    extract_reviews,
    compute_sentiment,
    extract_keywords_and_bigrams,
    render_wordcloud_bytes,
)

st.set_page_config(page_title='Walmart Reviews Explorer', layout='wide')

st.title('Walmart Reviews Explorer')
st.caption('Paste Walmart.com review HTML/JSON. Add multiple pages (View Page Source) before parsing.')

# Multi-page append (Undo removed)
if 'pages' not in st.session_state:
    st.session_state['pages'] = []

with st.sidebar:
    st.header('Input')
    mode = st.radio('How do you want to provide data?', ['Paste pages (append)', 'Upload file'], index=0)

    raw_text = ''

    if mode == 'Paste pages (append)':
        new_text = st.text_area('Paste ONE page source (HTML/JSON) here', height=200)
        col_add, col_clear = st.columns(2)
        with col_add:
            add_clicked = st.button('Add page')
        with col_clear:
            clear_clicked = st.button('Clear all')

        if add_clicked and (new_text or '').strip():
            st.session_state['pages'].append(new_text)

        if clear_clicked:
            st.session_state['pages'] = []

        st.caption(f"Pages added: **{len(st.session_state['pages'])}**")
        if st.session_state['pages']:
            preview = st.session_state['pages'][-1]
            st.text_area('Last page preview (read-only)', preview[:2000], height=120, disabled=True)

        raw_text = "\n\n".join(st.session_state['pages'])

    else:
        up = st.file_uploader('Upload a .txt/.html/.json file', type=['txt','html','json'])
        if up is not None:
            raw_text = up.getvalue().decode('utf-8', errors='replace')

    st.divider()
    parse_clicked = st.button('Parse & Analyze', type='primary')

if parse_clicked:
    with st.spinner('Parsing reviews…'):
        rows = extract_reviews(raw_text or '')

    if not rows:
        st.error('No reviews found. Tip: Use View Page Source on each review page and add multiple pages before parsing.')
        st.stop()

    enriched = compute_sentiment(rows)
    df = pd.DataFrame(enriched)
    df['rating_num'] = pd.to_numeric(df['rating'], errors='coerce')

    total_reviews = len(df)
    avg_rating = df['rating_num'].mean() if total_reviews else None
    net_sentiment = df['combined_score'].mean() if total_reviews else None
    low_star = int(((df['rating_num'] <= 2) & (df['rating_num'].notna())).sum())
    low_star_pct = (low_star / total_reviews) if total_reviews else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric('Total Reviews', f"{total_reviews:,}")
    k2.metric('Average Rating', f"{avg_rating:.2f}" if avg_rating == avg_rating else '—')
    k3.metric('Net Sentiment', f"{net_sentiment:.3f}" if net_sentiment == net_sentiment else '—')
    k4.metric('1–2 Star %', f"{low_star_pct:.0%}")

    st.divider()

    left, right = st.columns([1, 1])
    texts = df['reviewText'].fillna('').tolist()
    top_words, top_phrases = extract_keywords_and_bigrams(texts, top_n_words=25, top_n_bigrams=25)

    with left:
        st.subheader('Word cloud (compact, top 25 words)')
        wc_bytes = render_wordcloud_bytes(top_words[:25], fig_size=(4.6, 3.2))
        if wc_bytes:
            st.image(wc_bytes, width=360)
        else:
            st.info('Word cloud unavailable (matplotlib not available).')

    with right:
        st.subheader('Top keywords & phrases')
        c1, c2 = st.columns(2)
        c1.write(pd.DataFrame(top_words, columns=['keyword','count']))
        c2.write(pd.DataFrame(top_phrases, columns=['phrase','count']))

    st.divider()
    st.subheader('Review cards')

    st.markdown("""<style>
.card-row { display:flex; gap:12px; overflow-x:auto; padding:6px 2px 10px 2px; }
.card { min-width: 320px; max-width: 320px; border:1px solid rgba(0,0,0,0.12); border-radius:14px; padding:12px; background:white; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.badge.pos { background:#e8f7ee; color:#137a3a; }
.badge.neu { background:#f1f3f5; color:#495057; }
.badge.neg { background:#fdecec; color:#b02a37; }
.small { color:#6c757d; font-size:12px; }
.title { font-weight:700; margin-top:6px; margin-bottom:6px; }
.txt { font-size:13px; line-height:1.35; }
</style>""", unsafe_allow_html=True)

    df_cards = df.copy()
    df_cards['date_sort'] = pd.to_datetime(df_cards['reviewSubmissionTime'], errors='coerce')
    df_cards = df_cards.sort_values('date_sort', ascending=False, na_position='last')

    cards_html = ['<div class="card-row">']
    for _, r in df_cards.head(40).iterrows():
        rating = r.get('rating','')
        sent = r.get('sentiment','neutral')
        badge_class = 'neu'
        if sent == 'positive': badge_class = 'pos'
        if sent == 'negative': badge_class = 'neg'
        title = (r.get('reviewTitle','') or '').strip() or '(No title)'
        date = (r.get('reviewSubmissionTime','') or '').strip()
        text = (r.get('reviewText','') or '').strip()
        short = text if len(text) <= 220 else (text[:220] + '…')
        cs = r.get('combined_score','')

        cards_html.append(
            f'<div class="card">'
            f'<div><span class="badge {badge_class}">{sent.upper()}</span> '
            f'<span class="small">⭐ {rating} • score {cs}</span></div>'
            f'<div class="title">{title}</div>'
            f'<div class="small">{date}</div>'
            f'<div class="txt">{short}</div>'
            f'</div>'
        )

    cards_html.append('</div>')
    st.markdown(''.join(cards_html), unsafe_allow_html=True)

    st.divider()
    st.subheader('Raw review table')

    show_cols = ['rating','sentiment','combined_score','text_score','rating_score','reviewTitle','reviewSubmissionTime','reviewText']
    st.dataframe(df[show_cols], use_container_width=True, height=520)

    st.download_button(
        'Download reviews (CSV)',
        df[show_cols].to_csv(index=False).encode('utf-8'),
        file_name='reviews_with_sentiment.csv',
        mime='text/csv'
    )

else:
    st.info('Add one or more pages on the left, then click **Parse & Analyze**.')
