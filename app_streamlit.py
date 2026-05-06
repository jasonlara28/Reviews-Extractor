import streamlit as st
import pandas as pd
import requests
import re
import time

from reviews_core import (
    extract_reviews,
    compute_sentiment,
    extract_keywords_and_bigrams,
    render_wordcloud_bytes,
)

st.set_page_config(page_title='Walmart Reviews Explorer V2', layout='wide')

st.title('Walmart Reviews Explorer V2')
st.caption('Paste Walmart URL OR HTML/JSON to analyze reviews, sentiment, and word cloud.')

# ---------------- HELPERS ----------------

def extract_product_id(url):
    match = re.search(r'/ip/(\d+)', url)
    return match.group(1) if match else None


@st.cache_data
def fetch_reviews_pages(product_id, max_pages=5):
    all_html = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for page in range(1, max_pages + 1):
        url = f"https://www.walmart.com/reviews/product/{product_id}?page={page}"
        
        try:
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                break

            all_html.append(response.text)
            time.sleep(0.6)  # prevent getting blocked

        except Exception:
            break

    return "\n".join(all_html)


# ---------------- SIDEBAR ----------------

with st.sidebar:
    st.header("Input")

    mode = st.radio(
        "How do you want to provide data?",
        ["Use Walmart URL", "Paste HTML/JSON", "Upload file"],
        index=0
    )

    raw_text = ""

    if mode == "Use Walmart URL":
        url_input = st.text_input(
            "Paste Walmart product URL",
            placeholder="https://www.walmart.com/ip/14053192"
        )
        pages = st.slider("Number of pages", 1, 20, 5)

    elif mode == "Paste HTML/JSON":
        raw_text = st.text_area("Paste HTML/JSON here", height=260)

    else:
        uploaded_file = st.file_uploader(
            "Upload a .txt/.html/.json file",
            type=["txt", "html", "json"]
        )
        if uploaded_file is not None:
            raw_text = uploaded_file.getvalue().decode("utf-8", errors="replace")

    st.divider()

    # Filters
    min_rating = st.slider("Minimum rating", 1.0, 5.0, 1.0, 0.5)
    sentiment_filter = st.multiselect(
        "Sentiment",
        ["positive", "neutral", "negative"],
        default=["positive", "neutral", "negative"]
    )
    keyword = st.text_input("Contains keyword (optional)")

    run = st.button("Run Analysis", type="primary")

# ---------------- MAIN ----------------

if run:

    # --- Auto-fetch if using URL ---
    if mode == "Use Walmart URL":
        product_id = extract_product_id(url_input)

        if not product_id:
            st.error("Invalid Walmart URL")
            st.stop()

        with st.spinner("Fetching reviews automatically..."):
            raw_text = fetch_reviews_pages(product_id, pages)

    if not raw_text:
        st.error("No input data")
        st.stop()

    # --- Parse reviews ---
    with st.spinner("Parsing reviews..."):
        rows = extract_reviews(raw_text)

    if not rows:
        st.error("No reviews found")
        st.stop()

    df = pd.DataFrame(compute_sentiment(rows))

    # Clean rating column
    df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce")

    # --- Apply filters ---
    df = df[df["rating_num"] >= min_rating]
    df = df[df["sentiment"].isin(sentiment_filter)]

    if keyword:
        df = df[df["reviewText"].str.contains(keyword, case=False, na=False)]

    # ---------------- KPI ----------------

    col1, col2, col3 = st.columns(3)
    col1.metric("Reviews", len(df))
    col2.metric("Avg Rating", round(df["rating_num"].mean(), 2))
    col3.metric("Avg Sentiment", round(df["combined_score"].mean(), 2))

    colA, colB = st.columns(2)

    # ---------------- Charts ----------------

    with colA:
        st.subheader("Sentiment Distribution")
        st.bar_chart(df["sentiment"].value_counts())

        st.subheader("Ratings Distribution")
        st.bar_chart(df["rating_num"].value_counts().sort_index())

    # ---------------- Word Cloud ----------------

    with colB:
        st.subheader("Word Cloud")

        words, bigrams = extract_keywords_and_bigrams(df["reviewText"])
        wc_items = words[:60] + bigrams[:30]

        image_bytes = render_wordcloud_bytes(wc_items)

        if image_bytes:
            st.image(image_bytes, use_container_width=True)
        else:
            st.info("Word cloud unavailable")

    # ---------------- Keywords ----------------

    st.subheader("Top Keywords")
    st.dataframe(
        pd.DataFrame(words, columns=["word", "count"]).head(20),
        use_container_width=True
    )

    # ---------------- Reviews ----------------

    st.subheader("Reviews")
    st.dataframe(
        df[["rating", "sentiment", "reviewText"]],
        height=500,
        use_container_width=True
    )
