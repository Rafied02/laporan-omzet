"""
Dashboard Laporan Omzet (Python + Streamlit)
Jalankan : streamlit run reporthnp.py
Install  : pip install streamlit pandas plotly
Sumber   : link Google Sheets "Publish to web" (CSV) atau unggah CSV manual.
Omzet    : kolom "Sales Netto"
"""
import hmac
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

# Password (opsional). Kosongkan jika tidak perlu. Di Streamlit Cloud lebih aman lewat Secrets: APP_PASSWORD = "..."
APP_PASSWORD = ""

BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
PAL = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]
KOLOM = {"storecode": "Store", "transdate": "Tgl", "sales netto": "Netto", "receiptno": "Resi",
         "transqty": "Qty", "sales after disc.": "SAD", "service charge": "SC", "transbruto": "Bruto",
         "cogs": "COGS", "group": "Group", "department": "Dept", "payment": "Payment", "catname": "Menu"}
ANGKA = ["Qty", "SAD", "SC", "Tax", "Bruto", "COGS"]
TEKS = ["Group", "Dept", "Payment", "Menu"]

# Tema terang: file .streamlit/config.toml dibuat otomatis jika belum ada (restart Streamlit sekali)
_cfg = Path(".streamlit/config.toml")
if not _cfg.exists():
    try:
        _cfg.parent.mkdir(exist_ok=True)
        _cfg.write_text('[theme]\nbase = "light"\nprimaryColor = "#1f4e8c"\nbackgroundColor = "#f4f6fa"\n'
                        'secondaryBackgroundColor = "#ffffff"\ntextColor = "#1d2433"\n', encoding="utf-8")
    except Exception:
        pass

st.set_page_config(page_title="Laporan Kinerja Omzet", layout="wide")

st.markdown("""<style>
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
</style>""", unsafe_allow_html=True)


def kartu(l, v, cap=""):
    kelas = "up" if v.startswith("+") else "down" if (v.startswith("-") and "%" in v) else ""
    return f'<div class="kpi"><div class="l">{l}</div><div class="v {kelas}">{v}</div><div class="s">{cap or "&nbsp;"}</div></div>'


HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def cek_data(df, akhir):
    msg = []
    awal = df["Tgl"].min()
    if awal > pd.Timestamp(awal.year, 1, 31):
        msg.append(f"Data tahun {awal.year} baru dimulai {awal:%d/%m/%Y}, sehingga tahun tersebut tidak penuh. "
                   "Jangan bandingkan total tahunannya langsung.")
    per = df.assign(P=df["Tgl"].dt.to_period("M"))
    for s_, g in per.groupby("Store"):
        mx = g["Tgl"].max()
        if mx < akhir - pd.Timedelta(days=7):
            msg.append(f"Store {s_}: data terakhir {mx:%d/%m/%Y}, tertinggal dari data terbaru ({akhir:%d/%m/%Y}).")
        bul = g.groupby("P")["Netto"].sum()
        bul = bul.reindex(pd.period_range(bul.index.min(), bul.index.max(), freq="M"), fill_value=0)
        for p_, v in bul.items():
            if v <= 0:
                msg.append(f"Store {s_}: tidak ada omzet pada {p_.strftime('%m/%Y')}.")
        for i in range(3, len(bul)):
            ref = bul.iloc[i - 3:i]
            ref = ref[ref > 0]
            p_ = bul.index[i]
            if p_ == akhir.to_period("M") and akhir.day < akhir.days_in_month:
                continue
            if len(ref) >= 2 and 0 < bul.iloc[i] < 0.4 * ref.mean():
                msg.append(f"Store {s_}: omzet {p_.strftime('%m/%Y')} hanya {bul.iloc[i] / ref.mean() * 100:.0f}% dari rata-rata 3 bulan sebelumnya.")
    return msg


def metrik(x):
    sad, cg, n = x["SAD"].sum(), x["COGS"].sum(), x["Nota"].nunique()
    return {"Sales Netto": x["Netto"].sum(), "Jumlah nota": n, "Item terjual": x["Qty"].sum(),
            "Rata-rata per nota": x["Netto"].sum() / n if n else 0, "COGS": cg, "Laba kotor": sad - cg,
            "Gross margin %": (sad - cg) / sad * 100 if sad else None, "Diskon": max(0, x["Bruto"].sum() - sad),
            "Bruto": x["Bruto"].sum(), "SAD": sad}


def cek_password():
    pw = APP_PASSWORD
    try:
        pw = st.secrets.get("APP_PASSWORD", "") or pw
    except Exception:
        pass
    if not pw or st.session_state.get("ok"):
        return
    st.markdown('<div class="banner"><h1>Laporan Kinerja Omzet Penjualan</h1><p>Masukkan password untuk melanjutkan</p></div>',
                unsafe_allow_html=True)
    x = st.text_input("Password", type="password")
    if x:
        if hmac.compare_digest(x, pw):
            st.session_state["ok"] = True
            st.rerun()
        st.error("Password salah.")
    st.stop()


def grid(items):
    st.markdown('<div class="kpis">' + "".join(kartu(i[0], i[1], i[3] if len(i) > 3 else "") for i in items) + "</div>",
                unsafe_allow_html=True)


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


