"""
Dashboard Laporan Omzet (Python + Streamlit)
Jalankan : streamlit run reporthnp.py
Install  : pip install streamlit pandas plotly
Sumber   : link Google Sheets "Publish to web" (CSV) atau unggah CSV manual.
Omzet    : kolom "Sales Netto"
"""
import io
import math
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit.runtime import exists

if not exists():
    print("Jalankan dengan: streamlit run reporthnp.py")
    raise SystemExit

# Tempel link Publish to web (format CSV) di sini. Di Streamlit Cloud lebih aman lewat Secrets: CSV_URL = "..."
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTknFFShtKKmsiLiH1IKhD9rARIlN68NUWdOrFiQc42X2jdAGemNg9L_NwBbb60osXL-m_1PIPAB_hF/pubhtml"

BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
PAL = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]
KOLOM = {
    "storecode": "Store",
    "transdate": "Tgl",
    "sales netto": "Netto",
    "receiptno": "Resi",
    "transqty": "Qty",
    "sales after disc.": "SAD",
    "service charge": "SC",
    "transbruto": "Bruto",
    "cogs": "COGS",
    "group": "Group",
    "department": "Dept",
    "payment": "Payment",
    "catname": "Menu",
}
ANGKA = ["Qty", "SAD", "SC", "Tax", "Bruto", "COGS"]
TEKS = ["Group", "Dept", "Payment", "Menu"]
TOTAL_MONTHS = 12
CHART_MIN_HEIGHT = 340
CHART_ITEM_HEIGHT = 26
CHART_MARGIN_EXTRA = 90

# Tema terang: file .streamlit/config.toml dibuat otomatis jika belum ada (restart Streamlit sekali)
_cfg = Path(".streamlit/config.toml")
if not _cfg.exists():
    try:
        _cfg.parent.mkdir(exist_ok=True)
        _cfg.write_text(
            '[theme]\nbase = "light"\nprimaryColor = "#1f4e8c"\nbackgroundColor = "#f4f6fa"\n'
            'secondaryBackgroundColor = "#ffffff"\ntextColor = "#1d2433"\n',
            encoding="utf-8",
        )
    except Exception:
        pass

st.set_page_config(page_title="Laporan Kinerja Omzet", layout="wide")

st.markdown(
    """<style>
.stApp{background:#f4f6fa}
.block-container{max-width:1200px;padding-top:1.5rem}
.stApp label{color:#1d2433}
.stApp h2{color:#1f4e8c !important;font-size:1.1rem !important;border-bottom:2px solid #1f4e8c;padding:0 0 6px 0 !important;margin-top:1.5rem}
.banner{background:#1f4e8c;border-radius:10px;padding:22px 26px;margin-bottom:12px}
.stApp .banner h1{color:#fff !important;margin:0 0 6px 0;font-size:22px;padding:0}
.stApp .banner p{color:#fff !important;margin:0;opacity:.85;font-size:13px}
.card{background:#fff;border:1px solid #e3e7ef;border-radius:10px;padding:16px}
.narasi{line-height:1.7;color:#1d2433}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:12px}
.kpi{background:#fff;border:1px solid #e3e7ef;border-radius:10px;padding:16px}
.kpi .l{color:#6b7385;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.kpi .v{font-size:20px;font-weight:700;margin:6px 0 2px 0;color:#1d2433}
.kpi .v.up{color:#1a8f4c}
.kpi .v.down{color:#c0392b}
.kpi .s{font-size:12px;color:#6b7385}
[data-testid="stPlotlyChart"]{background:#fff;border:1px solid #e3e7ef;border-radius:10px;padding:8px}
[data-testid="stDataFrame"]{border:1px solid #e3e7ef;border-radius:10px;overflow:hidden}
</style>""",
    unsafe_allow_html=True,
)


def kartu(l, v, cap=""):
    kelas = "up" if v.startswith("+") else "down" if (v.startswith("-") and "%" in v) else ""
    return f'<div class="kpi"><div class="l">{l}</div><div class="v {kelas}">{v}</div><div class="s">{cap or "&nbsp;"}</div></div>'


