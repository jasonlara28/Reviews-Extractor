import streamlit as st
import pandas as pd
import requests
import time
import html as htmllib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from reviews_core import (
    extract_reviews,
    compute_sentiment,
    extract_keywords_and_bigrams,
    render_wordcloud_bytes,
)

st.set_page_config(page_title="Walmart Reviews Explorer V2", layout="wide")

st.title("Walmart Reviews Explorer V2")
st.caption("Use a Walmart *reviews* URL (recommended) or paste HTML/JSON to analyze reviews, sentiment, and keywords.")

# --------------------------
# Helpers
# --------------------------

def build_paged_url(base_url: str, page: int) -> str:
    """
    Takes a base reviews URL like:
      https://www.walmart.com/reviews/product/14053192?entryPoint=viewAllReviewsBottom
    and returns the same URL with page=<n> set correctly.
    Handles accidental '&amp;' by unescaping HTML first.
    """
    if not base_url:
        return base_url

    base_url = base_url.strip()
    base_url = htmllib.unescape(base_url)  # converts &amp; -> & if user pasted encoded text

    p = urlparse(base_url)
    qs = parse_qs(p.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)

    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))


def looks_blocked(html_text: str) -> bool:
    """
    Detect common bot/challenge pages Walmart returns.
    """
    if not html_text:
        return True
    low = html_text.lower()
    return ("robot or human" in low) or ("captcha" in low) or ("px-captcha" in low) or ("are you a robot" in low)


def fetch_reviews_html(reviews_url: str, max_pages: int, delay_s: float, debug: bool):
    """
    Fetch multiple review pages and return concatenated HTML plus block status.
    """
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    combined = []
    blocked = False
    debug_rows = []

    for page in range(1, max_pages + 1):
        url = build_paged_url(reviews_url, page)

        try:
            r = session.get(url, headers=headers, timeout=20)
            text = r.text or ""

            if debug:
                debug_rows.append({
                    "page": page,
                    "url": url,
                    "status": r.status_code,
                    "len": len(text),
                    "has_NEXT_DATA": "__NEXT_DATA__" in text,
                    "has_reviewText": "reviewText" in text,
                    "blocked_like": looks_blocked(text),
                    "first_120": text[:120].replace("\n", " ")
                })

            # hard stop if blocked/challenged
            if r.status_code != 200 or looks_blocked(text):
                blocked = True
                break

            combined.append(text)
            time.sleep(delay_s)

        except Exception as e:
            if debug:
                debug_rows.append({
                    "page": page,
                    "url": url,
                    "status": "EXCEPTION",
                    "len": 0,
                    "has_NEXT_DATA": False,
                    "has_reviewText": False,
                    "blocked_like": True,
                    "first_120": str(e)[:120]
                })
            blocked = True
            break

    return "\n".join(combined), blocked, debug_rows


# --------------------------
# Sidebar
# --------------------------
with st.sidebar:
    st.header("Input")

    mode = st.radio(
        "How do you want to provide data?",
        ["Use Walmart *reviews* URL (auto-fetch)", "Paste HTML/JSON", "Upload file"],
        index=0
    )

    raw_text = ""
    reviews_url = ""
    pages = 5

    if mode == "Use Walmart *reviews* URL (auto-fetch)":
        reviews_url = st.text_input(
            "Paste Walmart reviews URL",
            placeholder="https://www.walmart.com/reviews/product/14053192?entryPoint=viewAllReviewsBottom"
        )
        pages = st.slider("Number of pages to fetch", 1, 20, 5)
        delay_s = st.slider("Delay between pages (seconds)", 0.2, 2.0, 0.6, 0.1)
        debug = st.checkbox("Debug fetch output", value=False)
    elif mode == "Paste HTML/JSON":
        raw_text = st.text_area("Paste HTML/JSON here", height=260)
        delay_s = 0.6
        debug = False
    else:
        up = st.file_uploader("Upload a .txt/.html/.json file", type=["txt", "html", "json"])
        if up is not None:
            raw_text = up.getvalue().decode("utf-8", errors="replace")
        delay_s = 0.6
        debug = False

    st.divider()
    st.header("Filters")
    min_rating = st.slider("Minimum rating", 1.0, 5.0, 1.0, 0.5)
    sentiment_filter = st.multiselect("Sentiment", ["positive", "neutral", "negative"],
                                     default=["positive", "neutral", "negative"])
    keyword = st.text_input("Contains keyword (optional)")

    run = st.button("Run Analysis", type="primary")


