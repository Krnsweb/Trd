import io
import time

import pandas as pd
import requests
import streamlit as st
import plotly.express as px
import yfinance as yf

st.set_page_config(page_title="Macro + India Daily Dashboard", layout="wide")

YF_TICKERS = {
    "DXY": "DX-Y.NYB",
    "US 10Y": "^TNX",
    "Brent": "BZ=F",
    "Gold": "GC=F",
    "USDINR": "INR=X",
    "India VIX": "^INDIAVIX",
    "Nifty": "^NSEI",
}

DISPLAY_NOTES = {
    "DXY": "US Dollar Index",
    "US 10Y": "US 10-year Treasury yield",
    "Brent": "Brent crude front-month futures",
    "Gold": "COMEX gold futures",
    "USDINR": "USD/INR FX rate from Yahoo Finance ticker INR=X",
    "India VIX": "NSE India VIX",
    "Nifty": "Nifty 50 index",
}

CHART_COLORS = {
    "DXY": "#2563eb",
    "US 10Y": "#7c3aed",
    "Brent": "#ea580c",
    "Gold": "#ca8a04",
    "USDINR": "#0891b2",
    "India VIX": "#dc2626",
    "Nifty": "#16a34a",
}

@st.cache_data(ttl=900)
def fetch_yf_history(period="6mo", interval="1d"):
    frames = []
    for label, ticker in YF_TICKERS.items():
        hist = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False)
        if hist is None or hist.empty:
            continue
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist = hist.reset_index()
        if 'Date' not in hist.columns:
            hist = hist.rename(columns={hist.columns[0]: 'Date'})
        hist['Metric'] = label
        hist['Ticker'] = ticker
        frames.append(hist[['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Metric', 'Ticker']])
    if not frames:
        return pd.DataFrame(columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Metric', 'Ticker'])
    df = pd.concat(frames, ignore_index=True)
    df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
    return df

@st.cache_data(ttl=1800)
def fetch_fii_dii():
    url = 'https://www.moneycontrol.com/markets/fii-dii-data/cash/'
    headers = {'User-Agent': 'Mozilla/5.0'}
    out = {'date': None, 'fii_net': None, 'dii_net': None, 'source': url}
    try:
        html = requests.get(url, headers=headers, timeout=20).text
        tables = pd.read_html(io.StringIO(html))
        picked = None
        for t in tables:
            cols = [str(c).strip().lower() for c in t.columns]
            joined = ' | '.join(cols)
            if ('fii' in joined or 'dii' in joined) and ('net' in joined or 'buy / sell' in joined or 'gross' in joined):
                picked = t.copy()
                break
        if picked is None and tables:
            picked = tables[0].copy()
        if picked is None or picked.empty:
            return out
        picked.columns = [str(c).strip() for c in picked.columns]
        picked = picked.dropna(how='all')
        txt = picked.astype(str)
        txt_lower = txt.apply(lambda s: s.str.lower())
        role_col = None
        for c in picked.columns:
            if txt_lower[c].str.contains('fii|fpi|dii', regex=True).any():
                role_col = c
                break
        date_col = next((c for c in picked.columns if 'date' in c.lower()), None)
        net_col = next((c for c in picked.columns if 'net' in c.lower()), None)
        if role_col is not None and net_col is not None:
            latest_date = None
            fii_net = None
            dii_net = None
            for _, row in picked.iterrows():
                role = str(row[role_col]).lower()
                val = pd.to_numeric(str(row[net_col]).replace(',', ''), errors='coerce')
                dval = pd.to_datetime(row[date_col], errors='coerce') if date_col else pd.NaT
                if 'fii' in role or 'fpi' in role:
                    fii_net = val if pd.notna(val) else fii_net
                    latest_date = dval if pd.notna(dval) else latest_date
                if 'dii' in role:
                    dii_net = val if pd.notna(val) else dii_net
                    latest_date = dval if pd.notna(dval) else latest_date
            out['date'] = None if latest_date is None or pd.isna(latest_date) else latest_date.date().isoformat()
            out['fii_net'] = None if fii_net is None or pd.isna(fii_net) else float(fii_net)
            out['dii_net'] = None if dii_net is None or pd.isna(dii_net) else float(dii_net)
    except Exception:
        return out
    return out

def build_latest_table(df):
    rows = []
    for metric in YF_TICKERS:
        sub = df[df['Metric'] == metric].sort_values('Date').dropna(subset=['Close'])
        if sub.empty:
            continue
        last = sub.iloc[-1]
        prev = sub.iloc[-2] if len(sub) > 1 else None
        change = None if prev is None else float(last['Close'] - prev['Close'])
        pct = None if prev is None or prev['Close'] == 0 else float((last['Close'] / prev['Close'] - 1) * 100)
        rows.append({
            'Metric': metric,
            'Value': float(last['Close']),
            'Change': change,
            'Pct Change': pct,
            'Date': last['Date'].date().isoformat(),
            'High': float(last['High']) if pd.notna(last['High']) else None,
            'Low': float(last['Low']) if pd.notna(last['Low']) else None,
            'Note': DISPLAY_NOTES.get(metric, '')
        })
    return pd.DataFrame(rows)

def fmt_value(metric, v):
    if v is None or pd.isna(v):
        return 'NA'
    if metric == 'US 10Y':
        return f'{v:.2f}%'
    return f'{v:,.2f}'

def create_metric_chart(metric_df, metric_name):
    fig = px.line(
        metric_df,
        x='Date',
        y='Close',
        markers=True,
        title=metric_name,
        color_discrete_sequence=[CHART_COLORS.get(metric_name, '#2563eb')]
    )
    fig.update_traces(line=dict(width=2.5), marker=dict(size=5))
    fig.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
        xaxis_title='',
        yaxis_title='Value',
        template='plotly_white'
    )
    return fig

