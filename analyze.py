from __future__ import annotations

import math

import pandas as pd


def _amp(row) -> float:
    if row["open"] and row["open"] != 0:
        return (row["high"] - row["low"]) / row["open"] * 100
    return float("nan")


def features(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 6:
        return {}
    d = df.copy()
    d["amp"] = d.apply(_amp, axis=1)
    last = d.iloc[-1]
    prev = d.iloc[-2]
    ma5 = d["close"].tail(5).mean()
    ma20 = d["close"].tail(20).mean() if len(d) >= 20 else d["close"].mean()
    vol20 = d["volume_lot"].tail(20).mean()
    amp20 = d["amp"].tail(20).mean()
    return {
        "date": last["date"],
        "close": float(last["close"]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "prev_close": float(prev["close"]),
        "chg_pct": float((last["close"] / prev["close"] - 1) * 100),
        "volume_lot": float(last["volume_lot"]),
        "vol20": float(vol20),
        "vol_ratio": float(last["volume_lot"] / vol20) if vol20 else 0.0,
        "amp": float(last["amp"]),
        "amp20": float(amp20) if pd.notna(amp20) else 0.0,
        "ma5": float(ma5),
        "ma20": float(ma20),
        "above_ma5": bool(last["close"] > ma5),
        "above_ma20": bool(last["close"] > ma20),
    }


def us_bias(us: pd.DataFrame) -> dict:
    if us is None or us.empty:
        return {"avg": 0.0, "label": "無美股資料"}
    # 隔日判斷以美股大盤／費半權重較高
    prefer = us[us["ticker"].isin(["QQQ", "^IXIC", "^GSPC", "SOXX", "NVDA"])]
    use = prefer if not prefer.empty else us
    avg = float(use["chg_pct"].mean())
    if avg >= 0.8:
        label = "美股夜盤偏多"
    elif avg <= -0.8:
        label = "美股夜盤偏空"
    else:
        label = "美股夜盤中性"
    return {"avg": avg, "label": label}


BULL_KW = ("降息", "升評", "利多", "創新高", "突破", "強勁", "rally", "rate cut", "beat", "surge")
BEAR_KW = ("升息", "關稅", "戰爭", "制裁", "衰退", "利空", "降評", "selloff", "tariff", "war", "recession", "crash")


def news_bias(news: list[dict]) -> dict:
    score = 0
    hits = []
    for it in news or []:
        raw = " ".join(
            [
                str(it.get("title") or ""),
                str(it.get("summary") or ""),
                str(it.get("body") or ""),
            ]
        )
        t = raw.lower()
        for k in BULL_KW:
            if k.lower() in t or k in raw:
                score += 1
                hits.append(f"偏多字：{raw[:60]}")
                break
        else:
            for k in BEAR_KW:
                if k.lower() in t or k in raw:
                    score -= 1
                    hits.append(f"偏空字：{raw[:60]}")
                    break
    if score >= 2:
        label = "新聞標題偏多"
    elif score <= -2:
        label = "新聞標題偏空"
    else:
        label = "新聞標題中性"
    return {"score": score, "label": label, "hits": hits[:6]}


def decide(
    feat: dict,
    us: dict,
    can_short: bool = True,
    flags: dict | None = None,
    index: dict | None = None,
    tx: dict | None = None,
    news: dict | None = None,
    inst: dict | None = None,
    margin: dict | None = None,
    daytrade: dict | None = None,
) -> dict:
    """用已公告資料做隔日偏向。不是預測保證。"""
    reasons = []
    why_long: list[str] = []
    why_short: list[str] = []
    why_none: list[str] = []
    flags = flags or {}
    index = index or {}
    tx = tx or {}
    inst = inst or {}
    margin = margin or {}
    daytrade = daytrade or {}
    news = news or {"score": 0, "label": "新聞標題中性", "hits": []}

    def add(msg: str, side: str | None = None):
        reasons.append(msg)
        if side == "long":
            why_long.append(msg)
        elif side == "short":
            why_short.append(msg)
        elif side == "none":
            why_none.append(msg)
    if flags.get("punish"):
        return {
            "side": "禁止",
            "reason": ["處置股，當沖風險與撮合限制高，不給單"],
            "why_long": [],
            "why_short": [],
            "why_none": ["處置股，分盤撮合／預收款券，不建議隔日當沖"],
            "entry": None,
            "stop": None,
            "target": None,
        }
    if flags.get("notice"):
        add("注意股：可做但降風險，部位應更小", "none")
    if flags.get("in_daytrade_list") is False and flags.get("market") == "TW":
        return {
            "side": "禁止",
            "reason": ["未出現在上市現股當沖標的名單"],
            "why_long": [],
            "why_short": [],
            "why_none": ["未出現在上市現股當沖標的名單"],
            "entry": None,
            "stop": None,
            "target": None,
        }
    if flags.get("in_daytrade_list") is False:
        add("未在上市當沖名單（上櫃請自行用券商畫面確認可否當沖）", "none")
    if flags.get("short_paused"):
        can_short = False
        add("名單註記可能暫停先賣後買，不建議放空", "none")
    if not feat:
        return {
            "side": "禁止",
            "reason": reasons + ["資料不足"],
            "why_long": why_long,
            "why_short": why_short,
            "why_none": why_none + ["價量資料不足"],
            "entry": None,
            "stop": None,
            "target": None,
        }

    if feat["vol20"] < 2000:
        return {
            "side": "禁止",
            "reason": [f"近20日均量 {feat['vol20']:.0f} 張，流動性偏弱"],
            "why_long": [],
            "why_short": [],
            "why_none": [f"近20日均量 {feat['vol20']:.0f} 張，進出容易滑價"],
            "entry": None,
            "stop": None,
            "target": None,
        }
    if feat["amp20"] < 2.0:
        add(f"近20日均振幅 {feat['amp20']:.1f}% < 2%，當沖空間可能不夠付成本", "none")

    score = 0
    if feat["above_ma5"]:
        score += 1
        add("個股收盤在 MA5 上，短線結構偏多", "long")
    else:
        score -= 1
        add("個股收盤在 MA5 下，短線結構偏空", "short")
    if feat["above_ma20"]:
        score += 1
        add("個股收盤在 MA20 上，中短線仍偏多", "long")
    else:
        score -= 1
        add("個股收盤在 MA20 下，中短線偏空", "short")
    if feat["vol_ratio"] >= 1.3:
        score += 1
        add(f"個股量比 {feat['vol_ratio']:.2f} 放大，有人參與", "long")

    twii = index.get("chg_pct")
    if twii is not None:
        if twii >= 0.6:
            score += 1
            add(f"大盤加權 {twii:+.2f}%，市場風險偏好升", "long")
        elif twii <= -0.6:
            score -= 1
            add(f"大盤加權 {twii:+.2f}%，市場風險偏好降", "short")
        else:
            add(f"大盤加權 {twii:+.2f}%（中性）")

    tx_chg = tx.get("chg_pct")
    if tx.get("ok") and tx_chg is not None:
        if tx_chg >= 0.4:
            score += 1
            add(f"台指期近月 {tx_chg:+.2f}%，指數期貨偏多", "long")
        elif tx_chg <= -0.4:
            score -= 1
            add(f"台指期近月 {tx_chg:+.2f}%，指數期貨偏空", "short")
        else:
            add(f"台指期近月 {tx_chg:+.2f}%（中性）")
    elif tx.get("note"):
        add(tx["note"])

    if us["avg"] >= 0.8:
        score += 1
        add(us["label"] + f"（{us['avg']:+.2f}%），隔日台股常跟漲", "long")
    elif us["avg"] <= -0.8:
        score -= 1
        add(us["label"] + f"（{us['avg']:+.2f}%），隔日台股常跟跌", "short")
    else:
        add(us["label"] + f"（{us['avg']:+.2f}%）")

    if inst.get("ok") and inst.get("total") is not None:
        tot = inst["total"]
        if tot > 0:
            score += 1
            add(
                f"三大法人買超 {tot:,.0f} 股（外資 {inst.get('foreign') or 0:,.0f}／投信 {inst.get('trust') or 0:,.0f}／自營 {inst.get('dealer') or 0:,.0f}）",
                "long",
            )
        elif tot < 0:
            score -= 1
            add(
                f"三大法人賣超 {tot:,.0f} 股（外資 {inst.get('foreign') or 0:,.0f}／投信 {inst.get('trust') or 0:,.0f}／自營 {inst.get('dealer') or 0:,.0f}）",
                "short",
            )
        else:
            add("三大法人合計接近平盤")
    elif inst.get("note"):
        add(inst["note"])

    if margin.get("ok") and margin.get("margin_chg") is not None:
        chg = margin["margin_chg"]
        if chg > 0:
            add(f"融資餘額增加（餘額 {margin.get('margin_bal')}），短線追價資金進場，波動可能加大", "none")
        elif chg < 0:
            add(f"融資餘額減少（餘額 {margin.get('margin_bal')}），槓桿資金退出")

    ratio = daytrade.get("ratio")
    if ratio is not None:
        pct = ratio * 100
        if pct >= 50:
            add(f"當沖比約 {pct:.1f}%，短線籌碼過熱，隔日方向容易反覆", "none")
        elif pct >= 30:
            add(f"當沖比約 {pct:.1f}%，短線活躍但未極端")
        else:
            add(f"當沖比約 {pct:.1f}%，隔夜籌碼相對穩")
    elif daytrade.get("note"):
        add(daytrade["note"])

    if news.get("score", 0) >= 2:
        score += 1
        add(news["label"] + "（標題／內文關鍵字）", "long")
    elif news.get("score", 0) <= -2:
        score -= 1
        add(news["label"] + "（標題／內文關鍵字）", "short")
    else:
        add(news.get("label") or "新聞中性")
    for h in news.get("hits") or []:
        add(h)

    close = feat["close"]
    low = feat["low"]
    high = feat["high"]
    prev = feat["prev_close"]
    # 隔日計畫停損用收盤±1.5%，避免用當日極值把高價股算成 0 張
    band = close * 0.015

    if score >= 2:
        side = "隔日偏多"
        entry = close
        stop = close - band
        risk = entry - stop
        target = entry + risk * 1.8
    elif score <= -2 and can_short:
        side = "隔日偏空"
        entry = close
        stop = close + band
        risk = stop - entry
        target = entry - risk * 1.8
    else:
        side = "隔日觀望"
        entry = close
        stop = None
        target = None
        add("大盤／期貨／美股／法人／新聞沒有同向，不給單", "none")

    if side == "隔日偏空" and not can_short:
        side = "隔日觀望"
        add("此檔未確認可先賣後買，不建議放空", "none")

    if side == "隔日偏多" and not why_none:
        why_none.append("若開盤跳空過多或量縮，仍應不做")
    if side == "隔日偏空" and not why_none:
        why_none.append("若開盤強勢反彈或無法先賣後買，應不做")
    return {
        "side": side,
        "score": score,
        "reason": reasons,
        "why_long": why_long,
        "why_short": why_short,
        "why_none": why_none,
        "entry": entry,
        "stop": stop,
        "target": target,
        "ref": prev,
    }


def position(
    side: str,
    entry: float | None,
    stop: float | None,
    capital: float,
    risk_pct: float,
    max_pos_pct: float,
    avg_turnover_twd: float | None = None,
) -> dict:
    if side in ("隔日觀望", "觀望", "禁止") or not entry or not stop:
        return {"lots": 0, "amount": 0, "risk_money": 0, "note": "隔日觀望／禁止，不建議進場"}

    risk_money = capital * risk_pct
    per_share_risk = abs(entry - stop)
    if per_share_risk <= 0:
        return {"lots": 0, "amount": 0, "risk_money": risk_money, "note": "停損距離為 0"}

    shares = risk_money / per_share_risk
    lots = math.floor(shares / 1000)
    max_amount = capital * max_pos_pct
    if avg_turnover_twd:
        max_amount = min(max_amount, avg_turnover_twd * 0.01)
    while lots > 0 and lots * 1000 * entry > max_amount:
        lots -= 1
    amount = lots * 1000 * entry
    worst = lots * 1000 * per_share_risk
    one_lot_risk = 1000 * per_share_risk
    note = (
        f"以本金 {capital:,.0f}、單筆風險 {risk_pct*100:.1f}%（上限 {risk_money:,.0f}）反推張數。"
        f"1 張碰到停損約虧 {one_lot_risk:,.0f}。"
    )
    if lots == 0:
        note += " 風險上限不夠 1 張，故金額為 0；若要做至少 1 張，請提高單筆風險或收斂停損。"
    return {
        "lots": lots,
        "amount": amount,
        "risk_money": risk_money,
        "worst": worst,
        "one_lot_risk": one_lot_risk,
        "note": note,
    }
