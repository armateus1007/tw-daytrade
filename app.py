import pandas as pd
import streamlit as st

from analyze import decide, features, news_bias, us_bias
from fetch import bundle, refresh_company_map

st.set_page_config(page_title="自用台股分析", layout="wide")
st.title("自用隔日多空分析")
st.caption("純分析：已公告價量、大盤、台指期、美股、三大法人、融資融券、當沖比、新聞／公告。不計算張數與金額。")

with st.sidebar:
    st.header("選項")
    can_short_default = st.checkbox("分析時考慮放空", value=True)
    if st.button("更新上市上櫃名單"):
        n = refresh_company_map()
        st.success(f"寫入 {n} 筆")

q = st.text_input("股票代碼或名稱", placeholder="2330 或 台積電")
go = st.button("分析", type="primary")

if go and q.strip():
    with st.spinner("抓台股、美股、新聞中…"):
        try:
            data = bundle(q.strip())
        except Exception as e:
            st.error(str(e))
            st.stop()

    info = data["info"]
    tw: pd.DataFrame = data["tw"]
    us: pd.DataFrame = data["us"]
    news = data["news"]
    feat = features(tw)
    ub = us_bias(us)
    nb = news_bias(news)
    flags = data.get("flags") or {}
    flags["market"] = info.get("market")
    can_short = bool(can_short_default) and not flags.get("short_paused") and not flags.get("punish")
    decision = decide(
        feat,
        ub,
        can_short=can_short,
        flags=flags,
        index=data.get("index") or {},
        tx=data.get("tx") or {},
        news=nb,
        inst=data.get("inst") or {},
        margin=data.get("margin") or {},
        daytrade=data.get("daytrade") or {},
    )

    st.subheader(f"{info['code']} {info['name']}（{info['market']}）")
    tags = []
    if flags.get("punish"):
        tags.append("處置股")
    if flags.get("notice"):
        tags.append("注意股")
    if flags.get("in_daytrade_list") is True:
        tags.append("在上市當沖名單")
    elif flags.get("in_daytrade_list") is False:
        tags.append("未在上市當沖名單")
    if flags.get("short_paused"):
        tags.append("可能暫停先賣後買")
    if tags:
        st.write("／".join(tags))
    for n in flags.get("raw_note") or []:
        st.caption(n)
    c1, c2, c3 = st.columns(3)
    c1.metric("方向", decision["side"])
    c2.metric("分數", str(decision.get("score", "-")))
    if feat:
        c3.metric("收盤", f"{feat['close']:.2f}", f"{feat['chg_pct']:+.2f}%")

    st.write("**參考價位（不是下單金額）**")
    if decision["side"] in ("隔日偏多", "隔日偏空") and decision.get("entry"):
        st.write(
            f"- 參考觀察價：{decision['entry']:.2f}\n"
            f"- 參考停損（收盤±1.5%）：{decision['stop']:.2f}\n"
            f"- 參考停利（約 1.8R）：{decision['target']:.2f}"
        )
    else:
        st.info("隔日觀望／禁止，不給進出場建議")

    idx = data.get("index") or {}
    tx = data.get("tx") or {}
    m1, m2, m3 = st.columns(3)
    m1.metric("大盤 ^TWII", f"{idx.get('last') or '-'}", f"{idx.get('chg_pct') or 0:+.2f}%")
    if tx.get("ok"):
        m2.metric("台指期近月", f"{tx.get('last')}", f"{(tx.get('chg_pct') or 0):+.2f}%")
    else:
        m2.metric("台指期近月", "抓不到", tx.get("note") or "")
    m3.metric("新聞標題", nb.get("label", ""), f"分數 {nb.get('score', 0)}")

    inst = data.get("inst") or {}
    margin = data.get("margin") or {}
    daytrade = data.get("daytrade") or {}
    k1, k2, k3 = st.columns(3)
    if inst.get("ok"):
        k1.metric("三大法人合計（股）", f"{inst.get('total') or 0:,.0f}")
    else:
        k1.metric("三大法人", inst.get("note") or "無")
    if margin.get("ok"):
        k2.metric("融資餘額（張）", f"{margin.get('margin_bal') or '-'}")
    else:
        k2.metric("融資融券", margin.get("note") or "無")
    if daytrade.get("ratio") is not None:
        k3.metric("當沖比", f"{daytrade['ratio']*100:.1f}%")
    else:
        k3.metric("當沖比", daytrade.get("note") or "無")

    side = decision.get("side") or ""
    if side == "隔日偏多":
        st.write("**做多原因**")
        rows = decision.get("why_long") or decision.get("reason") or ["分數偏向多方"]
    elif side == "隔日偏空":
        st.write("**做空原因**")
        rows = decision.get("why_short") or decision.get("reason") or ["分數偏向空方"]
    else:
        st.write("**不做原因**")
        rows = decision.get("why_none") or decision.get("reason") or ["訊號不足或有限制"]
    for r in rows:
        st.write(f"- {r}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.write("**台股價量（最近）**")
        if tw.empty:
            st.warning("日線抓不到。先按側欄更新名單，上櫃改走櫃買／Yahoo 備援。")
        else:
            show = tw.tail(10)[
                [c for c in ["date", "open", "high", "low", "close", "volume_lot"] if c in tw.columns]
            ]
            st.dataframe(show, use_container_width=True, hide_index=True)
            if feat:
                st.caption(
                    f"MA5={feat['ma5']:.2f}　MA20={feat['ma20']:.2f}　"
                    f"均量={feat['vol20']:.0f}張　均振幅={feat['amp20']:.1f}%"
                )
    with col_b:
        st.write("**美股／指數（已公布最近收盤相對前一日）**")
        if us.empty:
            st.warning("Yahoo 美股抓不到，可能是網路或代號問題。")
        else:
            st.dataframe(us, use_container_width=True, hide_index=True)
            st.caption(f"{ub['label']}（平均 {ub['avg']:+.2f}%）")

    st.write("**公開資訊觀測站／重大訊息（可公開的法人可見公告，不是券商研報原文）**")
    mops = data.get("mops") or []
    if not mops:
        st.caption("沒有對到此公司的即時重大訊息。券商「投資報告全文」多半要付費，這裡改抓官方公告。")
    for m in mops:
        st.markdown(f"**{m.get('title','')}**")
        if m.get("body"):
            st.write(m["body"][:1200])

    st.write("**新聞標題與可抓到的內文摘要**")
    if not news:
        st.caption("沒有抓到新聞。")
    for n in news:
        title = n["title"]
        link = n["link"]
        st.markdown(f"- [{title}]({link})")
        text = n.get("body") or n.get("summary") or ""
        if text:
            st.caption(text[:500])

st.divider()
st.caption("本站只做多空與理由分析，不計算本金、張數、金額。")
