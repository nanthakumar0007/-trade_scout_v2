"""
Trade Scout v2  —  Dual-Mode Stock Predictor
Pre-market mode  : before 8:00 AM CST  → buy at open, exit same day (uses 1 PDT)
End-of-day mode  : after  11:00 AM CST → buy before close, exit next morning (swing, no PDT)
Capital: $35 | Target profit: $1+ | Max risk: $0.50 | R:R = 2:1
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import csv, os
from datetime import datetime, date, timedelta
import pytz

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Trade Scout", page_icon="📈",
                   layout="centered", initial_sidebar_state="collapsed")

# ── Constants ─────────────────────────────────────────────────────────────────
CAPITAL       = 35.00
TARGET        = 1.00
MAX_RISK      = 0.50
PDT_WEEKLY_MAX = 3
HISTORY_FILE  = "trades_v2.csv"
PDT_FILE      = "pdt_log.csv"
CST           = pytz.timezone("America/Chicago")

HISTORY_COLS = ["date","mode","ticker","entry","target","stop","shares",
                "pot_profit","pot_loss","result","pnl","is_day_trade"]
PDT_COLS     = ["trade_date","ticker"]

# ── Ticker universe (liquid, frequently sub-$35) ──────────────────────────────
UNIVERSE = [
    "SIRI","VALE","ITUB","BBD","SNAP","SOFI","F","AAL","CCL","PLTR",
    "NIO","RIVN","LCID","HOOD","MARA","RIOT","CLSK","WULF","BITF",
    "OPEN","GME","AMC","NKLA","XPEV","LI","FUTU","WBD","PARA","T","PFE",
    "INTC","NOK","BB","MU","KEY","BAC","C","WFC","GRAB","FFIE",
    "CMCSA","VZ","HPQ","DELL","ERIC","SMCI","TIGR","CLOV","HOOD","JNPR",
]

# ═══════════════════════════════════════════════════════════════════════════════
# MOBILE-FIRST CSS  (works in desktop browser too — max-width capped at 520px)
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"]{
    max-width:520px!important;margin:0 auto!important;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    background:#0d0d0f;color:#f0f0f0}
[data-testid="stHeader"],[data-testid="stToolbar"],footer,
section[data-testid="stSidebar"]{display:none}
h1{font-size:22px!important;font-weight:800!important;letter-spacing:-.5px}
h2{font-size:17px!important;font-weight:700!important}
h3{font-size:15px!important;font-weight:600!important}
div.stButton>button{
    width:100%;height:52px;border-radius:14px;font-size:16px;
    font-weight:700;border:none;background:#1dff8a;color:#0d0d0f;
    margin:5px 0;cursor:pointer}
div.stButton>button:hover{background:#00e07a}
div.stButton>button:active{transform:scale(.98)}
div.stButton>button:disabled{background:#2e2e36;color:#555;cursor:not-allowed}
.card{background:#1a1a1e;border:.5px solid #2e2e36;border-radius:16px;
      padding:16px 18px;margin:8px 0}
.card-green{background:#0e1f14;border:.5px solid #1dff8a44;border-radius:16px;padding:16px 18px;margin:8px 0}
.card-blue{background:#0e1422;border:.5px solid #3399ff44;border-radius:16px;padding:16px 18px;margin:8px 0}
.card-red{background:#1e0e0e;border:.5px solid #ff4d4d44;border-radius:16px;padding:16px 18px;margin:8px 0}
.card-amber{background:#1e1800;border:.5px solid #ffb83344;border-radius:16px;padding:16px 18px;margin:8px 0}
.lbl{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px}
.val{font-size:26px;font-weight:800;color:#f0f0f0}
.val-g{font-size:26px;font-weight:800;color:#1dff8a}
.val-r{font-size:26px;font-weight:800;color:#ff4d4d}
.val-b{font-size:26px;font-weight:800;color:#3399ff}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:3px 9px;
       border-radius:6px;margin:2px}
.bg{background:#1dff8a22;color:#1dff8a}
.bb{background:#3399ff22;color:#3399ff}
.br{background:#ff4d4d22;color:#ff4d4d}
.ba{background:#ffb83322;color:#ffb833}
.div{border:none;border-top:.5px solid #2e2e36;margin:12px 0}
.frow{display:flex;align-items:center;gap:10px;padding:5px 0;font-size:13px}
.fdot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;
      justify-content:center;font-size:11px;font-weight:700;flex-shrink:0}
.fp{background:#1dff8a22;color:#1dff8a}
.ff{background:#ff4d4d22;color:#ff4d4d}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:8px 0}
.metric{background:#141418;border:.5px solid #2e2e36;border-radius:12px;
        padding:12px;text-align:center}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TIME UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def now_cst() -> datetime:
    return datetime.now(CST)

def scan_mode() -> str:
    """
    Returns 'premarket', 'eod', or 'closed'.
    premarket : before 08:00 CST
    eod       : 11:00–15:30 CST
    closed    : outside trading hours (still let user scan manually)
    """
    t = now_cst()
    h = t.hour + t.minute / 60
    if h < 8.0:
        return "premarket"
    if 11.0 <= h <= 15.5:
        return "eod"
    return "closed"

def market_open_today() -> bool:
    t = now_cst()
    return t.weekday() < 5   # Mon–Fri only


# ═══════════════════════════════════════════════════════════════════════════════
# PDT TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure(path, cols):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=cols).writeheader()

def load_pdt() -> pd.DataFrame:
    _ensure(PDT_FILE, PDT_COLS)
    try:
        df = pd.read_csv(PDT_FILE)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df
    except Exception:
        return pd.DataFrame(columns=PDT_COLS)

def pdt_used_this_week() -> int:
    df = load_pdt()
    if df.empty:
        return 0
    cutoff = date.today() - timedelta(days=4)   # rolling 5 business days
    recent = df[df["trade_date"] >= cutoff]
    return len(recent)

def log_pdt(ticker: str):
    _ensure(PDT_FILE, PDT_COLS)
    with open(PDT_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=PDT_COLS).writerow(
            {"trade_date": date.today().isoformat(), "ticker": ticker})

def pdt_remaining() -> int:
    return max(0, PDT_WEEKLY_MAX - pdt_used_this_week())


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

def load_history() -> pd.DataFrame:
    _ensure(HISTORY_FILE, HISTORY_COLS)
    try:
        df = pd.read_csv(HISTORY_FILE)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date", ascending=False)
    except Exception:
        return pd.DataFrame(columns=HISTORY_COLS)

def log_trade(rec: dict):
    _ensure(HISTORY_FILE, HISTORY_COLS)
    with open(HISTORY_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=HISTORY_COLS).writerow(rec)

def update_trade_result(df: pd.DataFrame, idx, result: str, pnl: float):
    df.at[idx, "result"] = result
    df.at[idx, "pnl"]    = round(pnl, 2)
    df["date"] = df["date"].astype(str)
    df.to_csv(HISTORY_FILE, index=False)
    load_history.clear() if hasattr(load_history, "clear") else None
    st.rerun()

def account_summary(df: pd.DataFrame) -> dict:
    closed = df[df["result"].isin(["win","loss"])] if not df.empty else df
    total  = len(closed)
    wins   = int((closed["result"] == "win").sum()) if total else 0
    pnl    = round(float(closed["pnl"].sum()), 2) if total else 0.0
    return {"balance": round(CAPITAL + pnl, 2), "trades": total,
            "wins": wins, "losses": total - wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "pnl": pnl}


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def rsi(series: pd.Series, n=14) -> float:
    d  = series.diff().dropna()
    g  = d.clip(lower=0).ewm(com=n-1, min_periods=n).mean()
    l  = (-d).clip(lower=0).ewm(com=n-1, min_periods=n).mean()
    rs = g / l.replace(0, np.nan)
    v  = (100 - 100/(1+rs)).iloc[-1]
    return round(float(v), 1) if pd.notna(v) else 50.0

def atr(daily: pd.DataFrame, n=14) -> float:
    h, lo, c = daily["High"], daily["Low"], daily["Close"]
    tr = pd.concat([h-lo, (h-c.shift()).abs(), (lo-c.shift()).abs()], axis=1).max(axis=1)
    v  = tr.rolling(n).mean().iloc[-1]
    return round(float(v), 4) if pd.notna(v) else 0.0

def vwap(intra: pd.DataFrame) -> float:
    tp  = (intra["High"] + intra["Low"] + intra["Close"]) / 3
    cum = (tp * intra["Volume"]).cumsum()
    vol = intra["Volume"].cumsum()
    v   = (cum / vol).iloc[-1]
    return round(float(v), 4) if pd.notna(v) else 0.0

def momentum_slope(series: pd.Series, n=10) -> float:
    """Normalised linear regression slope over last n bars."""
    y = series.iloc[-n:].values
    if len(y) < 2:
        return 0.0
    x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    return round(float(slope / y.mean() * 100), 3)   # % per bar


# ═══════════════════════════════════════════════════════════════════════════════
# UNIVERSE FETCH
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600)
def fetch_universe() -> pd.DataFrame:
    records = []
    for ticker in UNIVERSE:
        try:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1d",
                                             auto_adjust=True)
            if hist.empty or len(hist) < 11:
                continue
            price = float(hist["Close"].iloc[-1])
            if not (0.50 < price < CAPITAL):
                continue
            avg_vol = float(hist["Volume"].iloc[-10:].mean())
            prev_close = float(hist["Close"].iloc[-2])
            records.append({"ticker": ticker, "price": round(price, 2),
                            "avg_vol": int(avg_vol),
                            "prev_close": round(prev_close, 2)})
        except Exception:
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).sort_values("avg_vol", ascending=False)
    return df.head(35).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PRE-MARKET SCORER  (before 8 AM CST)
# Strategy: find stocks with pre-market volume spike + bullish gap
#           from previous close. Buy at open, target intraday $1 gain.
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=180)
def score_premarket(ticker: str, avg_vol: float, prev_close: float) -> dict | None:
    try:
        tk = yf.Ticker(ticker)
        # Pre-market + extended data for today
        pre = tk.history(period="1d", interval="1m",
                         prepost=True, auto_adjust=True)
        daily = tk.history(period="2mo", interval="1d", auto_adjust=True)
        if pre.empty or daily.empty or len(daily) < 20:
            return None

        # Filter to pre-market session (before 09:30 ET = 08:30 CST)
        pre.index = pre.index.tz_convert("America/Chicago")
        pm = pre[pre.index.hour < 8]
        if pm.empty:
            # Fall back: use all available extended data
            pm = pre

        pm_vol   = int(pm["Volume"].sum())
        pm_price = float(pm["Close"].iloc[-1])
        if pm_price <= 0 or pm_price >= CAPITAL:
            return None

        # ── Filter 1: Pre-market volume > 0.8x daily avg (lower bar — it's pre-mkt)
        pm_vol_ratio = round(pm_vol / (avg_vol * 0.15), 2)   # 0.15 = ~15% of day
        vol_pass     = pm_vol_ratio >= 0.8

        # ── Filter 2: Bullish gap — pre-mkt price > prev close
        gap_pct   = round((pm_price - prev_close) / prev_close * 100, 2)
        gap_pass  = gap_pct > 0.3   # at least +0.3% gap up

        # ── Filter 3: RSI on daily chart 40–70 (wider window for early momentum)
        rsi_val  = rsi(daily["Close"])
        rsi_pass = 40 <= rsi_val <= 70

        # ── Filter 4: Daily ATR covers our $1 target
        atr_val  = atr(daily)
        shares   = int(CAPITAL / pm_price)
        if shares == 0:
            return None
        min_move = round(TARGET / shares, 4)
        atr_pass = atr_val >= min_move

        base = {"ticker": ticker, "price": round(pm_price, 2),
                "pm_vol_ratio": pm_vol_ratio, "gap_pct": gap_pct,
                "rsi": rsi_val, "atr": round(atr_val, 3), "min_move": min_move,
                "vol_pass": vol_pass, "gap_pass": gap_pass,
                "rsi_pass": rsi_pass, "atr_pass": atr_pass}

        if vol_pass and gap_pass and rsi_pass and atr_pass:
            entry  = round(pm_price, 2)
            target = round(entry + min_move, 2)
            stop   = round(entry - (MAX_RISK / shares), 2)
            base.update({"shares": shares, "entry": entry, "target": target,
                         "stop": stop, "cost": round(entry*shares, 2),
                         "pot_profit": round((target-entry)*shares, 2),
                         "pot_loss": round((entry-stop)*shares, 2),
                         "rr": round(((target-entry)*shares) /
                                     max((entry-stop)*shares, 0.01), 2)})
        else:
            base["_failed"] = True
        return base
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# END-OF-DAY SWING SCORER  (after 11 AM CST)
# Strategy: find stocks with afternoon uptrend + volume confirmation.
#           Buy before close, sell next morning. No PDT consumed.
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=180)
def score_eod(ticker: str, avg_vol: float) -> dict | None:
    try:
        tk = yf.Ticker(ticker)
        intra = tk.history(period="1d", interval="5m", auto_adjust=True)
        daily = tk.history(period="2mo", interval="1d", auto_adjust=True)
        if intra.empty or daily.empty or len(daily) < 20 or len(intra) < 6:
            return None

        price = float(intra["Close"].iloc[-1])
        if price <= 0 or price >= CAPITAL:
            return None

        today_open = float(intra["Open"].iloc[0])
        intra_vol  = int(intra["Volume"].sum())
        elapsed    = len(intra)        # 5-min bars elapsed
        scaled_avg = avg_vol * (elapsed * 5 / 390)
        vol_ratio  = round(intra_vol / scaled_avg, 2) if scaled_avg > 0 else 0

        # ── Filter 1: Volume > 1.3x average (scaled to elapsed time)
        vol_pass = vol_ratio >= 1.3

        # ── Filter 2: Price above today's open (intraday uptrend)
        trend_pass = price > today_open

        # ── Filter 3: Price above VWAP
        vwap_val  = vwap(intra)
        vwap_pass = price >= vwap_val

        # ── Filter 4: RSI 45–65 on daily (momentum, not overbought)
        rsi_val  = rsi(daily["Close"])
        rsi_pass = 45 <= rsi_val <= 65

        # ── Filter 5: Positive price slope in last 10 bars
        slope      = momentum_slope(intra["Close"], 10)
        slope_pass = slope > 0

        # ── Filter 6: ATR covers overnight target move
        atr_val  = atr(daily)
        shares   = int(CAPITAL / price)
        if shares == 0:
            return None
        min_move = round(TARGET / shares, 4)
        atr_pass = atr_val >= min_move

        base = {"ticker": ticker, "price": round(price, 2),
                "vol_ratio": vol_ratio, "rsi": rsi_val,
                "vwap": round(vwap_val, 3), "slope": slope,
                "atr": round(atr_val, 3), "min_move": min_move,
                "vol_pass": vol_pass, "trend_pass": trend_pass,
                "vwap_pass": vwap_pass, "rsi_pass": rsi_pass,
                "slope_pass": slope_pass, "atr_pass": atr_pass}

        all_pass = all([vol_pass, trend_pass, vwap_pass, rsi_pass,
                        slope_pass, atr_pass])
        if all_pass:
            entry  = round(price, 2)
            target = round(entry + min_move, 2)
            stop   = round(entry - (MAX_RISK / shares), 2)
            base.update({"shares": shares, "entry": entry, "target": target,
                         "stop": stop, "cost": round(entry*shares, 2),
                         "pot_profit": round((target-entry)*shares, 2),
                         "pot_loss": round((entry-stop)*shares, 2),
                         "rr": round(((target-entry)*shares) /
                                     max((entry-stop)*shares, 0.01), 2)})
        else:
            base["_failed"] = True
        return base
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# FULL SCAN RUNNERS
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def run_premarket_scan():
    universe = fetch_universe()
    if universe.empty:
        return None, []
    results = []
    for _, row in universe.iterrows():
        r = score_premarket(row["ticker"], row["avg_vol"], row["prev_close"])
        if r:
            results.append(r)
    passing = [r for r in results if not r.get("_failed")]
    if not passing:
        return None, results
    def rank(r):
        return r["pm_vol_ratio"] * r["gap_pct"] * (r["atr"] / r["min_move"])
    return max(passing, key=rank), results

@st.cache_data(ttl=300)
def run_eod_scan():
    universe = fetch_universe()
    if universe.empty:
        return None, []
    results = []
    for _, row in universe.iterrows():
        r = score_eod(row["ticker"], row["avg_vol"])
        if r:
            results.append(r)
    passing = [r for r in results if not r.get("_failed")]
    if not passing:
        return None, results
    def rank(r):
        rsi_c = 1 - abs(r["rsi"] - 55) / 10
        return r["vol_ratio"] * rsi_c * r["slope"] * (r["atr"] / r["min_move"])
    return max(passing, key=rank), results


# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def frow(label, passed, detail):
    cls = "fp" if passed else "ff"
    sym = "✓" if passed else "✗"
    return (f'<div class="frow"><div class="fdot {cls}">{sym}</div>'
            f'<div style="flex:1"><b>{label}</b><br>'
            f'<span style="color:#888;font-size:12px">{detail}</span>'
            f'</div></div>')

def rec_card(best, mode_color, mode_label):
    rr_c = "#1dff8a" if best.get("rr", 0) >= 2 else "#ffb833"
    badge_mode = f'<span class="badge {mode_color}">{mode_label}</span>'
    return f"""