# --------------------------
# Main
# --------------------------
if run:

    # 1) Get input text
    blocked = False
    debug_rows = []

    if mode == "Use Walmart *reviews* URL (auto-fetch)":
        if not reviews_url.strip():
            st.error("Please paste a Walmart reviews URL.")
            st.stop()

        with st.spinner("Fetching review pages..."):
            raw_text, blocked, debug_rows = fetch_reviews_html(reviews_url, pages, delay_s, debug)

        if debug and debug_rows:
            st.subheader("Debug (Fetch Results)")
            st.dataframe(pd.DataFrame(debug_rows), use_container_width=True, height=260)

        if blocked:
            st.error(
                "Walmart blocked the automatic fetch (the server received a 'Robot or human?' challenge page). "
                "✅ Best workaround: open the reviews page in your browser, right-click → **View Page Source**, "
                "copy everything, and use **Paste HTML/JSON** mode here."
            )
            st.stop()

    if not raw_text:
        st.error("No input data to process.")
        st.stop()

    # 2) Parse reviews
    with st.spinner("Parsing reviews..."):
        rows = extract_reviews(raw_text)

    if not rows:
        st.error(
            "No reviews were extracted. If you used auto-fetch, Walmart may have served a page without review data. "
            "Try the **Paste HTML/JSON** fallback using View Page Source."
        )
        st.stop()

    # 3) Sentiment + dataframe
    enriched = compute_sentiment(rows)
    df = pd.DataFrame(enriched)
    df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce")

    # 4) Apply filters
    mask = (df["rating_num"].fillna(0) >= float(min_rating)) & (df["sentiment"].isin(sentiment_filter))
    if keyword:
        mask = mask & df["reviewText"].astype(str).str.contains(keyword, case=False, na=False)
    dff = df[mask].copy()

    # 5) KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reviews (filtered)", f"{len(dff):,}")
    c2.metric("Reviews (total)", f"{len(df):,}")
    avg_rating = dff["rating_num"].mean() if len(dff) else df["rating_num"].mean()
    c3.metric("Avg rating", f"{avg_rating:.2f}" if pd.notna(avg_rating) else "—")
    c4.metric("Net sentiment (avg combined)", f"{dff['combined_score'].mean():.3f}" if len(dff) else f"{df['combined_score'].mean():.3f}")

    left, right = st.columns([1, 1])

    with left:
        st.subheader("Sentiment distribution")
        dist = dff["sentiment"].value_counts().reindex(["positive", "neutral", "negative"]).fillna(0)
        st.bar_chart(dist)

        st.subheader("Ratings distribution")
        rdist = dff["rating_num"].value_counts().sort_index()
        st.bar_chart(rdist)

    with right:
        st.subheader("Word cloud (filtered)")
        texts = dff["reviewText"].fillna("").tolist()
        top_words, top_bigrams = extract_keywords_and_bigrams(texts)
        wc_items = top_words[:60] + top_bigrams[:30]
        img_bytes = render_wordcloud_bytes(wc_items)
        if img_bytes:
            st.image(img_bytes, use_container_width=True)
        else:
            st.info("Word cloud unavailable (matplotlib not available).")

        with st.expander("Top keywords & bigrams"):
            colA, colB = st.columns(2)
            colA.write(pd.DataFrame(top_words, columns=["term", "count"]).head(25))
            colB.write(pd.DataFrame(top_bigrams, columns=["term", "count"]).head(25))

    st.subheader("Reviews")
    show_cols = ["rating", "sentiment", "combined_score", "reviewTitle", "reviewSubmissionTime", "reviewText"]
    st.dataframe(dff[show_cols], use_container_width=True, height=460)

    st.download_button(
        "Download filtered reviews (CSV)",
        dff[show_cols].to_csv(index=False).encode("utf-8"),
        file_name="reviews_filtered.csv",
        mime="text/csv"
    )

else:
    st.info("Choose an input method on the left, then click **Run Analysis**.")