st.title('Daily Macro + India Market Dashboard')
st.caption('Tracks DXY, US 10Y, Brent, Gold, USDINR, India VIX, FII/DII cash, and Nifty with live connectors where available.')

with st.sidebar:
    st.header('Controls')
    lookback = st.selectbox('History window', ['1mo', '3mo', '6mo', '1y'], index=2)
    selected = st.multiselect('Metrics', list(YF_TICKERS.keys()), default=list(YF_TICKERS.keys()))
    auto_refresh = st.checkbox('Auto-refresh every 15 min', value=False)
    if auto_refresh:
        time.sleep(1)
        st.rerun()

hist = fetch_yf_history(period=lookback)
latest = build_latest_table(hist)
fii_dii = fetch_fii_dii()

if latest.empty:
    st.error('No market data returned. Check connectivity or Yahoo Finance availability.')
    st.stop()

latest = latest[latest['Metric'].isin(selected)]
hist = hist[hist['Metric'].isin(selected)]

st.markdown('### Latest KPIs')
kpi_cols = st.columns(4)
for i, (_, row) in enumerate(latest.iterrows()):
    col = kpi_cols[i % 4]
    delta_str = 'NA' if pd.isna(row['Pct Change']) else f"{row['Pct Change']:.2f}%"
    col.metric(row['Metric'], fmt_value(row['Metric'], row['Value']), delta_str)

st.markdown('### FII / DII cash activity')
a, b, c = st.columns(3)
a.metric('FII net cash (Rs cr)', 'NA' if fii_dii['fii_net'] is None else f"{fii_dii['fii_net']:,.2f}")
b.metric('DII net cash (Rs cr)', 'NA' if fii_dii['dii_net'] is None else f"{fii_dii['dii_net']:,.2f}")
c.metric('Data date', fii_dii['date'] or 'NA')

st.markdown('### Individual charts')
for metric in selected:
    metric_df = hist[hist['Metric'] == metric][['Date', 'Close']].dropna().copy()
    if metric_df.empty:
        st.warning(f'No data available for {metric}.')
        continue
    st.plotly_chart(create_metric_chart(metric_df, metric), use_container_width=True)

st.markdown('### Latest snapshot')
show = latest[['Metric', 'Value', 'Change', 'Pct Change', 'Date', 'High', 'Low', 'Note']].copy()
st.dataframe(show, use_container_width=True, hide_index=True)

csv = show.to_csv(index=False).encode('utf-8')
st.download_button('Download latest snapshot CSV', data=csv, file_name='daily_dashboard_snapshot.csv', mime='text/csv')

st.markdown('### Connector notes')
st.markdown('''
- Yahoo Finance powers DXY, US 10Y, Brent, Gold, USDINR, India VIX, and Nifty in this app.
- FII/DII cash is scraped from the publicly visible Moneycontrol cash activity page.
- If you want exchange-grade reliability, switch FII/DII and India VIX to official NSE endpoints or a licensed market data vendor.
''')