# ------------------------------------------------------------ data
def ke_angka(s):
    s = s.fillna("").astype(str).str.replace(r"[^0-9,.\-]", "", regex=True)
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
def hitung(d, tahun, Y, M, Dd, partial):
    bul = (d.pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
           .reindex(index=range(1, 13), columns=tahun, fill_value=0))
    tot = bul.sum()
    pt = (d.groupby("Tahun").agg(trn=("Nota", "nunique"), qty=("Qty", "sum"), sad=("SAD", "sum"),
                                 sc=("SC", "sum"), tax=("Tax", "sum"), bruto=("Bruto", "sum"), cogs=("COGS", "sum"))
          .reindex(tahun, fill_value=0))
    sel = [(t, b, float(bul.loc[b, t])) for t in tahun for b in range(1, 13)
           if bul.loc[b, t] > 0 and not (t == Y and b == M and partial)]
    aktif = {t: sum(1 for s in sel if s[0] == t) for t in tahun}
    ytd_now = float(d.loc[d["Tahun"] == Y, "Netto"].sum())
    m_prev = (d["Tahun"] == Y - 1) & ((d["Bulan"] < M) | ((d["Bulan"] == M) & (d["Hari"] <= Dd)))
    ytd_prev = float(d.loc[m_prev, "Netto"].sum())
    dy = d[d["Tahun"] == Y]
    return {
        "bul": bul, "tot": tot, "pt": pt,
        "rb": {t: (tot[t] / aktif[t] if aktif[t] else 0) for t in tahun},
        "hi": max(sel, key=lambda s: s[2]) if sel else None,
        "lo": min(sel, key=lambda s: s[2]) if sel else None,
        "ytd_now": ytd_now, "ytd_prev": ytd_prev, "ytd_g": growth(ytd_now, ytd_prev),
        "grp": dy.groupby("Group")["Netto"].sum(), "dep": dy.groupby("Dept")["Netto"].sum(),
        "pay": dy.groupby("Payment")["Netto"].sum(), "menu": dy.groupby("Menu")["Netto"].sum(),
    }