<div class="card-{'green' if mode_color=='bg' else 'blue'}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div class="lbl">Today's pick</div>
      <div style="font-size:36px;font-weight:900;letter-spacing:-1px;
                  color:{'#1dff8a' if mode_color=='bg' else '#3399ff'}">
        {best['ticker']}
      </div>
    </div>
    <div style="text-align:right">{badge_mode}</div>
  </div>
  <hr class="div">
  <div class="grid3">
    <div class="metric"><div class="lbl">Entry</div><div class="val">${best['entry']}</div></div>
    <div class="metric"><div class="lbl">Target</div><div class="val-g">${best['target']}</div></div>
    <div class="metric"><div class="lbl">Stop</div><div class="val-r">${best['stop']}</div></div>
  </div>
  <hr class="div">
  <div class="grid3">
    <div class="metric"><div class="lbl">Shares</div>
         <div style="font-size:22px;font-weight:800">{best['shares']}</div></div>
    <div class="metric"><div class="lbl">Cost</div>
         <div style="font-size:22px;font-weight:800">${best['cost']}</div></div>
    <div class="metric"><div class="lbl">R:R</div>
         <div style="font-size:22px;font-weight:800;color:{rr_c}">{best.get('rr','–')}:1</div>
    </div>
  </div>
</div>"""

def pnl_summary_cards(best):
    return f"""