def grid(items):
    st.markdown(
        '<div class="kpis">' + "".join(kartu(i[0], i[1], i[3] if len(i) > 3 else "") for i in items) + "</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------ format
def url_csv(u):
    """Ubah link Publish to web (pubhtml) otomatis menjadi link CSV."""
    u = (u or "").strip()
    if "/pubhtml" in u:
        u = u.replace("/pubhtml", "/pub")
    if "/pub" in u and "output=" not in u:
        u += ("&" if "?" in u else "?") + "output=csv"
    return u


def idn(t):
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def angka(x, d=0):
    return idn(f"{x:,.{d}f}")


def rp(x):
    return "Rp " + angka(x)


def singkat(x):
    if abs(x) >= 1e9:
        return angka(x / 1e9, 1) + " M"
    if abs(x) >= 1e6:
        return angka(x / 1e6) + " jt"
    return angka(x)


def pct(v, tanda=True):
    if v is None or pd.isna(v):
        return "n/a"
    return idn(f"{v:+.1f}%" if tanda else f"{v:.1f}%")


def growth(a, b):
    return None if not b else (a - b) / b * 100


def ticks(maks):
    mentah = (maks or 1) / 5
    mag = 10 ** math.floor(math.log10(mentah))
    n = mentah / mag
    step = (1 if n <= 1 else 2 if n <= 2 else 5 if n <= 5 else 10) * mag
    vals = [i * step for i in range(int(maks / step) + 2)]
    return vals, [singkat(v) for v in vals]


def chart_height_for_items(n_items):
    return max(CHART_MIN_HEIGHT, CHART_ITEM_HEIGHT * n_items + CHART_MARGIN_EXTRA)


# ------------------------------------------------------------ data
def ke_angka(s):
    s = s.fillna("").astype(str).str.replace(r"[^0-9,\.\-]", "", regex=True)
    fmt_id = s.str.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")
    fmt_us = s.str.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
    s = s.where(~fmt_id, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    s = s.where(~fmt_us, s.str.replace(",", "", regex=False))
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def bersihkan(raw):
    peta = {}
    for c in raw.columns:
        k = c.strip().lower()
        if k in KOLOM:
            peta[c] = KOLOM[k]
        elif k.startswith("tax"):
            peta[c] = "Tax"
    df = raw.rename(columns=peta)
    hilang = [n for n in ["Store", "Tgl", "Netto"] if n not in df.columns]
    if hilang:
        st.error("Kolom tidak ditemukan: " + ", ".join(hilang) + "\nKolom terbaca: " + ", ".join(raw.columns))
        st.stop()

    tgl = pd.to_datetime(df["Tgl"].astype(str).str.strip(), format="%Y%m%d", errors="coerce")
    sisa = tgl.isna()
    if sisa.any():
        tgl[sisa] = pd.to_datetime(df.loc[sisa, "Tgl"], dayfirst=True, errors="coerce")
    df["Tgl"] = tgl
    df["Netto"] = ke_angka(df["Netto"])
    for c in ANGKA:
        df[c] = ke_angka(df[c]).fillna(0) if c in df.columns else 0.0
    for c in TEKS:
        df[c] = df[c].fillna("-").astype(str).str.strip().replace("", "-") if c in df.columns else "-"
    df["Store"] = df["Store"].astype(str).str.strip()
    df["Nota"] = (df["Store"] + "|" + df["Resi"].astype(str).str.strip()) if "Resi" in df.columns else pd.NA

    total = len(df)
    df = df.dropna(subset=["Tgl", "Netto"])
    df = df[df["Store"] != ""].copy()
    df.attrs["dilewati"] = total - len(df)
    df["Tahun"] = df["Tgl"].dt.year.astype(int)
    df["Bulan"] = df["Tgl"].dt.month.astype(int)
    df["Hari"] = df["Tgl"].dt.day.astype(int)
    return df


@st.cache_data(ttl=300, show_spinner="Memuat data...")
def muat(sumber, isi=None):
    src = io.BytesIO(isi) if isi is not None else sumber
    raw = pd.read_csv(src, dtype=str)
    if raw.shape[1] == 1 and isi is not None:  # CSV bertitik koma
        raw = pd.read_csv(io.BytesIO(isi), dtype=str, sep=";")
    return bersihkan(raw)


# ------------------------------------------------------------ KPI
def get_valid_months(bul, tahun, Y, M, partial):
    hasil = []
    for t in tahun:
        for b in range(1, TOTAL_MONTHS + 1):
            nilai = float(bul.loc[b, t])
            if nilai > 0 and not (t == Y and b == M and partial):
                hasil.append((t, b, nilai))
    return hasil


def gross_margin_for_year(pt, year):
    sad = float(pt.loc[year, "sad"]) if year in pt.index else 0.0
    cogs = float(pt.loc[year, "cogs"]) if year in pt.index else 0.0
    return ((sad - cogs) / sad * 100) if sad else None


def cogs_pct_for_year(pt, year):
    sad = float(pt.loc[year, "sad"]) if year in pt.index else 0.0
    cogs = float(pt.loc[year, "cogs"]) if year in pt.index else 0.0
    return (cogs / sad * 100) if sad else None


def gross_profit_for_year(pt, year):
    sad = float(pt.loc[year, "sad"]) if year in pt.index else 0.0
    cogs = float(pt.loc[year, "cogs"]) if year in pt.index else 0.0
    return sad - cogs


def annual_transaction_count(pt, year):
    return int(pt.loc[year, "trn"]) if year in pt.index else 0


def build_executive_summary(S, nama, tahun, Y, P, M, Dd, pilih, kon, sub_kon):
    n = f"**{nama}** mencatat total omzet (Sales Netto) **{rp(S['tot'].sum())}** pada periode {tahun[0]}-{Y}. "
    n += f"Sampai dengan tanggal {Dd}/{M}/{Y}, omzet tahun berjalan sebesar **{rp(S['ytd_now'])}**"
    if S["ytd_g"] is not None:
        direction = "naik" if S["ytd_g"] >= 0 else "turun"
        n += f", {direction} **{pct(abs(S['ytd_g']), False)}** dibanding rentang tanggal yang sama tahun {P}"
    n += ". "
    if S["hi"]:
        n += f"Omzet bulanan tertinggi terjadi pada {lbl(S['hi'])} ({rp(S['hi'][2])})"
        n += f", sedangkan terendah pada {lbl(S['lo'])} ({rp(S['lo'][2])}). " if S["lo"] else ". "
    if annual_transaction_count(S["pt"], Y):
        n += f"Pada {Y} tercatat {angka(annual_transaction_count(S['pt'], Y))} nota dengan rata-rata {rp(S['tot'][Y] / annual_transaction_count(S['pt'], Y))} per nota. "
    if pilih != "SEMUA STORE":
        n += f"Store ini berkontribusi {kon} dari total omzet {Y} ({sub_kon.lower()})."
    return n


def hitung(d, tahun, Y, M, Dd, partial):
    bul = (
        d.groupby(["Tahun", "Bulan"], as_index=False)
        .agg(Netto=("Netto", "sum"))
        .pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
        .reindex(index=range(1, TOTAL_MONTHS + 1), columns=tahun, fill_value=0)
    )
    tot = bul.sum()
    pt = (
        d.groupby("Tahun")
        .agg(
            trn=("Nota", "nunique"),
            qty=("Qty", "sum"),
            sad=("SAD", "sum"),
            sc=("SC", "sum"),
            tax=("Tax", "sum"),
            bruto=("Bruto", "sum"),
            cogs=("COGS", "sum"),
        )
        .reindex(tahun, fill_value=0)
    )
    valid_months = get_valid_months(bul, tahun, Y, M, partial)
    aktif = {t: sum(1 for item in valid_months if item[0] == t) for t in tahun}
    ytd_now = float(d.loc[d["Tahun"] == Y, "Netto"].sum())
    m_prev = (d["Tahun"] == Y - 1) & ((d["Bulan"] < M) | ((d["Bulan"] == M) & (d["Hari"] <= Dd)))
    ytd_prev = float(d.loc[m_prev, "Netto"].sum())
    dy = d[d["Tahun"] == Y]
    return {
        "bul": bul,
        "tot": tot,
        "pt": pt,
        "rb": {t: (tot[t] / aktif[t] if aktif[t] else 0) for t in tahun},
        "hi": max(valid_months, key=lambda s: s[2]) if valid_months else None,
        "lo": min(valid_months, key=lambda s: s[2]) if valid_months else None,
        "ytd_now": ytd_now,
        "ytd_prev": ytd_prev,
        "ytd_g": growth(ytd_now, ytd_prev),
        "grp": dy.groupby("Group")["Netto"].sum(),
        "dep": dy.groupby("Dept")["Netto"].sum(),
        "pay": dy.groupby("Payment")["Netto"].sum(),
        "menu": dy.groupby("Menu")["Netto"].sum(),
    }


def hbar(judul, serie, warna, n=10, uang=True):
    s = serie.sort_values(ascending=False).head(n)[::-1]
    fmt = rp if uang else angka
    fig = go.Figure(
        go.Bar(
            x=s.values,
            y=list(s.index),
            orientation="h",
            marker_color=warna,
            text=[singkat(v) for v in s.values],
            textposition="outside",
            cliponaxis=False,
            customdata=[fmt(v) for v in s.values],
            hovertemplate="%{y}<br>%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        title=judul,
        height=chart_height_for_items(len(s)),
        margin=dict(t=45, r=60, b=20, l=10),
        xaxis=dict(showticklabels=False),
        yaxis=dict(automargin=True),
    )
    return fig


def lbl(x):
    return f"{BLN[x[1] - 1]} {x[0]}" if x else "-"


# ------------------------------------------------------------ SUMBER DATA
sumber = CSV_URL
try:
    sumber = sumber or st.secrets.get("CSV_URL", "")
except Exception:
    pass

sumber = url_csv(sumber)

with st.sidebar:
    st.header("Filter")
    file = st.file_uploader("Atau unggah CSV manual", type=["csv", "txt"])
    if st.button("Muat ulang data"):
        st.cache_data.clear()
        st.rerun()

if file is not None:
    try:
        df = muat("upload", file.getvalue())
    except pd.errors.EmptyDataError:
        st.error("File CSV kosong atau tidak terbaca.")
        st.stop()
    except pd.errors.ParserError:
        st.error("Format file CSV tidak valid. Pastikan file CSV asli dan tidak rusak.")
        st.stop()
    except Exception as exc:
        st.error(f"Gagal membaca file upload: {exc}")
        st.stop()
elif sumber:
    try:
        df = muat(sumber)
    except pd.errors.EmptyDataError:
        st.error("Data dari Google Sheets kosong atau link CSV tidak valid.")
        st.stop()
    except pd.errors.ParserError:
        st.error("Format data dari Google Sheets tidak valid. Cek kembali link CSV Anda.")
        st.stop()
    except Exception as e:
        st.error(f"Gagal memuat dari Google Sheets: {e}\nAnda bisa mengunggah CSV manual di sidebar.")
        st.stop()
else:
    st.title("HELIOS - Laporan Kinerja Omzet Penjualan")
    st.info("Isi CSV_URL dengan link Publish to web (CSV) dari Google Sheets, atau unggah file CSV di sidebar.")
    st.stop()

if df.empty:
    st.error("Tidak ada baris valid. Periksa format TransDate (contoh 20240906) dan Sales Netto.")
    st.stop()

tahun = sorted(int(t) for t in df["Tahun"].unique())
warna = {t: PAL[i % len(PAL)] for i, t in enumerate(tahun)}
akhir = df["Tgl"].max()
Y, M, Dd = int(akhir.year), int(akhir.month), int(akhir.day)
partial = Dd < akhir.days_in_month
P = Y - 1
stores = sorted(df["Store"].unique())

with st.sidebar:
    pilih = st.selectbox("StoreCode", ["SEMUA STORE"] + stores)

d = df if pilih == "SEMUA STORE" else df[df["Store"] == pilih]
nama = "Seluruh Store" if pilih == "SEMUA STORE" else f"Store {pilih}"
S = hitung(d, tahun, Y, M, Dd, partial)
SA = S if pilih == "SEMUA STORE" else hitung(df, tahun, Y, M, Dd, partial)

# kontribusi & peringkat
rank = []
for s_ in stores:
    h = S if s_ == pilih else hitung(df[df["Store"] == s_], tahun, Y, M, Dd, partial)
    rank.append((s_, h))
rank.sort(key=lambda x: x[1]["tot"][Y], reverse=True)
tot_all = SA["tot"][Y]
if pilih == "SEMUA STORE":
    kon, sub_kon = "100%", f"{len(stores)} store"
else:
    posisi = [r[0] for r in rank].index(pilih) + 1
    kon = pct(S["tot"][Y] / tot_all * 100, False) if tot_all else "n/a"
    sub_kon = f"Peringkat {posisi} dari {len(stores)} store"

# ------------------------------------------------------------ TAMPILAN
st.markdown(
    '<div class="banner"><h1>HELIOS - Laporan Kinerja Omzet Penjualan</h1><p>'
    f"{nama} | Data {df['Tgl'].min():%d/%m/%Y} s.d. {akhir:%d/%m/%Y} | {len(stores)} store | "
    "Basis omzet: Sales Netto | Diperbarui otomatis tiap 5 menit</p></div>",
    unsafe_allow_html=True,
)

pt, tot = S["pt"], S["tot"]
trn = lambda t: int(pt.loc[t, "trn"]) if t in pt.index else 0
cogs_pct = lambda t: (pt.loc[t, "cogs"] / pt.loc[t, "sad"] * 100) if pt.loc[t, "sad"] else None
laba = lambda t: pt.loc[t, "sad"] - pt.loc[t, "cogs"]

st.header("1. Ringkasan Eksekutif")
summary_text = build_executive_summary(S, nama, tahun, Y, P, M, Dd, pilih, kon, sub_kon)
st.markdown('<div class="card narasi">' + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", summary_text) + "</div>", unsafe_allow_html=True)

st.header("2. Indikator Kinerja Utama (KPI)")
k = [
    ("Total omzet periode", rp(tot.sum()), None, f"{tahun[0]} - {Y}"),
    (f"Omzet {Y} (YTD s.d. {Dd}/{M})", rp(S["ytd_now"]), None, f"{P}: {rp(S['ytd_prev'])} (tanggal sama)"),
    (f"Pertumbuhan YTD vs {P}", pct(S["ytd_g"]), None, "Rentang tanggal yang sama"),
]
for t in tahun[1:]:
    k.append((f"Pertumbuhan {t} vs {t - 1}", pct(growth(tot[t], tot[t - 1])), None, f"Omzet {t}: {singkat(tot[t])}"))
k += [
    (f"Rata-rata omzet bulanan {Y}", rp(S["rb"][Y]), None, f"{P}: {singkat(S['rb'].get(P, 0))}"),
    (f"Jumlah transaksi (nota) {Y}", angka(annual_transaction_count(pt, Y)), None, f"{P}: {angka(annual_transaction_count(pt, P))}"),
    (f"Rata-rata nilai per nota {Y}", rp(tot[Y] / annual_transaction_count(pt, Y)) if annual_transaction_count(pt, Y) else "n/a", None,
     f"{P}: {rp(tot[P] / annual_transaction_count(pt, P)) if P in tot.index and annual_transaction_count(pt, P) else 'n/a'}"),
    (f"Item terjual {Y}", angka(pt.loc[Y, "qty"]), None, f"{P}: {angka(pt.loc[P, 'qty']) if P in pt.index else 0}"),
    (f"Sales After Disc. {Y}", rp(pt.loc[Y, "sad"]), None, "Sebelum service charge & pajak"),
    (f"Service charge + pajak {Y}", rp(pt.loc[Y, "sc"] + pt.loc[Y, "tax"]), None,
     f"SC {singkat(pt.loc[Y, 'sc'])} | Pajak {singkat(pt.loc[Y, 'tax'])}"),
    (f"Total diskon {Y}", rp(max(0, pt.loc[Y, "bruto"] - pt.loc[Y, "sad"])), None, "TransBruto - Sales After Disc."),
    (f"COGS {Y}", rp(pt.loc[Y, "cogs"]), None, f"{P}: {rp(pt.loc[P, 'cogs']) if P in pt.index else 'n/a'}"),
    (f"COGS % dari Sales After Disc. {Y}", pct(cogs_pct_for_year(pt, Y), False), None, f"{P}: {pct(cogs_pct_for_year(pt, P), False) if P in pt.index else 'n/a'}"),
    (f"Laba kotor {Y}", rp(gross_profit_for_year(pt, Y)), None, f"{P}: {rp(gross_profit_for_year(pt, P)) if P in pt.index else 'n/a'}"),
    (f"Gross margin {Y}", pct(gross_margin_for_year(pt, Y), False), None, f"{P}: {pct(gross_margin_for_year(pt, P), False) if P in pt.index else 'n/a'}"),
    ("Bulan omzet tertinggi", lbl(S["hi"]), None, rp(S["hi"][2]) if S["hi"] else ""),
    ("Bulan omzet terendah", lbl(S["lo"]), None, rp(S["lo"][2]) if S["lo"] else ""),
    (f"Kontribusi terhadap total {Y}", kon, None, sub_kon),
]
grid(k)

st.header("3. Analisis Tren")
c1, c2 = st.columns([2.4, 1])
fig = go.Figure()
for t in tahun:
    y = [None if (t == Y and b > M) else float(v) for b, v in zip(range(1, 13), S["bul"][t])]
    fig.add_trace(
        go.Scatter(
            x=BLN,
            y=y,
            mode="lines+markers",
            name=str(t),
            line=dict(width=3, color=warna[t]),
            customdata=[rp(v) for v in S["bul"][t]],
            hovertemplate="%{x}<br>%{customdata}<extra>" + str(t) + "</extra>",
        )
    )
tv, tt = ticks(float(S["bul"].values.max()))
fig.update_layout(
    title=f"Tren Omzet Bulanan - {nama}",
    height=380,
    yaxis=dict(tickvals=tv, ticktext=tt, rangemode="tozero", title="Omzet (Rupiah)"),
    legend=dict(orientation="h", y=-0.2),
    margin=dict(t=50, r=15, b=60, l=70),
)
c1.plotly_chart(fig, use_container_width=True)
vals = [float(tot[t]) for t in tahun]
tv2, tt2 = ticks(max(vals))
fig2 = go.Figure(
    go.Bar(
        x=[str(t) for t in tahun],
        y=vals,
        marker_color=[warna[t] for t in tahun],
        text=[singkat(v) for v in vals],
        textposition="outside",
        customdata=[rp(v) for v in vals],
        hovertemplate="%{x}<br>%{customdata}<extra></extra>",
    )
)
fig2.update_layout(
    title="Total Omzet per Tahun",
    height=380,
    yaxis=dict(tickvals=tv2, ticktext=tt2),
    margin=dict(t=50, r=15, b=50, l=70),
)
c2.plotly_chart(fig2, use_container_width=True)

st.header("4. Komposisi Omzet")
a, b = st.columns(2)
dy_ = d[d["Tahun"] == Y]
a.plotly_chart(hbar(f"Omzet per Group ({Y})", S["grp"], "#4C72B0"), use_container_width=True)
b.plotly_chart(hbar(f"Omzet per Department ({Y})", S["dep"], "#55A868"), use_container_width=True)
a.plotly_chart(hbar(f"COGS per Group ({Y})", dy_.groupby("Group")["COGS"].sum(), "#C44E52"), use_container_width=True)
b.plotly_chart(hbar(f"Metode Pembayaran ({Y})", S["pay"], "#DD8452"), use_container_width=True)

st.header("5. Analisis Group, Department, dan Menu")
f1, f2, f3, f4 = st.columns(4)
thn = f1.selectbox("Tahun", sorted(tahun, reverse=True))
dm = d[d["Tahun"] == thn]
grp = f2.selectbox("Group", ["Semua"] + sorted(dm["Group"].unique()))
if grp != "Semua":
    dm = dm[dm["Group"] == grp]
dep = f3.selectbox("Department", ["Semua"] + sorted(dm["Dept"].unique()))
if dep != "Semua":
    dm = dm[dm["Dept"] == dep]
cari = f4.text_input("Cari nama menu")
if cari:
    dm = dm[dm["Menu"].str.contains(cari, case=False, na=False, regex=False)]

if dm.empty:
    st.info("Tidak ada data untuk filter tersebut.")
else:
    menu = (
        dm.groupby("Menu")
        .agg(
            Group=("Group", "first"),
            Dept=("Dept", "first"),
            Qty=("Qty", "sum"),
            Netto=("Netto", "sum"),
            SAD=("SAD", "sum"),
            COGS=("COGS", "sum"),
            Nota=("Nota", "nunique"),
        )
        .reset_index()
    )
    menu["Laba Kotor"] = menu["SAD"] - menu["COGS"]
    menu["Margin %"] = (menu["Laba Kotor"] / menu["SAD"] * 100).where(menu["SAD"] > 0)
    tn = menu["Netto"].sum()
    menu["Kontribusi %"] = menu["Netto"] / tn * 100 if tn else 0.0
    menu = menu.sort_values("Netto", ascending=False)
    ts, tq, tc = menu["SAD"].sum(), menu["Qty"].sum(), menu["COGS"].sum()
    ringkas = [
        ("Sales Netto", rp(tn)),
        ("Item terjual", angka(tq)),
        ("COGS", rp(tc)),
        ("Laba kotor", rp(ts - tc)),
        ("Gross margin", pct((ts - tc) / ts * 100, False) if ts else "n/a"),
    ]
    grid(ringkas)

    t1, t2, t3, t4 = st.tabs(["Treemap (klik untuk drill-down)", "Top Menu", "Tabel Menu", "Tren per Menu"])
    with t1:
        tm = dm[dm["Netto"] > 0]
        if tm.empty:
            st.info("Tidak ada omzet positif pada filter ini.")
        else:
            fig3 = px.treemap(tm, path=["Group", "Dept", "Menu"], values="Netto")
            fig3.update_traces(hovertemplate="%{label}<br>Rp %{value:,.0f}<extra></extra>")
            fig3.update_layout(height=520, margin=dict(t=30, l=10, r=10, b=10))
            st.plotly_chart(fig3, use_container_width=True)
    with t2:
        ukuran = st.selectbox("Urutkan berdasarkan", ["Netto", "Qty", "COGS", "Laba Kotor"])
        n_top = st.slider("Jumlah menu", 5, 30, 15)
        st.plotly_chart(
            hbar(f"Top {n_top} Menu - {ukuran} ({thn})", menu.set_index("Menu")[ukuran], "#8172B3", n_top, ukuran != "Qty"),
            use_container_width=True,
        )
    with t3:
        tampil = menu[["Menu", "Group", "Dept", "Qty", "Netto", "SAD", "COGS", "Laba Kotor", "Margin %", "Kontribusi %", "Nota"]]
        tampil = tampil.rename(columns={"Netto": "Sales Netto", "SAD": "Sales After Disc.", "Nota": "Jumlah Nota"}).reset_index(drop=True)
        fmt = {
            "Qty": angka,
            "Sales Netto": rp,
            "Sales After Disc.": rp,
            "COGS": rp,
            "Laba Kotor": rp,
            "Jumlah Nota": angka,
            "Margin %": lambda v: pct(v, False),
            "Kontribusi %": lambda v: pct(v, False),
        }
        st.dataframe(tampil.style.format(fmt, na_rep="n/a"), use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh tabel (CSV)",
            tampil.to_csv(index=False).encode("utf-8-sig"),
            f"analisis_menu_{thn}.csv",
            "text/csv",
        )
    with t4:
        pm = st.selectbox("Pilih menu", list(menu["Menu"]))
        bmn = (
            d[d["Menu"] == pm]
            .pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
            .reindex(index=range(1, 13), columns=tahun, fill_value=0)
        )
        fig4 = go.Figure()
        for t in tahun:
            y4 = [None if (t == Y and b_ > M) else float(v) for b_, v in zip(range(1, 13), bmn[t])]
            fig4.add_trace(
                go.Scatter(
                    x=BLN,
                    y=y4,
                    mode="lines+markers",
                    name=str(t),
                    line=dict(width=3, color=warna[t]),
                    customdata=[rp(v) for v in bmn[t]],
                    hovertemplate="%{x}<br>%{customdata}<extra>" + str(t) + "</extra>",
                )
            )
        tv4, tt4 = ticks(float(bmn.values.max()))
        fig4.update_layout(
            title=f"Tren Omzet Bulanan - {pm}",
            height=380,
            legend=dict(orientation="h", y=-0.2),
            yaxis=dict(tickvals=tv4, ticktext=tt4, rangemode="tozero"),
            margin=dict(t=50, r=15, b=60, l=70),
        )
        st.plotly_chart(fig4, use_container_width=True)

st.header("6. Rincian Bulanan")
ukur = st.radio("Tampilkan", ["Sales Netto", "COGS", "Laba Kotor"], horizontal=True)
nilai = d["SAD"] - d["COGS"] if ukur == "Laba Kotor" else d["COGS" if ukur == "COGS" else "Netto"]
bm = (
    d.assign(Nilai=nilai)
    .pivot_table(index="Bulan", columns="Tahun", values="Nilai", aggfunc="sum", fill_value=0)
    .reindex(index=range(1, 13), columns=tahun, fill_value=0)
)
tabel = pd.DataFrame(
    {
        str(t): [
            ("-" if (t == Y and i + 1 > M) else rp(bm[t].iloc[i]) + (" *" if (t == Y and i + 1 == M and partial) else ""))
            for i in range(12)
        ]
        for t in tahun
    },
    index=BLN,
)
tabel.loc["TOTAL"] = [rp(bm[t].sum()) for t in tahun]
tabel.index.name = "Bulan"
st.dataframe(tabel, use_container_width=True)

st.header("7. Peringkat Seluruh Store")
baris = [
    {"StoreCode": s_, **{str(t): rp(h["tot"][t]) for t in tahun}, f"Kontribusi {Y}": pct(h["tot"][Y] / tot_all * 100, False) if tot_all else "n/a", "Growth YTD": pct(h["ytd_g"])}
    for s_, h in rank
]
baris.append({"StoreCode": "TOTAL", **{str(t): rp(SA["tot"][t]) for t in tahun}, f"Kontribusi {Y}": "100%", "Growth YTD": pct(SA["ytd_g"])})
st.dataframe(pd.DataFrame(baris), use_container_width=True, hide_index=True)

cat = "Omzet = Sales Netto (termasuk service charge dan pajak). Pertumbuhan YTD membandingkan rentang tanggal yang sama tahun sebelumnya. "
cat += "Gross margin = (Sales After Disc. - COGS) / Sales After Disc. "
if partial:
    cat += f"* Bulan {BLN[M - 1]} {Y} belum penuh (data s.d. tanggal {Dd}). "
if df.attrs.get("dilewati"):
    cat += f"{angka(df.attrs['dilewati'])} baris dilewati karena tanggal/angka tidak terbaca."
st.caption(cat)
