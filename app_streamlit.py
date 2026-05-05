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
st.caption('Paste Walmart.com review HTML/JSON, explore reviews, sentiment, and a word cloud.')

with st.sidebar:
    st.header('Input')
    mode = st.radio('How do you want to provide data?', ['Paste text', 'Upload file'], index=0)
    raw_text = ''
    if mode == 'Paste text':
        raw_text = st.text_area('Paste HTML/JSON here', height=260)
    else:
        up = st.file_uploader('Upload a .txt/.html/.json file', type=['txt','html','json'])
        if up is not None:
            raw_text = up.getvalue().decode('utf-8', errors='replace')

    st.divider()
    st.header('Filters')
    min_rating = st.slider('Minimum rating', 1.0, 5.0, 1.0, 0.5)
    sentiment_filter = st.multiselect('Sentiment', ['positive','neutral','negative'], default=['positive','neutral','negative'])
    keyword = st.text_input('Contains keyword (optional)')

    parse_clicked = st.button('Parse & Analyze', type='primary')

if parse_clicked:
    with st.spinner('Parsing reviews…'):
        rows = extract_reviews(raw_text or '')

    if not rows:
        st.error('No reviews found in the input. Try pasting a larger chunk of the page (including <script> blocks).')
        st.stop()

    enriched = compute_sentiment(rows)
    df = pd.DataFrame(enriched)

    # clean rating
    df['rating_num'] = pd.to_numeric(df['rating'], errors='coerce')

    # apply filters
    mask = (df['rating_num'].fillna(0) >= float(min_rating)) & (df['sentiment'].isin(sentiment_filter))
    if keyword:
        mask = mask & df['reviewText'].str.contains(keyword, case=False, na=False)
    dff = df[mask].copy()

    # --- top metrics ---
    c1,c2,c3,c4 = st.columns(4)
    c1.metric('Reviews (filtered)', f"{len(dff):,}")
    c2.metric('Reviews (total)', f"{len(df):,}")
    avg_rating = dff['rating_num'].mean() if len(dff) else df['rating_num'].mean()
    c3.metric('Avg rating', f"{avg_rating:.2f}" if pd.notna(avg_rating) else '—')
    c4.metric('Net sentiment (avg combined)', f"{dff['combined_score'].mean():.3f}" if len(dff) else f"{df['combined_score'].mean():.3f}")

    left,right = st.columns([1,1])

    with left:
        st.subheader('Sentiment distribution')
        dist = dff['sentiment'].value_counts().reindex(['positive','neutral','negative']).fillna(0)
        st.bar_chart(dist)

        st.subheader('Ratings distribution')
        rdist = dff['rating_num'].value_counts().sort_index()
        st.bar_chart(rdist)

    with right:
        st.subheader('Word cloud (filtered)')
        texts = (dff['reviewText'].fillna('')).tolist()
        top_words, top_bigrams = extract_keywords_and_bigrams(texts)
        wc_items = top_words[:60] + top_bigrams[:30]
        img_bytes = render_wordcloud_bytes(wc_items)
        if img_bytes:
            st.image(img_bytes, use_container_width=True)
        else:
            st.info('Matplotlib is not available in this environment; word cloud rendering is disabled.')

        with st.expander('Top keywords & bigrams'):
            colA, colB = st.columns(2)
            colA.write(pd.DataFrame(top_words, columns=['term','count']).head(25))
            colB.write(pd.DataFrame(top_bigrams, columns=['term','count']).head(25))

    st.subheader('Reviews')
    show_cols = ['rating','sentiment','combined_score','reviewTitle','reviewSubmissionTime','reviewText']
    st.dataframe(dff[show_cols], use_container_width=True, height=420)

    st.download_button(
        'Download filtered reviews (CSV)',
        dff[show_cols].to_csv(index=False).encode('utf-8'),
        file_name='reviews_filtered.csv',
        mime='text/csv'
    )

else:
    st.info('Add input on the left, then click **Parse & Analyze**.')