<div class="grid2">
  <div class="card" style="text-align:center">
    <div class="lbl">Max profit</div>
    <div class="val-g">+${best['pot_profit']}</div>
  </div>
  <div class="card" style="text-align:center">
    <div class="lbl">Max risk</div>
    <div class="val-r">-${best['pot_loss']}</div>
  </div>
</div>"""


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    _ensure(HISTORY_FILE, HISTORY_COLS)
    _ensure(PDT_FILE, PDT_COLS)

    if "page"         not in st.session_state: st.session_state.page = "scanner"
    if "scan_result"  not in st.session_state: st.session_state.scan_result = None
    if "all_results"  not in st.session_state: st.session_state.all_results = []
    if "scan_mode"    not in st.session_state: st.session_state.scan_mode = None
    if "logged"       not in st.session_state: st.session_state.logged = False
    if "ran"          not in st.session_state: st.session_state.ran = False

    # ── Top nav ───────────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📡  Scanner"): st.session_state.page = "scanner"
    with c2:
        if st.button("📋  History"): st.session_state.page = "history"
    st.markdown('<hr class="div">', unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    if st.session_state.page == "scanner":
        _page_scanner()
    else:
        _page_history()


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER PAGE
# ═══════════════════════════════════════════════════════════════════════════════

def _page_scanner():
    now    = now_cst()
    mode   = scan_mode()
    pdt_rem = pdt_remaining()
    pdt_used = pdt_used_this_week()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("## 📈 Trade Scout")
    st.markdown(
        f'<p style="color:#888;font-size:13px;margin-top:-8px">'
        f'Capital <b style="color:#f0f0f0">${CAPITAL}</b> · '
        f'Target <b style="color:#1dff8a">+${TARGET}</b> · '
        f'Risk <b style="color:#ff4d4d">-${MAX_RISK}</b></p>',
        unsafe_allow_html=True)

    # ── PDT status ────────────────────────────────────────────────────────────
    pdt_color = "#1dff8a" if pdt_rem >= 2 else ("#ffb833" if pdt_rem == 1 else "#ff4d4d")
    st.markdown(
        f'<div class="card" style="display:flex;align-items:center;'
        f'justify-content:space-between;padding:12px 16px">'
        f'<div><div class="lbl">PDT trades remaining</div>'
        f'<div style="font-size:22px;font-weight:800;color:{pdt_color}">'
        f'{pdt_rem} / {PDT_WEEKLY_MAX}</div></div>'
        f'<div style="text-align:right">'
        f'<div class="lbl">Used this week</div>'
        f'<div style="font-size:18px;font-weight:700;color:#888">{pdt_used}</div>'
        f'</div></div>',
        unsafe_allow_html=True)

    # ── Mode indicator ────────────────────────────────────────────────────────
    if mode == "premarket":
        mode_html = (
            '<div class="card-green" style="text-align:center;padding:10px">'
            '<span class="badge bg">PRE-MARKET MODE</span><br>'
            '<span style="font-size:12px;color:#888;margin-top:4px;display:block">'
            'Buy at open → sell same day &nbsp;|&nbsp; '
            '<b style="color:#ff4d4d">Uses 1 PDT slot</b></span></div>')
    elif mode == "eod":
        mode_html = (
            '<div class="card-blue" style="text-align:center;padding:10px">'
            '<span class="badge bb">END-OF-DAY SWING MODE</span><br>'
            '<span style="font-size:12px;color:#888;margin-top:4px;display:block">'
            'Buy before close → sell tomorrow &nbsp;|&nbsp; '
            '<b style="color:#1dff8a">No PDT slot used</b></span></div>')
    else:
        h = now.strftime("%I:%M %p CST")
        mode_html = (
            f'<div class="card-amber" style="text-align:center;padding:10px">'
            f'<span class="badge ba">MARKET CLOSED · {h}</span><br>'
            f'<span style="font-size:12px;color:#888;margin-top:4px;display:block">'
            f'You can still force-scan. Pre-market opens 4 AM · Market opens 8:30 AM CST'
            f'</span></div>')

    st.markdown(mode_html, unsafe_allow_html=True)

    # ── Manual override for outside-hours testing ──────────────────────────
    if mode == "closed":
        manual_mode = st.radio("Force scan as:", ["Pre-market", "End-of-day"],
                               horizontal=True, label_visibility="collapsed")
        forced = "premarket" if manual_mode == "Pre-market" else "eod"
    else:
        forced = mode

    # ── PDT warning ───────────────────────────────────────────────────────────
    if pdt_rem == 0 and forced == "premarket":
        st.markdown(
            '<div class="card-red" style="text-align:center;padding:12px">'
            '<b style="color:#ff4d4d">⚠ No PDT trades remaining this week</b><br>'
            '<span style="font-size:12px;color:#888">Switch to End-of-day swing mode '
            'to trade without using a PDT slot.</span></div>',
            unsafe_allow_html=True)

    # ── Scan button ───────────────────────────────────────────────────────────
    btn_disabled = (pdt_rem == 0 and forced == "premarket")
    if st.button("🔍  Run Market Scan", disabled=btn_disabled):
        with st.spinner("Scanning market universe…"):
            if forced == "premarket":
                best, all_r = run_premarket_scan()
            else:
                best, all_r = run_eod_scan()
            st.session_state.scan_result = best
            st.session_state.all_results = all_r
            st.session_state.scan_mode   = forced
            st.session_state.logged      = False
            st.session_state.ran         = True

    # ── No scan yet ───────────────────────────────────────────────────────────
    if not st.session_state.ran:
        st.markdown(
            '<div class="card" style="text-align:center;padding:32px">'
            '<div style="font-size:40px">🎯</div>'
            '<p style="color:#888;margin:8px 0 0">Before 8 AM CST → pre-market scan<br>'
            'After 11 AM CST → end-of-day swing scan</p></div>',
            unsafe_allow_html=True)
        return

    best    = st.session_state.scan_result
    s_mode  = st.session_state.scan_mode

    # ── No setup found ─────────────────────────────────────────────────────────
    if best is None:
        st.markdown(
            '<div class="card-red" style="text-align:center;padding:24px">'
            '<div style="font-size:36px">⚠️</div>'
            '<p style="color:#ff4d4d;font-weight:700">No valid setup found</p>'
            '<p style="color:#888;font-size:13px">No ticker cleared all filters.<br>'
            'Protecting capital — skip today.</p></div>',
            unsafe_allow_html=True)
        _scan_table(st.session_state.all_results)
        return

    # ── Recommendation ─────────────────────────────────────────────────────────
    if s_mode == "premarket":
        mc, ml = "bg", "PRE-MARKET DAY TRADE"
        is_dt  = True
        strategy_note = (
            "Place a <b>market buy order</b> at open (9:30 AM ET). "
            "Set your stop-loss immediately. Target is an intraday exit — "
            "<b>sell before 3:00 PM ET</b> to avoid holding overnight.")
    else:
        mc, ml = "bb", "END-OF-DAY SWING"
        is_dt  = False
        strategy_note = (
            "Place a <b>limit buy order</b> 15–30 min before market close (3:00–3:30 PM ET). "
            "This is an <b>overnight hold</b>. Set your stop-loss. "
            "Target exit: next morning pre-market or at open.")

    st.markdown(rec_card(best, mc, ml), unsafe_allow_html=True)
    st.markdown(pnl_summary_cards(best), unsafe_allow_html=True)

    # ── Strategy note ─────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="card-amber" style="font-size:13px;color:#ffb833;padding:12px 14px">'
        f'📋 <b>Strategy:</b> {strategy_note}</div>',
        unsafe_allow_html=True)

    # ── Filter details ─────────────────────────────────────────────────────────
    if s_mode == "premarket":
        filters_html = (
            frow("Pre-market volume",  best["vol_pass"],
                 f'{best["pm_vol_ratio"]}× of expected pre-mkt volume (need ≥0.8×)')
          + frow("Gap from prev close", best["gap_pass"],
                 f'+{best["gap_pct"]}% gap up (need >+0.3%)')
          + frow("RSI momentum",        best["rsi_pass"],
                 f'RSI {best["rsi"]} (need 40–70)')
          + frow("ATR coverage",        best["atr_pass"],
                 f'ATR ${best["atr"]} covers ${best["min_move"]} min move for $1 target'))
    else:
        filters_html = (
            frow("Volume surge",      best["vol_pass"],
                 f'{best["vol_ratio"]}× scaled avg (need ≥1.3×)')
          + frow("Above today open",  best["trend_pass"],
                 f'${best["price"]} vs open — intraday uptrend confirmed')
          + frow("Above VWAP",        best["vwap_pass"],
                 f'Price ${best["price"]} ≥ VWAP ${best.get("vwap","–")}')
          + frow("RSI momentum",      best["rsi_pass"],
                 f'RSI {best["rsi"]} (need 45–65)')
          + frow("Positive slope",    best["slope_pass"],
                 f'Price slope {best.get("slope","–")}% per bar (need >0)')
          + frow("ATR coverage",      best["atr_pass"],
                 f'ATR ${best["atr"]} covers ${best["min_move"]} overnight target'))

    st.markdown(
        f'<div class="card"><div class="lbl" style="margin-bottom:8px">Filter results</div>'
        + filters_html + "</div>",
        unsafe_allow_html=True)

    # ── Risk disclosure ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="background:#1a1100;border:.5px solid #ffb83333;border-radius:12px;'
        'padding:10px 14px;margin:8px 0;font-size:12px;color:#ffb833">'
        '⚠️ No algorithm guarantees profit. Always place your stop-loss order '
        'immediately after entry. Never risk more than you can afford to lose.</div>',
        unsafe_allow_html=True)

    # ── Confirm button ────────────────────────────────────────────────────────
    if not st.session_state.logged:
        if st.button("✅  Confirm Trade Placed"):
            rec = {
                "date": datetime.now().isoformat(timespec="seconds"),
                "mode": s_mode,
                "ticker": best["ticker"],
                "entry": best["entry"],
                "target": best["target"],
                "stop": best["stop"],
                "shares": best["shares"],
                "pot_profit": best["pot_profit"],
                "pot_loss": best["pot_loss"],
                "result": "open",
                "pnl": 0.0,
                "is_day_trade": is_dt,
            }
            log_trade(rec)
            if is_dt:
                log_pdt(best["ticker"])
            st.session_state.logged = True
            st.rerun()
    else:
        st.markdown(
            '<div class="card-green" style="text-align:center;padding:12px">'
            '✅ <b style="color:#1dff8a">Trade logged!</b> '
            'Update the result in History when closed.</div>',
            unsafe_allow_html=True)

    # ── Full scan table ───────────────────────────────────────────────────────
    with st.expander("📊 Full scan results"):
        _scan_table(st.session_state.all_results, s_mode)


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY PAGE
# ═══════════════════════════════════════════════════════════════════════════════

def _page_history():
    st.markdown("## 📋 Trade History")
    df  = load_history()
    s   = account_summary(df)

    bal_c = "#1dff8a" if s["balance"] >= CAPITAL else "#ff4d4d"
    pnl_c = "#1dff8a" if s["pnl"] >= 0 else "#ff4d4d"
    sign  = "+" if s["pnl"] >= 0 else ""

    st.markdown(
        f'<div class="card">'
        f'<div class="lbl">Account balance</div>'
        f'<div style="font-size:38px;font-weight:900;color:{bal_c}">${s["balance"]}</div>'
        f'<div style="font-size:13px;color:#888;margin-top:4px">'
        f'Started ${CAPITAL} · '
        f'<span style="color:{pnl_c}">{sign}${s["pnl"]} total P&L</span></div></div>',
        unsafe_allow_html=True)

    st.markdown(
        f'<div class="grid3">'
        f'<div class="metric"><div class="lbl">Trades</div>'
        f'<div style="font-size:22px;font-weight:800">{s["trades"]}</div></div>'
        f'<div class="metric"><div class="lbl">Wins</div>'
        f'<div style="font-size:22px;font-weight:800;color:#1dff8a">{s["wins"]}</div></div>'
        f'<div class="metric"><div class="lbl">Win rate</div>'
        f'<div style="font-size:22px;font-weight:800">{s["win_rate"]}%</div></div>'
        f'</div>',
        unsafe_allow_html=True)

    # PDT usage this week
    pdt_used = pdt_used_this_week()
    pdt_rem  = pdt_remaining()
    st.markdown(
        f'<div class="card" style="display:flex;justify-content:space-between;'
        f'align-items:center;padding:12px 16px">'
        f'<div><div class="lbl">PDT this week</div>'
        f'<div style="font-size:18px;font-weight:700">{pdt_used} used · '
        f'<span style="color:#{"1dff8a" if pdt_rem > 0 else "ff4d4d"}">'
        f'{pdt_rem} remaining</span></div></div>'
        f'<div style="font-size:12px;color:#555">Resets rolling 5 days</div></div>',
        unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)

    if df.empty:
        st.markdown(
            '<div class="card" style="text-align:center;padding:32px">'
            '<p style="color:#888">No trades yet. Confirm a trade on the Scanner tab.</p>'
            '</div>', unsafe_allow_html=True)
        return

    for _, row in df.iterrows():
        result   = str(row.get("result", "open")).lower()
        pnl_val  = float(row.get("pnl", 0))
        is_dt    = str(row.get("is_day_trade", "False")).lower() == "true"
        rc       = {"win": "#1dff8a", "loss": "#ff4d4d"}.get(result, "#ffb833")
        pnl_str  = (("+" if pnl_val >= 0 else "") + f"${pnl_val:.2f}"
                    ) if result != "open" else "–"
        dt_badge = ('<span class="badge br">Day trade</span>'
                    if is_dt else '<span class="badge bb">Swing</span>')
        mode_str = row.get("mode", "")
        d_str    = pd.to_datetime(row["date"]).strftime("%b %d, %Y %H:%M")

        st.markdown(
            f'<div class="card" style="margin:10px 0">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<div style="font-size:22px;font-weight:900">{row["ticker"]}</div>'
            f'<div>{dt_badge} '
            f'<span style="font-size:13px;font-weight:700;color:{rc}">'
            f'{result.upper()}</span></div></div>'
            f'<div style="font-size:12px;color:#555;margin-bottom:8px">{d_str}</div>'
            f'<div class="grid3" style="font-size:12px;text-align:center">'
            f'<div><div style="color:#888">Entry</div><b>${float(row["entry"]):.2f}</b></div>'
            f'<div><div style="color:#888">Target</div>'
            f'<b style="color:#1dff8a">${float(row["target"]):.2f}</b></div>'
            f'<div><div style="color:#888">Stop</div>'
            f'<b style="color:#ff4d4d">${float(row["stop"]):.2f}</b></div>'
            f'</div>'
            f'<div style="margin-top:8px;font-size:13px">'
            f'P&L: <b style="color:{rc}">{pnl_str}</b> &nbsp;·&nbsp; '
            f'Shares: {int(row["shares"])}</div></div>',
            unsafe_allow_html=True)

        if result == "open":
            c1, c2 = st.columns(2)
            with c1:
                if st.button(f"✅ Win", key=f"w{row.name}"):
                    df2 = load_history()
                    update_trade_result(df2, row.name, "win",
                                        float(row["pot_profit"]))
            with c2:
                if st.button(f"❌ Loss", key=f"l{row.name}"):
                    df2 = load_history()
                    update_trade_result(df2, row.name, "loss",
                                        -float(row["pot_loss"]))


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN TABLE
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_table(results: list, mode: str = "eod"):
    if not results:
        st.markdown('<p style="color:#888;font-size:13px">No data.</p>',
                    unsafe_allow_html=True)
        return
    rows = []
    for r in results:
        passed = not r.get("_failed")
        if mode == "premarket":
            f = ("✓" if r.get("vol_pass") else "✗") + \
                ("✓" if r.get("gap_pass") else "✗") + \
                ("✓" if r.get("rsi_pass") else "✗") + \
                ("✓" if r.get("atr_pass") else "✗")
        else:
            f = ("✓" if r.get("vol_pass") else "✗") + \
                ("✓" if r.get("trend_pass") else "✗") + \
                ("✓" if r.get("vwap_pass") else "✗") + \
                ("✓" if r.get("rsi_pass") else "✗") + \
                ("✓" if r.get("slope_pass") else "✗") + \
                ("✓" if r.get("atr_pass") else "✗")
        rows.append({"Ticker": r["ticker"],
                     "Price": f'${r["price"]:.2f}',
                     "RSI": r.get("rsi", "–"),
                     "Filters": f,
                     "Pass": "✅" if passed else "❌"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
