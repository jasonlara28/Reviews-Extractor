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

# ---- Custom CSS ----
st.markdown("""
<style>
    .card-row { display:flex; gap:12px; overflow-x:auto; padding:6px 2px 10px 2px; }
    .card { min-width: 320px; max-width: 320px; border:1px solid rgba(0,0,0,0.12); border-radius:14px; padding:12px; background:white; }
    .badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; }
    .badge.pos { background:#e8f7ee; color:#137a3a; }
    .badge.neu { background:#f1f3f5; color:#495057; }
    .badge.neg { background:#fdecec; color:#b02a37; }
    .small { color:#6c757d; font-size:12px; }
    .rtitle { font-weight:700; margin-top:6px; margin-bottom:6px; }
    .txt { font-size:13px; line-height:1.35; }
</style>
""", unsafe_allow_html=True)

# ---- Multi-page append (Undo removed) ----

if 'pages' not in st.session_state:
    st.session_state['pages'] = []

with st.sidebar:
    st.header('Input')
    mode = st.radio('How do you want to provide data?', ['Paste pages (append)', 'Upload file'], index=0)

    if mode == 'Paste pages (append)':
        raw_input = st.text_area('Paste page source HTML/JSON here', height=200, key='paste_area')
        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button('Add Page', use_container_width=True):
                if raw_input and raw_input.strip():
                    st.session_state['pages'].append(raw_input.strip())
                    st.success('Page ' + str(len(st.session_state['pages'])) + ' added!')
                else:
                    st.warning('Paste some content first.')
        with col_clear:
            if st.button('Clear All', use_container_width=True):
                st.session_state['pages'] = []
                st.info('All pages cleared.')

        st.caption(str(len(st.session_state['pages'])) + ' page(s) loaded')

        if st.session_state['pages']:
            with st.expander('Preview loaded pages'):
                for i, p in enumerate(st.session_state['pages']):
                    st.text('--- Page ' + str(i + 1) + ' (' + str(len(p)) + ' chars) ---')
                    preview = p[:300] + ('...' if len(p) > 300 else '')
                    st.text(preview)

        raw_text = chr(10).join(st.session_state['pages'])

    else:
        uploaded = st.file_uploader('Upload HTML/JSON file', type=['html', 'json', 'txt'])
        if uploaded:
            raw_text = uploaded.read().decode('utf-8', errors='replace')
        else:
            raw_text = ''

    st.divider()
    parse_clicked = st.button('Parse & Analyze', type='primary', use_container_width=True)


# ---- Main area ----
if parse_clicked:
    if not raw_text or not raw_text.strip():
        st.warning('No content to parse. Add at least one page or upload a file.')
    else:
        with st.spinner('Parsing reviews...'):
            rows = extract_reviews(raw_text or '')

        if not rows:
            st.error('No reviews found. Make sure you are pasting the full page source (View Page Source).')
        else:
            with st.spinner('Computing sentiment...'):
                enriched = compute_sentiment(rows)

            df = pd.DataFrame(enriched)

            # ---- KPI Metrics ----
            total = len(enriched)
            avg_rating = df['rating'].dropna().mean()
            low_star = df[df['rating'].apply(lambda x: x is not None and float(x) <= 2.0)]
            low_pct = (len(low_star) / total * 100) if total > 0 else 0

            kpi1, kpi2, kpi3 = st.columns(3)
            with kpi1:
                st.metric('Total Reviews', total)
            with kpi2:
                rating_display = str(round(avg_rating, 1)) + ' stars' if pd.notna(avg_rating) else 'N/A'
                st.metric('Avg Rating', rating_display)
            with kpi3:
                st.metric('% Low Star (1-2)', str(round(low_pct, 1)) + '%')

            st.divider()

            # ---- Keywords & Word Cloud ----
            all_texts = [r.get('reviewText', '') for r in enriched if r.get('reviewText')]
            top_words, top_phrases = extract_keywords_and_bigrams(all_texts)

            # Word Cloud
            if top_words:
                st.subheader('Word Cloud')
                wc_bytes = render_wordcloud_bytes(top_words)
                if wc_bytes:
                    st.image(wc_bytes, use_container_width=True)
                else:
                    st.caption('Word cloud could not be generated (matplotlib or wordcloud not available).')

            # Top Keywords and Top Phrases side by side
            col_kw, col_ph = st.columns(2)
            with col_kw:
                st.subheader('Top Keywords')
                if top_words:
                    kw_df = pd.DataFrame(top_words, columns=['Keyword', 'Count'])
                    st.dataframe(kw_df, use_container_width=True, hide_index=True)
                else:
                    st.caption('No keywords extracted.')
            with col_ph:
                st.subheader('Top Phrases')
                if top_phrases:
                    ph_df = pd.DataFrame(top_phrases, columns=['Phrase', 'Count'])
                    st.dataframe(ph_df, use_container_width=True, hide_index=True)
                else:
                    st.caption('No phrases extracted.')

            st.divider()

            # ---- Review Cards ----
            st.subheader('Individual Reviews')

            if enriched:
                cards_html = '<div class="card-row">'
                for r in enriched:
                    label = r.get('sentiment_label', 'neutral')
                    if label == 'positive':
                        badge_class = 'pos'
                    elif label == 'negative':
                        badge_class = 'neg'
                    else:
                        badge_class = 'neu'
                    badge_text = label.capitalize()
                    rating = r.get('rating', '')
                    if rating is not None:
                        try:
                            rating_display = str(int(float(rating))) + ' stars'
                        except Exception:
                            rating_display = 'N/A'
                    else:
                        rating_display = 'N/A'
                    title = r.get('reviewTitle', '') or ''
                    text = r.get('reviewText', '') or ''
                    date = r.get('reviewSubmissionTime', '') or ''
                    shipping_flag = ' [shipping]' if r.get('shipping_issue') else ''

                    if len(text) > 250:
                        display_text = text[:250].rsplit(' ', 1)[0] + '...'
                    else:
                        display_text = text

                    cards_html += (
                        '<div class="card">'
                        + '<span class="badge ' + badge_class + '">' + badge_text + '</span>'
                        + '<span class="small" style="float:right;">' + rating_display + shipping_flag + '</span>'
                        + '<div class="rtitle">' + title + '</div>'
                        + '<div class="txt">' + display_text + '</div>'
                        + '<div class="small" style="margin-top:6px;">' + date + '</div>'
                        + '</div>'
                    )
                cards_html += '</div>'
                st.markdown(cards_html, unsafe_allow_html=True)

            st.divider()

            # ---- CSV Export ----
            st.subheader('Export')
            export_df = pd.DataFrame(enriched)
            csv_data = export_df.to_csv(index=False)
            st.download_button(
                label='Download CSV',
                data=csv_data,
                file_name='walmart_reviews_export.csv',
                mime='text/csv',
            )

else:
    st.info('Add one or more pages on the left, then click **Parse & Analyze**.')