def hbar(judul, serie, warna, n=10, uang=True):
    s = serie.sort_values(ascending=False).head(n)[::-1]
    fmt = rp if uang else angka
    fig = go.Figure(go.Bar(x=s.values, y=list(s.index), orientation="h", marker_color=warna,
                           text=[singkat(v) for v in s.values], textposition="outside", cliponaxis=False,
                           customdata=[fmt(v) for v in s.values], hovertemplate="%{y}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title=judul, height=max(340, 26 * n + 90), margin=dict(t=45, r=60, b=20, l=10),
                      xaxis=dict(showticklabels=False), yaxis=dict(automargin=True))
    return fig


def lbl(x):
    return f"{BLN[x[1] - 1]} {x[0]}" if x else "-"


def rata(ms, key):
    v = [m[key] for m in ms if m[key] is not None]
    return sum(v) / len(v) if v else None


def laporan_harian(df, pilih, akhir, stores):
    semua = pilih == "SEMUA STORE"
    dd = df if semua else df[df["Store"] == pilih]
    nama = "Seluruh Store" if semua else f"Store {pilih}"
    st.markdown(f'<div class="banner"><h1>Laporan Harian</h1><p>{nama} | Data terbaru s.d. {akhir:%d/%m/%Y}</p></div>',
                unsafe_allow_html=True)
    tgl = st.date_input("Tanggal laporan", value=akhir.date(), min_value=df["Tgl"].min().date(), max_value=akhir.date())
    t = pd.Timestamp(tgl)
    st.subheader(f"{HARI[t.dayofweek]}, {t:%d/%m/%Y}")
    if t.date() == akhir.date():
        st.caption("Ini hari terakhir di data. Pastikan data hari tersebut sudah lengkap sebelum laporan dibagikan.")

    def ringkas(x):
        hist = [metrik(x[x["Tgl"] == t - pd.Timedelta(days=7 * i)]) for i in range(1, 5)]
        return metrik(x[x["Tgl"] == t]), hist[0], [h for h in hist if h["Jumlah nota"] > 0]

    awal_b = t.replace(day=1)
    pb_end = awal_b - pd.Timedelta(days=1)
    pb_start = pb_end.replace(day=1)
    pb_sd = pb_start.replace(day=min(t.day, pb_end.day))

    def mtd_of(x):
        return (x.loc[(x["Tgl"] >= awal_b) & (x["Tgl"] <= t), "Netto"].sum(),
                x.loc[(x["Tgl"] >= pb_start) & (x["Tgl"] <= pb_sd), "Netto"].sum())

    m, mw, ada = ringkas(dd)
    rt = rata(ada, "Sales Netto")
    g_mw, g_rt = growth(m["Sales Netto"], mw["Sales Netto"]), (growth(m["Sales Netto"], rt) if rt else None)
    if m["Jumlah nota"] == 0:
        st.warning("Belum ada transaksi pada tanggal ini.")

    st.header("1. Ringkasan Hari Ini")
    kh = []
    for nm_, fm in [("Sales Netto", rp), ("Jumlah nota", angka), ("Rata-rata per nota", rp), ("Item terjual", angka),
                    ("Laba kotor", rp), ("Diskon", rp)]:
        r_ = rata(ada, nm_)
        kh.append((nm_, fm(m[nm_]), None,
                   f"Minggu lalu: {fm(mw[nm_])} ({pct(growth(m[nm_], mw[nm_]))})<br>"
                   f"Rata-rata 4 minggu: {fm(r_) if r_ is not None else 'n/a'} ({pct(growth(m[nm_], r_)) if r_ else 'n/a'})"))
    kh.append(("Gross margin", pct(m["Gross margin %"], False), None, f"Minggu lalu: {pct(mw['Gross margin %'], False)}"))
    grid(kh)

    st.header("2. Akumulasi Bulan Berjalan (MTD)")
    mtd, mtd_p = mtd_of(dd)
    est = mtd / t.day * t.days_in_month
    grid([(f"MTD {BLN[t.month - 1]} {t.year}", rp(mtd), None, f"Sampai tanggal {t.day}"),
          (f"{BLN[pb_start.month - 1]} {pb_start.year} s.d. tanggal sama", rp(mtd_p), None, ""),
          ("Pertumbuhan MTD", pct(growth(mtd, mtd_p)), None, "Dibanding bulan lalu"),
          ("Estimasi omzet akhir bulan", rp(est), None, "Perkiraan kasar dari rata-rata harian")])

    def peringatan(x, label):
        out = []
        m_, _, ada_ = ringkas(x)
        r_ = rata(ada_, "Sales Netto")
        if m_["Jumlah nota"] == 0:
            if ada_:
                out.append(f"{label}: belum ada transaksi pada tanggal ini, padahal biasanya ada.")
            return out
        if r_ and m_["Sales Netto"] < 0.7 * r_:
            out.append(f"{label}: omzet {rp(m_['Sales Netto'])}, turun {pct(abs(growth(m_['Sales Netto'], r_)), False)} dari rata-rata hari yang sama 4 minggu terakhir.")
        if ada_:
            dp = sum(a["Diskon"] for a in ada_) / max(sum(a["Bruto"] for a in ada_), 1)
            dn = m_["Diskon"] / m_["Bruto"] if m_["Bruto"] else 0
            if dn > 1.5 * dp and dn - dp >= 0.02:
                out.append(f"{label}: diskon {pct(dn * 100, False)} dari bruto, di atas biasanya ({pct(dp * 100, False)}).")
            cp = sum(a["COGS"] for a in ada_) / max(sum(a["SAD"] for a in ada_), 1)
            cn = m_["COGS"] / m_["SAD"] if m_["SAD"] else 0
            if cn - cp >= 0.05:
                out.append(f"{label}: COGS {pct(cn * 100, False)} dari Sales After Disc., di atas biasanya ({pct(cp * 100, False)}).")
        return out

    st.header("3. Peringatan")
    notif = []
    for s_ in (stores if semua else [pilih]):
        notif += peringatan(dd[dd["Store"] == s_], f"Store {s_}")
    if notif:
        st.warning("\n".join("- " + n_ for n_ in notif))
    else:
        st.success("Tidak ada peringatan untuk tanggal ini.")
    st.caption("Peringatan: omzet di bawah 70% rata-rata hari yang sama 4 minggu terakhir, diskon jauh di atas biasanya, "
               "COGS naik 5 poin persentase atau lebih, atau belum ada data.")

    baris_h = []
    if semua:
        st.header("4. Per Store")
        for s_ in stores:
            xs = dd[dd["Store"] == s_]
            ms, msw, adas = ringkas(xs)
            rs = rata(adas, "Sales Netto")
            a_, b_ = mtd_of(xs)
            baris_h.append({"StoreCode": s_, "Sales Netto": ms["Sales Netto"],
                            "vs Minggu Lalu": growth(ms["Sales Netto"], msw["Sales Netto"]),
                            "vs Rata-rata 4 Minggu": growth(ms["Sales Netto"], rs) if rs else None,
                            "Nota": ms["Jumlah nota"], "Rata-rata per Nota": ms["Rata-rata per nota"],
                            "Diskon %": (ms["Diskon"] / ms["Bruto"] * 100) if ms["Bruto"] else None,
                            "MTD": a_, "MTD vs Bulan Lalu": growth(a_, b_)})
        th = pd.DataFrame(baris_h).sort_values("Sales Netto", ascending=False)
        st.dataframe(th.style.format({"Sales Netto": rp, "vs Minggu Lalu": pct, "vs Rata-rata 4 Minggu": pct, "Nota": angka,
                                      "Rata-rata per Nota": rp, "Diskon %": lambda v: pct(v, False), "MTD": rp,
                                      "MTD vs Bulan Lalu": pct}, na_rep="n/a"), use_container_width=True, hide_index=True)

    if m["Jumlah nota"] > 0:
        st.header("5. Rincian Hari Ini" if semua else "4. Rincian Hari Ini")
        dday = dd[dd["Tgl"] == t]
        dday = dday.assign(Diskon=(dday["Bruto"] - dday["SAD"]).clip(lower=0))
        c1, c2 = st.columns(2)
        c1.plotly_chart(hbar("Omzet per Group", dday.groupby("Group")["Netto"].sum(), "#4C72B0"), use_container_width=True)
        c2.plotly_chart(hbar("Metode Pembayaran", dday.groupby("Payment")["Netto"].sum(), "#DD8452"), use_container_width=True)
        c1.plotly_chart(hbar("10 Menu Terlaris", dday.groupby("Menu")["Netto"].sum(), "#8172B3"), use_container_width=True)
        c2.plotly_chart(hbar("10 Menu Paling Banyak Didiskon", dday.groupby("Menu")["Diskon"].sum(), "#C44E52"), use_container_width=True)

    st.header("Teks Ringkasan (salin untuk WhatsApp/Telegram)")
    tk = [f"LAPORAN HARIAN - {nama}", f"{HARI[t.dayofweek]}, {t:%d/%m/%Y}", "",
          f"Sales Netto: {rp(m['Sales Netto'])} ({pct(g_mw)} vs minggu lalu; {pct(g_rt)} vs rata-rata 4 minggu)",
          f"Nota: {angka(m['Jumlah nota'])} | Rata-rata per nota: {rp(m['Rata-rata per nota'])}",
          f"Diskon: {rp(m['Diskon'])} | Laba kotor: {rp(m['Laba kotor'])} (margin {pct(m['Gross margin %'], False)})",
          f"MTD: {rp(mtd)} ({pct(growth(mtd, mtd_p))} vs bulan lalu) | Estimasi akhir bulan: {rp(est)}"]
    if semua:
        tk += ["", "Per store:"] + [f"- {r_['StoreCode']}: {rp(r_['Sales Netto'])} ({pct(r_['vs Rata-rata 4 Minggu'])} vs rata-rata)"
                                    for r_ in sorted(baris_h, key=lambda z: -z["Sales Netto"])]
    if notif:
        tk += ["", "Perlu perhatian:"] + ["- " + n_ for n_ in notif]
    st.code("\n".join(tk), language=None)


# ------------------------------------------------------------ SUMBER DATA
cek_password()
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
    df = muat("upload", file.getvalue())
elif sumber:
    try:
        df = muat(sumber)
    except Exception as e:
        st.error(f"Gagal memuat dari Google Sheets: {e}\nAnda bisa mengunggah CSV manual di sidebar.")
        st.stop()
else:
    st.title("Laporan Kinerja Omzet Penjualan")
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
    halaman = st.radio("Halaman", ["Laporan Bulanan", "Laporan Harian"])
    pilih = st.selectbox("StoreCode", ["SEMUA STORE"] + stores)

if halaman == "Laporan Harian":
    laporan_harian(df, pilih, akhir, stores)
    st.stop()

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
    '<div class="banner"><h1>Laporan Kinerja Omzet Penjualan</h1><p>'
    f"{nama} | Data {df['Tgl'].min():%d/%m/%Y} s.d. {akhir:%d/%m/%Y} | {len(stores)} store | "
    "Basis omzet: Sales Netto | Diperbarui otomatis tiap 5 menit</p></div>", unsafe_allow_html=True)

