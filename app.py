# -*- coding: utf-8 -*-
import time

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SORT_OPTIONS = {
    "銷量高到低": "sale/dc",
    "價格低到高": "prc/ac",
    "價格高到低": "prc/dc",
    "最新上架": "new/dc",
    "相關度": "rnk/dc",
}

st.set_page_config(page_title="PChome 商品價格分析", page_icon="🛒", layout="wide")
st.title("🛒 PChome 商品價格分析")


# ---------- 爬蟲 ----------
def fetch_products(keyword: str, pages: int, sort: str, delay: float, progress) -> pd.DataFrame:
    """依頁數抓取 PChome 搜尋結果,回傳整理後的 DataFrame"""
    frames = []
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"正在抓取第 {i}/{pages} 頁...")
        resp = requests.get(
            API_URL,
            params={"q": keyword, "page": i, "sort": sort},  # requests 會自動處理中文編碼
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        prods = resp.json().get("prods", [])
        if not prods:
            st.warning(f"第 {i} 頁沒有資料,已停止抓取。")
            break
        page_df = pd.DataFrame(prods)
        page_df["頁碼"] = i
        frames.append(page_df)
        if i < pages and delay > 0:
            time.sleep(delay)  # 拖延時間,避免請求過於頻繁
    progress.progress(1.0, text="抓取完成")

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    if not {"name", "price"}.issubset(raw.columns):
        return pd.DataFrame()

    df = raw[["name", "price", "頁碼"]].rename(columns={"name": "商品名稱", "price": "價格"})
    df["價格"] = pd.to_numeric(df["價格"], errors="coerce")
    df = df.dropna(subset=["商品名稱", "價格"]).reset_index(drop=True)
    df.insert(0, "序號", df.index + 1)
    return df


# ---------- 價格區間 ----------
def add_price_band(df: pd.DataFrame, n_bins: int) -> pd.DataFrame:
    df = df.copy()
    lo, hi = df["價格"].min(), df["價格"].max()
    if lo == hi:
        df["價格區間"] = f"{int(lo)}"
        return df
    n_bins = max(1, min(n_bins, df["價格"].nunique()))
    edges = np.linspace(lo, hi, n_bins + 1)
    labels = [f"{int(edges[k])}–{int(edges[k + 1])}" for k in range(n_bins)]
    df["價格區間"] = pd.cut(
        df["價格"], bins=edges, labels=labels, include_lowest=True, ordered=True
    )
    return df


def short(text: str, n: int = 18) -> str:
    return text if len(text) <= n else text[:n] + "…"


# ---------- 側邊欄:搜尋條件 ----------
with st.sidebar:
    st.header("搜尋條件")
    with st.form("search_form"):
        keyword = st.text_input("產品名稱", value="行動電源")
        pages = st.number_input("抓取頁數", min_value=1, max_value=20, value=3, step=1)
        sort_label = st.selectbox("排序方式", list(SORT_OPTIONS.keys()))
        delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.0, 0.5)
        submitted = st.form_submit_button("🔍 開始爬取", use_container_width=True)

if submitted:
    if not keyword.strip():
        st.error("請輸入產品名稱")
    else:
        bar = st.progress(0, text="準備中...")
        try:
            result = fetch_products(
                keyword.strip(), int(pages), SORT_OPTIONS[sort_label], delay, bar
            )
        except Exception as e:
            st.error(f"爬取失敗:{e}")
            result = pd.DataFrame()
        finally:
            bar.empty()
        st.session_state["df"] = result
        st.session_state["keyword"] = keyword.strip()

# ---------- 主畫面 ----------
df = st.session_state.get("df")

if df is None:
    st.info("👈 請在左側輸入產品名稱與頁數,再按「開始爬取」。")
    st.stop()
if df.empty:
    st.warning("沒有取得任何資料,請換個關鍵字或稍後再試。")
    st.stop()

kw = st.session_state.get("keyword", "")
mean_price = df["價格"].mean()

st.subheader(f"「{kw}」搜尋結果")
m1, m2, m3, m4 = st.columns(4)
m1.metric("商品數", f"{len(df):,}")
m2.metric("平均價格", f"{mean_price:,.0f}")
m3.metric("最高價格", f"{df['價格'].max():,.0f}")
m4.metric("最低價格", f"{df['價格'].min():,.0f}")

n_bins = st.slider("價格區間數量(用於圓餅圖與旭日圖)", 2, 8, 5)
dfb = add_price_band(df, n_bins)

tab_line, tab_pie, tab_sun, tab_data = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📋 資料表"])

with tab_line:
    fig = px.line(
        df,
        x="序號",
        y="價格",
        hover_name="商品名稱",
        markers=True,
        title=f"PChome 電商網站上「{kw}」售價",
    )
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
        annotation_position="top left",
    )
    fig.update_layout(xaxis_title="商品序號", yaxis_title="價格", height=500)
    st.plotly_chart(fig, use_container_width=True)

with tab_pie:
    counts = dfb.groupby("價格區間", observed=True).size().reset_index(name="商品數")
    counts["價格區間"] = counts["價格區間"].astype(str)
    fig = px.pie(
        counts,
        names="價格區間",
        values="商品數",
        hole=0.3,
        title=f"「{kw}」價格區間分布",
    )
    fig.update_traces(sort=False, textinfo="label+percent")
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

with tab_sun:
    show_items = st.checkbox("顯示商品層級", value=False)
    sun = dfb.copy()
    sun["價格區間"] = sun["價格區間"].astype(str)
    sun["頁碼"] = "第" + sun["頁碼"].astype(str) + "頁"
    sun["商品"] = sun["商品名稱"].map(short)
    path = ["頁碼", "價格區間"] + (["商品"] if show_items else [])
    title = f"「{kw}」頁碼 → 價格區間" + (" → 商品" if show_items else "")
    fig = px.sunburst(sun, path=path, title=title)
    fig.update_traces(textinfo="label+value")
    fig.update_layout(height=650)
    st.plotly_chart(fig, use_container_width=True)

with tab_data:
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ 下載 CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"PCHOME_{kw}.csv",
        mime="text/csv",
    )
