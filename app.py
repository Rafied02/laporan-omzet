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

# Konfigurasi Akses Keamanan Sederhana (Poin 8)
PASSWORD_RAHASIA = "helios2026" # Ubah sesuai kebutuhan

st.set_page_config(page_title="Laporan Kinerja Omzet - HELIOS", layout="wide")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

with st.sidebar:
    st.header("Autentikasi Akses")
    if not st.session_state["authenticated"]:
        pwd_input = st.text_input("Masukkan Password Dashboard", type="password")
        if st.button("Masuk"):
            if pwd_input == PASSWORD_RAHASIA:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Password salah.")
        st.stop()
    else:
        if st.button("Keluar (Lock)"):
            st.session_state["authenticated"] = False
            st.rerun()

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

def url_csv(u):
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
    df["DayOfWeek"] = df["Tgl"].dt.day_name()
    return df

@st.cache_data(ttl=300, show_spinner="Memuat data...")
def muat(sumber, isi=None):
    src = io.BytesIO(isi) if isi is not None else sumber
    raw = pd.read_csv(src, dtype=str)
    if raw.shape[1] == 1 and isi is not None:
        raw = pd.read_csv(io.BytesIO(isi), dtype=str, sep=";")
    return bersihkan(raw)

sumber = CSV_URL
try:
    sumber = sumber or st.secrets.get("CSV_URL", "")
except Exception:
    pass

sumber = url_csv(sumber)

with st.sidebar:
    st.header("Filter & Sumber Data")
    file = st.file_uploader("Unggah CSV Manual", type=["csv", "txt"])
    target_file = st.file_uploader("Unggah Target Omzet (Opsional CSV)", type=["csv"])
    if st.button("Muat ulang data"):
        st.cache_data.clear()
        st.rerun()

if file is not None:
    try:
        df = muat("upload", file.getvalue())
    except Exception as exc:
        st.error(f"Gagal membaca file upload: {exc}")
        st.stop()
elif sumber:
    try:
        df = muat(sumber)
    except Exception as e:
        st.error(f"Gagal memuat dari Google Sheets: {e}")
        st.stop()
else:
    st.title("HELIOS - Laporan Kinerja Omzet Penjualan")
    st.info("Isi CSV_URL atau unggah file CSV di sidebar.")
    st.stop()

if df.empty:
    st.error("Tidak ada baris valid.")
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
    
    st.markdown("---")
    st.subheader("Filter Periode Khusus (Poin 2)")
    mode_periode = st.radio("Mode Periode", ["YTD Otomatis", "Rentang Tanggal Kustom"])
    if mode_periode == "Rentang Tanggal Kustom":
        min_date = df["Tgl"].min().date()
        max_date = df["Tgl"].max().date()
        tgl_mulai, tgl_selesai = st.date_input("Pilih Rentang", [min_date, max_date], min_value=min_date, max_value=max_date)
    else:
        tgl_mulai, tgl_selesai = None, None

# Filter data berdasarkan kustom tanggal jika dipilih
if mode_periode == "Rentang Tanggal Kustom" and isinstance(tgl_mulai, type(min_date)) and isinstance(tgl_selesai, type(max_date)):
    d_filtered = df[(df["Tgl"].dt.date >= tgl_mulai) & (df["Tgl"].dt.date <= tgl_selesai)]
else:
    d_filtered = df if pilih == "SEMUA STORE" else df[df["Store"] == pilih]

d = df if pilih == "SEMUA STORE" else df[df["Store"] == pilih]
nama = "Seluruh Store" if pilih == "SEMUA STORE" else f"Store {pilih}"

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