pesan = cek_data(df, akhir)
if pesan:
    st.warning(f"Kualitas data: ada {len(pesan)} catatan yang perlu dicek sebelum laporan dibagikan.")
else:
    st.success("Kualitas data: tidak ada catatan.")
with st.expander("Detail kualitas data"):
    for m_ in pesan[:25]:
        st.write("- " + m_)
    if len(pesan) > 25:
        st.caption(f"... dan {len(pesan) - 25} catatan lain")
    hm = df.assign(P=df["Tgl"].dt.strftime("%Y-%m")).groupby(["Store", "P"])["Tgl"].nunique().unstack(fill_value=0)
    fig_h = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=list(hm.index), colorscale="Blues",
                                 hovertemplate="%{y}<br>%{x}: %{z} hari ada transaksi<extra></extra>"))
    fig_h.update_layout(title="Jumlah hari yang memiliki transaksi per store per bulan",
                        height=max(220, 60 * len(hm) + 120), margin=dict(t=50, r=15, b=40, l=10))
    st.plotly_chart(fig_h, use_container_width=True)

pt, tot = S["pt"], S["tot"]
mg = lambda t: ((pt.loc[t, "sad"] - pt.loc[t, "cogs"]) / pt.loc[t, "sad"] * 100) if pt.loc[t, "sad"] else None
trn = lambda t: int(pt.loc[t, "trn"]) if t in pt.index else 0
cogs_pct = lambda t: (pt.loc[t, "cogs"] / pt.loc[t, "sad"] * 100) if pt.loc[t, "sad"] else None
laba = lambda t: pt.loc[t, "sad"] - pt.loc[t, "cogs"]

st.header("1. Ringkasan Eksekutif")
n = f"**{nama}** mencatat total omzet (Sales Netto) **{rp(tot.sum())}** pada periode {tahun[0]}-{Y}. "
n += f"Sampai dengan tanggal {Dd}/{M}/{Y}, omzet tahun berjalan sebesar **{rp(S['ytd_now'])}**"
if S["ytd_g"] is not None:
    n += f", {'naik' if S['ytd_g'] >= 0 else 'turun'} **{pct(abs(S['ytd_g']), False)}** dibanding rentang tanggal yang sama tahun {P}"
n += ". "
if S["hi"]:
    n += f"Omzet bulanan tertinggi terjadi pada {lbl(S['hi'])} ({rp(S['hi'][2])})"
    n += f", sedangkan terendah pada {lbl(S['lo'])} ({rp(S['lo'][2])}). " if S["lo"] else ". "
if trn(Y):
    n += f"Pada {Y} tercatat {angka(trn(Y))} nota dengan rata-rata {rp(tot[Y] / trn(Y))} per nota. "
if pilih != "SEMUA STORE":
    n += f"Store ini berkontribusi {kon} dari total omzet {Y} ({sub_kon.lower()})."