def hitung(d_set, tahun, Y, M, Dd, partial):
    bul = (
        d_set.groupby(["Tahun", "Bulan"], as_index=False)
        .agg(Netto=("Netto", "sum"))
        .pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
        .reindex(index=range(1, TOTAL_MONTHS + 1), columns=tahun, fill_value=0)
    )
    tot = bul.sum()
    pt = (
        d_set.groupby("Tahun")
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
    ytd_now = float(d_set.loc[d_set["Tahun"] == Y, "Netto"].sum())
    m_prev = (d_set["Tahun"] == Y - 1) & ((d_set["Bulan"] < M) | ((d_set["Bulan"] == M) & (d_set["Hari"] <= Dd)))
    ytd_prev = float(d_set.loc[m_prev, "Netto"].sum())
    dy = d_set[d_set["Tahun"] == Y]
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

S = hitung(d, tahun, Y, M, Dd, partial)
SA = hitung(df, tahun, Y, M, Dd, partial)

rank = []
for s_ in stores:
    h = hitung(df[df["Store"] == s_], tahun, Y, M, Dd, partial)
    rank.append((s_, h))
rank.sort(key=lambda x: x[1]["tot"][Y], reverse=True)
tot_all = SA["tot"][Y]
if pilih == "SEMUA STORE":
    kon, sub_kon = "100%", f"{len(stores)} store"
else:
    posisi = [r[0] for r in rank].index(pilih) + 1
    kon = pct(S["tot"][Y] / tot_all * 100, False) if tot_all else "n/a"
    sub_kon = f"Peringkat {posisi} dari {len(stores)} store"

st.markdown(
    '<div class="banner"><h1>HELIOS - Laporan Kinerja Omzet Penjualan</h1><p>'
    f"{nama} | Data {df['Tgl'].min():%d/%m/%Y} s.d. {akhir:%d/%m/%Y} | {len(stores)} store | "
    "Basis omzet: Sales Netto</p></div>",
    unsafe_allow_html=True,
)

# ============================================================
# 1. PANEL KUALITAS DATA
# ============================================================
st.header("1. Panel Kualitas Data & Validasi")
with st.expander("Lihat Audit Kelengkapan Data", expanded=False):
    col_q1, col_q2 = st.columns(2)
    with col_q1:
        st.markdown("**Jumlah Baris Data per Bulan (Semua Store):**")
        df_audit = df.groupby(["Tahun", "Bulan"]).agg(Jumlah_Baris=("Netto", "count"), Total_Omzet=("Netto", "sum")).reset_index()
        st.dataframe(df_audit, use_container_width=True, hide_index=True)
    with col_q2:
        st.markdown("**Peringatan & Catatan Sistem:**")
        warnings = []
        for t_ in tahun:
            min_t_date = df[df["Tahun"] == t_]["Tgl"].min()
            if min_t_date.day > 1 or min_t_date.month > 1:
                warnings.append(f"• Tahun `{t_}` dimulai sejak `{min_t_date:%d %b %Y}` (data tidak penuh 1 tahun penuh).")
        
        # Deteksi anomali drop tajam
        monthly_totals = df.groupby(["Tahun", "Bulan"])["Netto"].sum()
        mean_omzet = monthly_totals.mean()
        for idx, val in monthly_totals.items():
            if val < mean_omzet * 0.3 and not (idx[0] == Y and idx[1] == M):
                warnings.append(f"• Anomali Terdeteksi: Bulan `{idx[1]}/{idx[0]}` memiliki omzet jauh di bawah rata-rata.")
                
        if df.attrs.get("dilewati"):
            warnings.append(f"• Terdapat `{df.attrs['dilewati']}` baris diabaikan karena format tanggal/angka salah.")
            
        if warnings:
            for w in warnings:
                st.warning(w)
        else:
            st.success("Tidak ada anomali atau celah data kritikal terdeteksi.")

# ============================================================
# 2. RINGKASAN EKSEKUTIF & KPI
# ============================================================
st.header("2. Ringkasan Eksekutif & KPI")
pt, tot = S["pt"], S["tot"]

def build_executive_summary(S, nama, tahun, Y, P, M, Dd, pilih, kon, sub_kon):
    n = f"**{nama}** mencatat total omzet (Sales Netto) **{rp(S['tot'].sum())}** pada periode {tahun[0]}-{Y}. "
    n += f"Sampai dengan tanggal {Dd}/{M}/{Y}, omzet tahun berjalan sebesar **{rp(S['ytd_now'])}**"
    if S["ytd_g"] is not None:
        direction = "naik" if S["ytd_g"] >= 0 else "turun"
        n += f", {direction} **{pct(abs(S['ytd_g']), False)}** dibanding rentang tanggal yang sama tahun {P}"
    n += ". "
    if S["hi"]:
        n += f"Omzet bulanan tertinggi terjadi pada {BLN[S['hi'][1]-1]} {S['hi'][0]} ({rp(S['hi'][2])}). "
    if pilih != "SEMUA STORE":
        n += f"Store ini berkontribusi {kon} dari total omzet {Y} ({sub_kon.lower()})."
    return n

summary_text = build_executive_summary(S, nama, tahun, Y, P, M, Dd, pilih, kon, sub_kon)
st.markdown('<div class="card narasi">' + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", summary_text) + "</div>", unsafe_allow_html=True)

k = [
    ("Total omzet periode", rp(tot.sum()), None, f"{tahun[0]} - {Y}"),
    (f"Omzet {Y} (YTD s.d. {Dd}/{M})", rp(S["ytd_now"]), None, f"{P}: {rp(S['ytd_prev'])}"),
    (f"Pertumbuhan YTD vs {P}", pct(S["ytd_g"]), None, "Rentang tanggal sama"),
]
for t in tahun[1:]:
    k.append((f"Pertumbuhan {t} vs {t - 1}", pct(growth(tot[t], tot[t - 1])), None, f"Omzet {t}: {singkat(tot[t])}"))
k += [
    (f"Rata-rata omzet bulanan {Y}", rp(S["rb"][Y]), None, f"{P}: {singkat(S['rb'].get(P, 0))}"),
    (f"Jumlah transaksi {Y}", angka(annual_transaction_count(pt, Y)), None, f"Nota terhitung"),
    (f"Laba kotor {Y}", rp(gross_profit_for_year(pt, Y)), None, f"Margin: {pct(gross_margin_for_year(pt, Y), False)}"),
]
grid(k)

# ============================================================
# 3. ANALISIS TREN & POLA WAKTU (Poin 5)
# ============================================================
st.header("3. Analisis Tren & Pola Waktu")
tab_t1, tab_t2 = st.tabs(["Tren Bulanan", "Analisis Hari (Weekday vs Weekend)"])
with tab_t1:
    c1, c2 = st.columns([2.4, 1])
    fig = go.Figure()
    for t in tahun:
        y_vals = [None if (t == Y and b > M) else float(v) for b, v in zip(range(1, 13), S["bul"][t])]
        fig.add_trace(
            go.Scatter(
                x=BLN, y=y_vals, mode="lines+markers", name=str(t),
                line=dict(width=3, color=warna[t]),
                customdata=[rp(v) for v in S["bul"][t]],
                hovertemplate="%{x}<br>%{customdata}<extra>" + str(t) + "</extra>",
            )
        )
    tv, tt = ticks(float(S["bul"].values.max()))
    fig.update_layout(title=f"Tren Omzet Bulanan - {nama}", height=380, yaxis=dict(tickvals=tv, ticktext=tt, rangemode="tozero"))
    c1.plotly_chart(fig, use_container_width=True)

    vals = [float(tot[t]) for t in tahun]
    tv2, tt2 = ticks(max(vals))
    fig2 = go.Figure(go.Bar(x=[str(t) for t in tahun], y=vals, marker_color=[warna[t] for t in tahun], text=[singkat(v) for v in vals], textposition="outside"))
    fig2.update_layout(title="Total Omzet per Tahun", height=380, yaxis=dict(tickvals=tv2, ticktext=tt2))
    c2.plotly_chart(fig2, use_container_width=True)

with tab_t2:
    st.markdown("### Performa Berdasarkan Hari dalam Seminggu")
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_df = d[d["Tahun"] == Y].groupby("DayOfWeek")["Netto"].sum().reindex(dow_order).reset_index()
    fig_dow = px.bar(dow_df, x="DayOfWeek", y="Netto", title=f"Distribusi Omzet Berdasarkan Hari ({Y})", text_auto=".2s")
    fig_dow.update_layout(xaxis_title="Hari", yaxis_title="Total Omzet (Rp)")
    st.plotly_chart(fig_dow, use_container_width=True)

# ============================================================
# 4. TARGET VS REALISASI & ANALISIS DISKON (Poin 3 & 6)
# ============================================================
st.header("4. Target vs Realisasi & Analisis Komersial")
col_s1, col_s2 = st.columns(2)

with col_s1:
    st.subheader("Pencapaian Target Bulanan")
    # Jika user tidak mengunggah file target, buat target simulasi berbasis rata-rata growth 10%
    bulan_aktif_df = pd.DataFrame({"Bulan": range(1, 13), "NamaBulan": BLN})
    bulan_aktif_df["Realisasi"] = [float(S["bul"].loc[b, Y]) for b in range(1, 13)]
    bulan_aktif_df["Target (Simulasi +10%)"] = bulan_aktif_df["Realisasi"] * 1.1
    bulan_aktif_df["Pencapaian %"] = (bulan_aktif_df["Realisasi"] / bulan_aktif_df["Target (Simulasi +10%)"] * 100).round(1)
    st.dataframe(bulan_aktif_df[["NamaBulan", "Target (Simulasi +10%)", "Realisasi", "Pencapaian %"]].style.format({"Target (Simulasi +10%)": rp, "Realisasi": rp, "Pencapaian %": lambda x: f"{x}%"}), use_container_width=True, hide_index=True)

with col_s2:
    st.subheader("Analisis Metode Pembayaran & Diskon")
    pay_df = d[d["Tahun"] == Y].groupby("Payment")["Netto"].sum().reset_index()
    fig_pay = px.pie(pay_df, names="Payment", values="Netto", title=f"Komposisi Pembayaran ({Y})", hole=0.4)
    st.plotly_chart(fig_pay, use_container_width=True)

# ============================================================
# 5. MENU ENGINEERING (Poin 4)
# ============================================================
st.header("5. Analisis Menu & Menu Engineering")
dm_menu = d[d["Tahun"] == Y]
if not dm_menu.empty:
    menu_eng = dm_menu.groupby("Menu").agg(Qty=("Qty", "sum"), Netto=("Netto", "sum"), SAD=("SAD", "sum"), COGS=("COGS", "sum")).reset_index()
    menu_eng["LabaKotor"] = menu_eng["SAD"] - menu_eng["COGS"]
    menu_eng["Margin"] = (menu_eng["LabaKotor"] / menu_eng["SAD"] * 100).fillna(0)
    
    # Kriteria kuadran Menu Engineering sederhana berdasarkan median Qty dan Margin
    med_qty = menu_eng["Qty"].median()
    med_margin = menu_eng["Margin"].median()
    
    def classify_menu(row):
        if row["Qty"] >= med_qty and row["Margin"] >= med_margin:
            return "Star (Bintang)"
        elif row["Qty"] >= med_qty and row["Margin"] < med_margin:
            return "Workhorse (Kuda Kerja)"
        elif row["Qty"] < med_qty and row["Margin"] >= med_margin:
            return "Puzzle (Tanda Tanya)"
        else:
            return "Dog (Beban)"
            
    menu_eng["Klasifikasi"] = menu_eng.apply(classify_menu, axis=1)
    
    tab_m1, tab_m2 = st.tabs(["Matriks Menu Engineering", "Tabel Rinci Menu"])
    with tab_m1:
        fig_eng = px.scatter(menu_eng, x="Qty", y="Margin", color="Klasifikasi", hover_name="Menu", size="Netto", title="Matriks Menu Engineering (Popularitas vs Margin)")
        fig_eng.add_hline(y=med_margin, line_dash="dash", annotation_text="Median Margin")
        fig_eng.add_vline(x=med_qty, line_dash="dash", annotation_text="Median Qty")
        st.plotly_chart(fig_eng, use_container_width=True)
    with tab_m2:
        st.dataframe(menu_eng.sort_values("Netto", ascending=False), use_container_width=True, hide_index=True)

# ============================================================
# 6. EKSPOR LAPORAN EXCEL (Poin 7)
# ============================================================
st.header("6. Ekspor Laporan Lengkap")
output_excel = io.BytesIO()
with pd.ExcelWriter(output_excel, engine="xlsxwriter") as writer:
    S["bul"].to_excel(writer, sheet_name="Tren Bulanan")
    pd.DataFrame(baris).to_excel(writer, sheet_name="Ranking Store", index=False)
    if not dm_menu.empty:
        menu_eng.to_excel(writer, sheet_name="Analisis Menu", index=False)

st.download_button(
    label="📥 Unduh Laporan Lengkap (Excel .xlsx)",
    data=output_excel.getvalue(),
    file_name=f"Laporan_Kinerja_Omzet_{Y}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.caption("HELIOS Business Intelligence Dashboard — Dirancang khusus untuk audit keuangan & operasional F&B.")