st.markdown('<div class="card narasi">' + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", n) + "</div>", unsafe_allow_html=True)

st.header("2. Indikator Kinerja Utama (KPI)")
k = [("Total omzet periode", rp(tot.sum()), None, f"{tahun[0]} - {Y}"),
     (f"Omzet {Y} (YTD s.d. {Dd}/{M})", rp(S["ytd_now"]), None, f"{P}: {rp(S['ytd_prev'])} (tanggal sama)"),
     (f"Pertumbuhan YTD vs {P}", pct(S["ytd_g"]), None, "Rentang tanggal yang sama")]
for t in tahun[1:]:
    k.append((f"Pertumbuhan {t} vs {t - 1}", pct(growth(tot[t], tot[t - 1])), None, f"Omzet {t}: {singkat(tot[t])}"))
k += [(f"Rata-rata omzet bulanan {Y}", rp(S["rb"][Y]), None, f"{P}: {singkat(S['rb'].get(P, 0))}"),
      (f"Jumlah transaksi (nota) {Y}", angka(trn(Y)), None, f"{P}: {angka(trn(P))}"),
      (f"Rata-rata nilai per nota {Y}", rp(tot[Y] / trn(Y)) if trn(Y) else "n/a", None,
       f"{P}: {rp(tot[P] / trn(P)) if P in tot.index and trn(P) else 'n/a'}"),
      (f"Item terjual {Y}", angka(pt.loc[Y, "qty"]), None, f"{P}: {angka(pt.loc[P, 'qty']) if P in pt.index else 0}"),
      (f"Sales After Disc. {Y}", rp(pt.loc[Y, "sad"]), None, "Sebelum service charge & pajak"),
      (f"Service charge + pajak {Y}", rp(pt.loc[Y, "sc"] + pt.loc[Y, "tax"]), None,
       f"SC {singkat(pt.loc[Y, 'sc'])} | Pajak {singkat(pt.loc[Y, 'tax'])}"),
      (f"Total diskon {Y}", rp(max(0, pt.loc[Y, "bruto"] - pt.loc[Y, "sad"])), None, "TransBruto - Sales After Disc."),
      (f"COGS {Y}", rp(pt.loc[Y, "cogs"]), None, f"{P}: {rp(pt.loc[P, 'cogs']) if P in pt.index else 'n/a'}"),
      (f"COGS % dari Sales After Disc. {Y}", pct(cogs_pct(Y), False), None, f"{P}: {pct(cogs_pct(P), False) if P in pt.index else 'n/a'}"),
      (f"Laba kotor {Y}", rp(laba(Y)), None, f"{P}: {rp(laba(P)) if P in pt.index else 'n/a'}"),
      (f"Gross margin {Y}", pct(mg(Y), False), None, f"{P}: {pct(mg(P), False) if P in pt.index else 'n/a'}"),
      ("Bulan omzet tertinggi", lbl(S["hi"]), None, rp(S["hi"][2]) if S["hi"] else ""),
      ("Bulan omzet terendah", lbl(S["lo"]), None, rp(S["lo"][2]) if S["lo"] else ""),
      (f"Kontribusi terhadap total {Y}", kon, None, sub_kon)]
grid(k)

st.header("3. Perbandingan Periode")
dmin, dmax = d["Tgl"].min().date(), d["Tgl"].max().date()
pc1, pc2 = st.columns(2)
rg = pc1.date_input("Periode utama", value=(max(dmin, akhir.replace(day=1).date()), dmax), min_value=dmin, max_value=dmax)
mode = pc2.radio("Dibandingkan dengan", ["Tahun lalu (tanggal sama)", "Periode sebelumnya (panjang sama)", "Pilih manual"])
rg2 = None
if mode == "Pilih manual":
    rg2 = pc2.date_input("Periode pembanding", value=(dmin, dmin), min_value=dmin, max_value=dmax)
ok = isinstance(rg, tuple) and len(rg) == 2 and (mode != "Pilih manual" or (isinstance(rg2, tuple) and len(rg2) == 2))
if not ok:
    st.info("Pilih tanggal awal dan tanggal akhir pada kalender.")
else:
    a1, a2 = pd.Timestamp(rg[0]), pd.Timestamp(rg[1])
    if mode.startswith("Tahun"):
        b1, b2 = a1 - pd.DateOffset(years=1), a2 - pd.DateOffset(years=1)
    elif mode.startswith("Periode"):
        span = a2 - a1 + pd.Timedelta(days=1)
        b2 = a1 - pd.Timedelta(days=1)
        b1 = b2 - span + pd.Timedelta(days=1)
    else:
        b1, b2 = pd.Timestamp(rg2[0]), pd.Timestamp(rg2[1])
    ma = metrik(d[(d["Tgl"] >= a1) & (d["Tgl"] <= a2)])
    mb = metrik(d[(d["Tgl"] >= b1) & (d["Tgl"] <= b2)])
    kp_ = [("Pertumbuhan Sales Netto", pct(growth(ma["Sales Netto"], mb["Sales Netto"])), None,
            f"{rp(ma['Sales Netto'])} vs {rp(mb['Sales Netto'])}")]
    for nm_, fm in [("Sales Netto", rp), ("Jumlah nota", angka), ("Item terjual", angka), ("Rata-rata per nota", rp),
                    ("COGS", rp), ("Laba kotor", rp), ("Diskon", rp)]:
        kp_.append((nm_, fm(ma[nm_]), None, f"Pembanding: {fm(mb[nm_])} ({pct(growth(ma[nm_], mb[nm_]))})"))
    kp_.append(("Gross margin", pct(ma["Gross margin %"], False), None, f"Pembanding: {pct(mb['Gross margin %'], False)}"))
    grid(kp_)
    st.caption(f"Periode utama {a1:%d/%m/%Y} - {a2:%d/%m/%Y} dibandingkan dengan {b1:%d/%m/%Y} - {b2:%d/%m/%Y}.")

st.header("4. Analisis Tren")
c1, c2 = st.columns([2.4, 1])
fig = go.Figure()
for t in tahun:
    y = [None if (t == Y and b > M) else float(v) for b, v in zip(range(1, 13), S["bul"][t])]
    fig.add_trace(go.Scatter(x=BLN, y=y, mode="lines+markers", name=str(t), line=dict(width=3, color=warna[t]),
                             customdata=[rp(v) for v in S["bul"][t]],
                             hovertemplate="%{x}<br>%{customdata}<extra>" + str(t) + "</extra>"))
tv, tt = ticks(float(S["bul"].values.max()))
fig.update_layout(title=f"Tren Omzet Bulanan - {nama}", height=380, yaxis=dict(tickvals=tv, ticktext=tt, rangemode="tozero", title="Omzet (Rupiah)"),
                  legend=dict(orientation="h", y=-0.2), margin=dict(t=50, r=15, b=60, l=70))
c1.plotly_chart(fig, use_container_width=True)
vals = [float(tot[t]) for t in tahun]
tv2, tt2 = ticks(max(vals))
fig2 = go.Figure(go.Bar(x=[str(t) for t in tahun], y=vals, marker_color=[warna[t] for t in tahun],
                        text=[singkat(v) for v in vals], textposition="outside", customdata=[rp(v) for v in vals],
                        hovertemplate="%{x}<br>%{customdata}<extra></extra>"))
fig2.update_layout(title="Total Omzet per Tahun", height=380, yaxis=dict(tickvals=tv2, ticktext=tt2), margin=dict(t=50, r=15, b=50, l=70))
c2.plotly_chart(fig2, use_container_width=True)

st.header("5. Komposisi Omzet")
a, b = st.columns(2)
dy_ = d[d["Tahun"] == Y]
a.plotly_chart(hbar(f"Omzet per Group ({Y})", S["grp"], "#4C72B0"), use_container_width=True)
b.plotly_chart(hbar(f"Omzet per Department ({Y})", S["dep"], "#55A868"), use_container_width=True)
a.plotly_chart(hbar(f"COGS per Group ({Y})", dy_.groupby("Group")["COGS"].sum(), "#C44E52"), use_container_width=True)
b.plotly_chart(hbar(f"Metode Pembayaran ({Y})", S["pay"], "#DD8452"), use_container_width=True)

tampil = None
st.header("6. Analisis Group, Department, dan Menu (Interaktif)")
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
    menu = (dm.groupby("Menu").agg(Group=("Group", "first"), Dept=("Dept", "first"), Qty=("Qty", "sum"),
                                   Netto=("Netto", "sum"), SAD=("SAD", "sum"), COGS=("COGS", "sum"),
                                   Nota=("Nota", "nunique")).reset_index())
    menu["Laba Kotor"] = menu["SAD"] - menu["COGS"]
    menu["Margin %"] = (menu["Laba Kotor"] / menu["SAD"] * 100).where(menu["SAD"] > 0)
    tn = menu["Netto"].sum()
    menu["Kontribusi %"] = menu["Netto"] / tn * 100 if tn else 0.0
    menu = menu.sort_values("Netto", ascending=False)
    ts, tq, tc = menu["SAD"].sum(), menu["Qty"].sum(), menu["COGS"].sum()
    ringkas = [("Sales Netto", rp(tn)), ("Item terjual", angka(tq)), ("COGS", rp(tc)), ("Laba kotor", rp(ts - tc)),
               ("Gross margin", pct((ts - tc) / ts * 100, False) if ts else "n/a")]
    grid(ringkas)

    t1, t2, t3, t4, t5 = st.tabs(["Treemap (klik untuk drill-down)", "Top Menu", "Tabel Menu", "Tren per Menu", "Menu Engineering"])
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
        st.plotly_chart(hbar(f"Top {n_top} Menu - {ukuran} ({thn})", menu.set_index("Menu")[ukuran], "#8172B3",
                             n_top, ukuran != "Qty"), use_container_width=True)
    with t3:
        tampil = menu[["Menu", "Group", "Dept", "Qty", "Netto", "SAD", "COGS", "Laba Kotor", "Margin %", "Kontribusi %", "Nota"]]
        tampil = tampil.rename(columns={"Netto": "Sales Netto", "SAD": "Sales After Disc.", "Nota": "Jumlah Nota"}).reset_index(drop=True)
        fmt = {"Qty": angka, "Sales Netto": rp, "Sales After Disc.": rp, "COGS": rp, "Laba Kotor": rp,
               "Jumlah Nota": angka, "Margin %": lambda v: pct(v, False), "Kontribusi %": lambda v: pct(v, False)}
        st.dataframe(tampil.style.format(fmt, na_rep="n/a"), use_container_width=True, hide_index=True)
        st.download_button("Unduh tabel (CSV)", tampil.to_csv(index=False).encode("utf-8-sig"),
                           f"analisis_menu_{thn}.csv", "text/csv")
    with t4:
        pm = st.selectbox("Pilih menu", list(menu["Menu"]))
        bmn = (d[d["Menu"] == pm].pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
               .reindex(index=range(1, 13), columns=tahun, fill_value=0))
        fig4 = go.Figure()
        for t in tahun:
            y4 = [None if (t == Y and b_ > M) else float(v) for b_, v in zip(range(1, 13), bmn[t])]
            fig4.add_trace(go.Scatter(x=BLN, y=y4, mode="lines+markers", name=str(t), line=dict(width=3, color=warna[t]),
                                      customdata=[rp(v) for v in bmn[t]],
                                      hovertemplate="%{x}<br>%{customdata}<extra>" + str(t) + "</extra>"))
        tv4, tt4 = ticks(float(bmn.values.max()))
        fig4.update_layout(title=f"Tren Omzet Bulanan - {pm}", height=380, legend=dict(orientation="h", y=-0.2),
                           yaxis=dict(tickvals=tv4, ticktext=tt4, rangemode="tozero"), margin=dict(t=50, r=15, b=60, l=70))
        st.plotly_chart(fig4, use_container_width=True)

    with t5:
        me = menu[menu["Qty"] > 0].copy()
        if len(me) < 4:
            st.info("Menu terlalu sedikit untuk dianalisis pada filter ini.")
        else:
            me["CM/item"] = me["Laba Kotor"] / me["Qty"]
            ambang_pop = 0.7 / len(me) * me["Qty"].sum()
            ambang_cm = me["Laba Kotor"].sum() / me["Qty"].sum()
            me["Kelas"] = [("Bintang" if cm >= ambang_cm else "Kuda Kerja") if q >= ambang_pop
                           else ("Tanda Tanya" if cm >= ambang_cm else "Beban") for q, cm in zip(me["Qty"], me["CM/item"])]
            wk = {"Bintang": "#55A868", "Kuda Kerja": "#4C72B0", "Tanda Tanya": "#DD8452", "Beban": "#C44E52"}
            fig5 = px.scatter(me, x="Qty", y="CM/item", color="Kelas", color_discrete_map=wk, hover_name="Menu",
                              hover_data={"Qty": ":,.0f", "CM/item": ":,.0f", "Laba Kotor": ":,.0f", "Kelas": False})
            fig5.add_vline(x=ambang_pop, line_dash="dash", line_color="#999")
            fig5.add_hline(y=ambang_cm, line_dash="dash", line_color="#999")
            fig5.update_layout(title="Menu Engineering: popularitas vs laba kotor per item", height=520,
                               xaxis_title="Item terjual (Qty)", yaxis_title="Laba kotor per item (Rp)")
            st.plotly_chart(fig5, use_container_width=True)
            saran = {"Bintang": "Laris dan laba tinggi: pertahankan kualitas, jaga stok, tampilkan menonjol.",
                     "Kuda Kerja": "Laris tapi laba kecil: pertimbangkan naik harga atau tekan COGS.",
                     "Tanda Tanya": "Laba bagus tapi kurang laku: promosikan atau tempatkan lebih menonjol.",
                     "Beban": "Kurang laku dan laba kecil: evaluasi resep dan harga, atau keluarkan dari menu."}
            ring = pd.DataFrame([{"Kelas": c_, "Jumlah menu": int((me["Kelas"] == c_).sum()),
                                  "Sales Netto": me.loc[me["Kelas"] == c_, "Netto"].sum(),
                                  "Laba Kotor": me.loc[me["Kelas"] == c_, "Laba Kotor"].sum(), "Saran": saran[c_]} for c_ in saran])
            st.dataframe(ring.style.format({"Sales Netto": rp, "Laba Kotor": rp}), use_container_width=True, hide_index=True)
            kp = st.selectbox("Lihat daftar menu pada kelas", list(saran))
            dk = (me[me["Kelas"] == kp].sort_values("Laba Kotor", ascending=False)
                  [["Menu", "Group", "Dept", "Qty", "CM/item", "Laba Kotor", "Netto"]]
                  .rename(columns={"Netto": "Sales Netto", "CM/item": "Laba kotor per item"}))
            st.dataframe(dk.style.format({"Qty": angka, "Laba kotor per item": rp, "Laba Kotor": rp, "Sales Netto": rp}),
                         use_container_width=True, hide_index=True)
            st.caption("Ambang popularitas = 70% dari rata-rata porsi penjualan menu; ambang margin = rata-rata laba kotor per item. "
                       "COGS dianggap total per baris.")

st.header("7. Pola Waktu")
thw = st.selectbox("Tahun analisis (Pola Waktu dan Diskon)", sorted(tahun, reverse=True), key="thw")
dw = d[d["Tahun"] == thw]
harian = dw.groupby("Tgl")["Netto"].sum()
if harian.empty:
    st.info("Tidak ada data pada tahun tersebut.")
else:
    hd = harian.groupby(harian.index.dayofweek).mean().reindex(range(7))
    tg = harian.groupby(harian.index.day).mean().reindex(range(1, 32))
    w1, w2 = st.columns(2)
    f6 = go.Figure(go.Bar(x=HARI, y=hd.values, marker_color=["#55A868" if i >= 5 else "#4C72B0" for i in range(7)],
                          text=[singkat(v) if pd.notna(v) else "" for v in hd.values], textposition="outside",
                          customdata=[rp(v) if pd.notna(v) else "-" for v in hd.values],
                          hovertemplate="%{x}<br>%{customdata}<extra></extra>"))
    f6.update_layout(title=f"Rata-rata Omzet per Hari ({thw})", height=360, yaxis=dict(visible=False), margin=dict(t=50, r=15, b=40, l=15))
    w1.plotly_chart(f6, use_container_width=True)
    f7 = go.Figure(go.Bar(x=list(range(1, 32)), y=tg.values, marker_color="#8172B3",
                          customdata=[rp(v) if pd.notna(v) else "-" for v in tg.values],
                          hovertemplate="Tanggal %{x}<br>%{customdata}<extra></extra>"))
    f7.update_layout(title=f"Rata-rata Omzet per Tanggal ({thw})", height=360, yaxis=dict(visible=False),
                     xaxis=dict(title="Tanggal", dtick=1), margin=dict(t=50, r=15, b=40, l=15))
    w2.plotly_chart(f7, use_container_width=True)
    st.caption(f"Rata-rata omzet tertinggi terjadi pada hari {HARI[int(hd.idxmax())]} ({rp(hd.max())}). "
               "Rata-rata dihitung hanya dari hari yang memiliki transaksi.")

st.header("8. Analisis Diskon dan Pembayaran")
dw2 = dw.assign(Diskon=(dw["Bruto"] - dw["SAD"]).clip(lower=0), Periode=dw["Tgl"].dt.strftime("%Y-%m"))
if dw2.empty:
    st.info("Tidak ada data pada tahun tersebut.")
else:
    bd = dw2.groupby("Periode").agg(Diskon=("Diskon", "sum"), Bruto=("Bruto", "sum"))
    bd["Pct"] = (bd["Diskon"] / bd["Bruto"] * 100).where(bd["Bruto"] > 0)
    tvd, ttd = ticks(float(bd["Diskon"].max()))
    f8 = go.Figure()
    f8.add_trace(go.Bar(x=list(bd.index), y=bd["Diskon"], name="Diskon (Rp)", marker_color="#C44E52",
                        customdata=[rp(v) for v in bd["Diskon"]], hovertemplate="%{x}<br>%{customdata}<extra>Diskon</extra>"))
    f8.add_trace(go.Scatter(x=list(bd.index), y=bd["Pct"], name="Diskon % dari Bruto", yaxis="y2", mode="lines+markers",
                            line=dict(color="#1f4e8c", width=3)))
    f8.update_layout(title=f"Tren Diskon per Bulan ({thw})", height=380, yaxis=dict(tickvals=tvd, ticktext=ttd),
                     yaxis2=dict(overlaying="y", side="right", ticksuffix="%", showgrid=False),
                     legend=dict(orientation="h", y=-0.2), margin=dict(t=50, r=50, b=60, l=70))
    st.plotly_chart(f8, use_container_width=True)
    e1, e2 = st.columns(2)
    e1.plotly_chart(hbar(f"Diskon per Group ({thw})", dw2.groupby("Group")["Diskon"].sum(), "#C44E52"), use_container_width=True)
    e2.plotly_chart(hbar(f"10 Menu Paling Banyak Didiskon ({thw})", dw2.groupby("Menu")["Diskon"].sum(), "#C44E52"), use_container_width=True)
    pv = dw2.pivot_table(index="Periode", columns="Payment", values="Netto", aggfunc="sum", fill_value=0)
    f9 = go.Figure()
    for i, c_ in enumerate(pv.columns):
        f9.add_trace(go.Bar(x=list(pv.index), y=pv[c_], name=str(c_), marker_color=px.colors.qualitative.Plotly[i % 10]))
    f9.update_layout(barmode="stack", barnorm="percent", title=f"Komposisi Metode Pembayaran per Bulan ({thw})", height=380,
                     yaxis=dict(ticksuffix="%"), legend=dict(orientation="h", y=-0.2), margin=dict(t=50, r=15, b=60, l=50))
    st.plotly_chart(f9, use_container_width=True)

st.header("9. Rincian Bulanan")
ukur = st.radio("Tampilkan", ["Sales Netto", "COGS", "Laba Kotor"], horizontal=True)
nilai = d["SAD"] - d["COGS"] if ukur == "Laba Kotor" else d["COGS" if ukur == "COGS" else "Netto"]
bm = (d.assign(Nilai=nilai).pivot_table(index="Bulan", columns="Tahun", values="Nilai", aggfunc="sum", fill_value=0)
      .reindex(index=range(1, 13), columns=tahun, fill_value=0))
tabel = pd.DataFrame({str(t): [("-" if (t == Y and i + 1 > M) else rp(bm[t].iloc[i]) + (" *" if (t == Y and i + 1 == M and partial) else ""))
                               for i in range(12)] for t in tahun}, index=BLN)
tabel.loc["TOTAL"] = [rp(bm[t].sum()) for t in tahun]
tabel.index.name = "Bulan"
st.dataframe(tabel, use_container_width=True)

st.header("10. Peringkat Seluruh Store")
baris = [{"StoreCode": s_, **{str(t): rp(h["tot"][t]) for t in tahun},
          f"Kontribusi {Y}": pct(h["tot"][Y] / tot_all * 100, False) if tot_all else "n/a",
          "Growth YTD": pct(h["ytd_g"])} for s_, h in rank]
baris.append({"StoreCode": "TOTAL", **{str(t): rp(SA["tot"][t]) for t in tahun}, f"Kontribusi {Y}": "100%", "Growth YTD": pct(SA["ytd_g"])})
st.dataframe(pd.DataFrame(baris), use_container_width=True, hide_index=True)

cat = "Omzet = Sales Netto (termasuk service charge dan pajak). Pertumbuhan YTD membandingkan rentang tanggal yang sama tahun sebelumnya. "
cat += "Gross margin = (Sales After Disc. - COGS) / Sales After Disc. "
if partial:
    cat += f"* Bulan {BLN[M - 1]} {Y} belum penuh (data s.d. tanggal {Dd}). "
if df.attrs.get("dilewati"):
    cat += f"{angka(df.attrs['dilewati'])} baris dilewati karena tanggal/angka tidak terbaca."
st.caption(cat)


def buat_excel():
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame([(i[0], i[1], i[3] if len(i) > 3 else "") for i in k], columns=["KPI", "Nilai", "Keterangan"]).to_excel(
            xw, sheet_name="KPI", index=False)
        bl = []
        for nm_, ser in [("Sales Netto", d["Netto"]), ("COGS", d["COGS"]), ("Laba Kotor", d["SAD"] - d["COGS"])]:
            pvt = (d.assign(Nilai=ser).pivot_table(index="Bulan", columns="Tahun", values="Nilai", aggfunc="sum", fill_value=0)
                   .reindex(index=range(1, 13), columns=tahun, fill_value=0))
            pvt.columns = [f"{nm_} {t}" for t in tahun]
            bl.append(pvt)
        bb = pd.concat(bl, axis=1)
        bb.index = BLN
        bb.to_excel(xw, sheet_name="Bulanan", index_label="Bulan")
        pd.DataFrame([{"StoreCode": s_, **{str(t): float(h["tot"][t]) for t in tahun}, "Growth YTD %": h["ytd_g"]}
                      for s_, h in rank]).to_excel(xw, sheet_name="Peringkat Store", index=False)
        if tampil is not None:
            tampil.to_excel(xw, sheet_name="Menu", index=False)
        pd.DataFrame({"Catatan": pesan or ["Tidak ada catatan"]}).to_excel(xw, sheet_name="Kualitas Data", index=False)
    return out.getvalue()


with st.sidebar:
    st.divider()
    try:
        st.download_button("Unduh laporan (Excel)", buat_excel(), f"laporan_omzet_{nama.replace(' ', '_')}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except ImportError:
        st.caption("Untuk ekspor Excel, instal dulu: pip install openpyxl")
