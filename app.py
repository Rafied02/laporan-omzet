"""
HELIOS - Dashboard Laporan Omzet Penjualan (Python + Streamlit)

Menjalankan : streamlit run reporthnp.py
Dependensi  : pip install streamlit pandas plotly openpyxl
Sumber data : Google Sheets "Publish to web" (CSV) atau unggah CSV manual
Basis omzet : kolom "Sales Netto"

Struktur file
    1. Konfigurasi        4. Perhitungan & kualitas data
    2. Format angka       5. Komponen tampilan
    3. Pemuatan data      6. Halaman (harian & bulanan)   7. Aplikasi (main)
"""
from __future__ import annotations

import hmac
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit.runtime import exists

if not exists():
    print("Jalankan dengan: streamlit run reporthnp.py")
    raise SystemExit

# ============================================================ 1. KONFIGURASI
BRAND = "HELIOS"

# Link Publish to web (CSV). Di Streamlit Cloud lebih aman lewat Secrets: CSV_URL = "..."
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTknFFShtKKmsiLiH1IKhD9rARIlN68NUWdOrFiQc42X2jdAGemNg9L_NwBbb60osXL-m_1PIPAB_hF/pubhtml"
# Password (opsional, kosongkan jika tidak perlu). Di Streamlit Cloud lebih aman lewat Secrets: APP_PASSWORD = "..."
APP_PASSWORD = ""
CACHE_TTL = 300  # detik; data Sheets dimuat ulang otomatis setiap 5 menit

# Ambang peringatan
HARI_PEMBANDING = 4          # jumlah minggu pembanding untuk laporan harian
AMBANG_OMZET_TURUN = 0.7     # omzet < 70% rata-rata hari yang sama
AMBANG_DISKON_RASIO = 1.5    # diskon > 1,5x biasanya ...
AMBANG_DISKON_SELISIH = 0.02  # ... dan selisih minimal 2 poin persentase
AMBANG_COGS_NAIK = 0.05      # COGS naik >= 5 poin persentase
AMBANG_BULAN_ANOMALI = 0.4   # omzet bulan < 40% rata-rata 3 bulan sebelumnya

BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
PAL = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]
BIRU, HIJAU, ORANYE, MERAH, UNGU = PAL[0], PAL[2], PAL[1], PAL[3], PAL[4]

KOLOM = {"storecode": "Store", "transdate": "Tgl", "sales netto": "Netto", "receiptno": "Resi",
         "transqty": "Qty", "sales after disc.": "SAD", "service charge": "SC", "transbruto": "Bruto",
         "cogs": "COGS", "group": "Group", "department": "Dept", "payment": "Payment", "catname": "Menu"}
KOLOM_WAJIB = ["Store", "Tgl", "Netto"]
NAMA_ASLI = {"Store": "StoreCode", "Tgl": "TransDate", "Netto": "Sales Netto"}  # untuk pesan error
KOLOM_ANGKA = ["Qty", "SAD", "SC", "Tax", "Bruto", "COGS"]
KOLOM_TEKS = ["Group", "Dept", "Payment", "Menu"]

TEMA_TOML = ('[theme]\nbase = "light"\nprimaryColor = "#1f4e8c"\nbackgroundColor = "#f4f6fa"\n'
             'secondaryBackgroundColor = "#ffffff"\ntextColor = "#1d2433"\n')

CSS = """<style>
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
</style>"""


# ============================================================ 2. FORMAT ANGKA
def idn(teks: str) -> str:
    """Ubah format angka Inggris (1,234.5) menjadi Indonesia (1.234,5)."""
    return teks.replace(",", "X").replace(".", ",").replace("X", ".")


def angka(x: float, desimal: int = 0) -> str:
    return idn(f"{x:,.{desimal}f}")


def rp(x: float) -> str:
    return "Rp " + angka(x)


def singkat(x: float) -> str:
    """Format ringkas: 1,2 M / 350 jt."""
    if abs(x) >= 1e9:
        return angka(x / 1e9, 1) + " M"
    if abs(x) >= 1e6:
        return angka(x / 1e6) + " jt"
    return angka(x)


def pct(v: Optional[float], tanda: bool = True) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    return idn(f"{v:+.1f}%" if tanda else f"{v:.1f}%")


def growth(sekarang: float, pembanding: float) -> Optional[float]:
    """Pertumbuhan dalam persen; None jika pembanding nol."""
    return None if not pembanding else (sekarang - pembanding) / pembanding * 100


def ticks(maks: float) -> tuple[list[float], list[str]]:
    """Tick sumbu Y dengan angka bulat dan label singkat (M / jt)."""
    mentah = (maks or 1) / 5
    mag = 10 ** math.floor(math.log10(mentah))
    n = mentah / mag
    step = (1 if n <= 1 else 2 if n <= 2 else 5 if n <= 5 else 10) * mag
    nilai = [i * step for i in range(int(maks / step) + 2)]
    return nilai, [singkat(v) for v in nilai]


# ============================================================ 3. PEMUATAN DATA
class DataError(Exception):
    """Data sumber tidak sesuai format yang diharapkan."""


def url_csv(url: str) -> str:
    """Ubah link Publish to web (pubhtml) otomatis menjadi link CSV."""
    url = (url or "").strip()
    if "/pubhtml" in url:
        url = url.replace("/pubhtml", "/pub")
    if "/pub" in url and "output=" not in url:
        url += ("&" if "?" in url else "?") + "output=csv"
    return url


def ke_angka(s: pd.Series) -> pd.Series:
    """Baca angka berformat Indonesia (1.234,5), Inggris (1,234.5), atau polos."""
    s = s.fillna("").astype(str).str.replace(r"[^0-9,.\-]", "", regex=True)
    fmt_id = s.str.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")
    fmt_us = s.str.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
    s = s.where(~fmt_id, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    s = s.where(~fmt_us, s.str.replace(",", "", regex=False))
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def bersihkan(raw: pd.DataFrame) -> pd.DataFrame:
    """Standarkan nama kolom, tipe data, dan turunan tanggal."""
    peta = {}
    for kolom in raw.columns:
        kunci = kolom.strip().lower()
        if kunci in KOLOM:
            peta[kolom] = KOLOM[kunci]
        elif kunci.startswith("tax"):
            peta[kolom] = "Tax"
    df = raw.rename(columns=peta)
    hilang = [NAMA_ASLI[k] for k in KOLOM_WAJIB if k not in df.columns]
    if hilang:
        raise DataError("Kolom tidak ditemukan: " + ", ".join(hilang) + "\nKolom terbaca: " + ", ".join(raw.columns))

    tgl = pd.to_datetime(df["Tgl"].astype(str).str.strip(), format="%Y%m%d", errors="coerce")
    sisa = tgl.isna()
    if sisa.any():
        tgl[sisa] = pd.to_datetime(df.loc[sisa, "Tgl"], dayfirst=True, errors="coerce")
    df["Tgl"] = tgl
    df["Netto"] = ke_angka(df["Netto"])
    for kolom in KOLOM_ANGKA:
        df[kolom] = ke_angka(df[kolom]).fillna(0) if kolom in df.columns else 0.0
    for kolom in KOLOM_TEKS:
        df[kolom] = df[kolom].fillna("-").astype(str).str.strip().replace("", "-") if kolom in df.columns else "-"
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


@st.cache_data(ttl=CACHE_TTL, show_spinner="Memuat data...")
def muat(sumber: str, isi: Optional[bytes] = None) -> pd.DataFrame:
    """Baca CSV dari URL (sumber) atau dari isi file unggahan, lalu bersihkan."""
    raw = pd.read_csv(io.BytesIO(isi) if isi is not None else sumber, dtype=str)
    if raw.shape[1] == 1 and isi is not None:  # CSV bertitik koma
        raw = pd.read_csv(io.BytesIO(isi), dtype=str, sep=";")
    return bersihkan(raw)


@dataclass
class Konteks:
    """Informasi umum data yang dipakai seluruh halaman."""
    df: pd.DataFrame
    tahun: list
    akhir: pd.Timestamp
    stores: list
    warna: dict

    @classmethod
    def dari(cls, df: pd.DataFrame) -> "Konteks":
        tahun = sorted(int(t) for t in df["Tahun"].unique())
        return cls(df, tahun, df["Tgl"].max(), sorted(df["Store"].unique()),
                   {t: PAL[i % len(PAL)] for i, t in enumerate(tahun)})

    @property
    def Y(self) -> int:
        return int(self.akhir.year)

    @property
    def M(self) -> int:
        return int(self.akhir.month)

    @property
    def Dd(self) -> int:
        return int(self.akhir.day)

    @property
    def P(self) -> int:
        return self.Y - 1

    @property
    def partial(self) -> bool:
        """True jika bulan terakhir belum penuh."""
        return self.Dd < self.akhir.days_in_month


# ============================================================ 4. PERHITUNGAN
def metrik(x: pd.DataFrame) -> dict:
    """Ringkasan KPI untuk sekumpulan baris transaksi."""
    sad, cogs, nota = x["SAD"].sum(), x["COGS"].sum(), x["Nota"].nunique()
    return {"Sales Netto": x["Netto"].sum(), "Jumlah nota": nota, "Item terjual": x["Qty"].sum(),
            "Rata-rata per nota": x["Netto"].sum() / nota if nota else 0, "COGS": cogs, "Laba kotor": sad - cogs,
            "Gross margin %": (sad - cogs) / sad * 100 if sad else None,
            "Diskon": max(0, x["Bruto"].sum() - sad), "Bruto": x["Bruto"].sum(), "SAD": sad}


def rata(daftar: list, kunci: str) -> Optional[float]:
    nilai = [m[kunci] for m in daftar if m[kunci] is not None]
    return sum(nilai) / len(nilai) if nilai else None


def hitung(d: pd.DataFrame, ctx: Konteks) -> dict:
    """Agregat bulanan/tahunan, YTD, bulan tertinggi/terendah, dan komposisi tahun terakhir."""
    Y, M, tahun = ctx.Y, ctx.M, ctx.tahun
    bul = (d.pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
           .reindex(index=range(1, 13), columns=tahun, fill_value=0))
    tot = bul.sum()
    pt = (d.groupby("Tahun").agg(trn=("Nota", "nunique"), qty=("Qty", "sum"), sad=("SAD", "sum"), sc=("SC", "sum"),
                                 tax=("Tax", "sum"), bruto=("Bruto", "sum"), cogs=("COGS", "sum"))
          .reindex(tahun, fill_value=0))
    sel = [(t, b, float(bul.loc[b, t])) for t in tahun for b in range(1, 13)
           if bul.loc[b, t] > 0 and not (t == Y and b == M and ctx.partial)]
    aktif = {t: sum(1 for s in sel if s[0] == t) for t in tahun}
    ytd_now = float(d.loc[d["Tahun"] == Y, "Netto"].sum())
    m_prev = (d["Tahun"] == ctx.P) & ((d["Bulan"] < M) | ((d["Bulan"] == M) & (d["Hari"] <= ctx.Dd)))
    ytd_prev = float(d.loc[m_prev, "Netto"].sum())
    dy = d[d["Tahun"] == Y]
    return {
        "bul": bul, "tot": tot, "pt": pt,
        "rb": {t: (tot[t] / aktif[t] if aktif[t] else 0) for t in tahun},
        "hi": max(sel, key=lambda s: s[2]) if sel else None,
        "lo": min(sel, key=lambda s: s[2]) if sel else None,
        "ytd_now": ytd_now, "ytd_prev": ytd_prev, "ytd_g": growth(ytd_now, ytd_prev),
        "grp": dy.groupby("Group")["Netto"].sum(), "dep": dy.groupby("Dept")["Netto"].sum(),
        "pay": dy.groupby("Payment")["Netto"].sum(),
    }


def cek_data(df: pd.DataFrame, akhir: pd.Timestamp) -> list:
    """Catatan kualitas data: tahun tidak penuh, store tertinggal, bulan kosong, dan anomali."""
    pesan = []
    awal = df["Tgl"].min()
    if awal > pd.Timestamp(awal.year, 1, 31):
        pesan.append(f"Data tahun {awal.year} baru dimulai {awal:%d/%m/%Y}, sehingga tahun tersebut tidak penuh. "
                     "Jangan bandingkan total tahunannya langsung.")
    for store, g in df.assign(P=df["Tgl"].dt.to_period("M")).groupby("Store"):
        terakhir = g["Tgl"].max()
        if terakhir < akhir - pd.Timedelta(days=7):
            pesan.append(f"Store {store}: data terakhir {terakhir:%d/%m/%Y}, tertinggal dari data terbaru ({akhir:%d/%m/%Y}).")
        bul = g.groupby("P")["Netto"].sum()
        bul = bul.reindex(pd.period_range(bul.index.min(), bul.index.max(), freq="M"), fill_value=0)
        pesan += [f"Store {store}: tidak ada omzet pada {p.strftime('%m/%Y')}." for p, v in bul.items() if v <= 0]
        for i in range(3, len(bul)):
            periode = bul.index[i]
            if periode == akhir.to_period("M") and akhir.day < akhir.days_in_month:
                continue
            ref = bul.iloc[i - 3:i]
            ref = ref[ref > 0]
            if len(ref) >= 2 and 0 < bul.iloc[i] < AMBANG_BULAN_ANOMALI * ref.mean():
                pesan.append(f"Store {store}: omzet {periode.strftime('%m/%Y')} hanya "
                             f"{bul.iloc[i] / ref.mean() * 100:.0f}% dari rata-rata 3 bulan sebelumnya.")
    return pesan


# ============================================================ 5. KOMPONEN TAMPILAN
Kartu = tuple  # (label, nilai, keterangan)


def banner(judul: str, subjudul: str) -> None:
    st.markdown(f'<div class="banner"><h1>{BRAND} - {judul}</h1><p>{subjudul}</p></div>', unsafe_allow_html=True)


def grid(items: list) -> None:
    """Tampilkan kartu KPI berkotak. Item: (label, nilai, keterangan)."""
    def kartu(label, nilai, ket=""):
        kelas = "up" if nilai.startswith("+") else "down" if (nilai.startswith("-") and "%" in nilai) else ""
        return (f'<div class="kpi"><div class="l">{label}</div><div class="v {kelas}">{nilai}</div>'
                f'<div class="s">{ket or "&nbsp;"}</div></div>')
    st.markdown('<div class="kpis">' + "".join(kartu(*i) for i in items) + "</div>", unsafe_allow_html=True)


def tabel_format(df: pd.DataFrame, pemformat: dict) -> pd.DataFrame:
    """Format kolom menjadi teks agar nilai kosong tampil 'n/a' (bukan None)."""
    df = df.copy()
    for kolom, fungsi in pemformat.items():
        df[kolom] = df[kolom].map(fungsi)
    return df


def hbar(judul: str, serie: pd.Series, warna: str, n: int = 10, uang: bool = True) -> go.Figure:
    """Grafik batang horizontal untuk n nilai terbesar."""
    s = serie.sort_values(ascending=False).head(n)[::-1]
    fmt = rp if uang else angka
    fig = go.Figure(go.Bar(x=s.values, y=list(s.index), orientation="h", marker_color=warna,
                           text=[singkat(v) for v in s.values], textposition="outside", cliponaxis=False,
                           customdata=[fmt(v) for v in s.values], hovertemplate="%{y}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title=judul, height=max(340, 26 * n + 90), margin=dict(t=45, r=60, b=20, l=10),
                      xaxis=dict(showticklabels=False), yaxis=dict(automargin=True))
    return fig


def grafik_garis(judul: str, bulanan: pd.DataFrame, ctx: Konteks, tinggi: int = 380) -> go.Figure:
    """Grafik garis omzet bulanan per tahun. bulanan: indeks 1..12, kolom = tahun."""
    fig = go.Figure()
    for t in ctx.tahun:
        y = [None if (t == ctx.Y and b > ctx.M) else float(v) for b, v in zip(range(1, 13), bulanan[t])]
        fig.add_trace(go.Scatter(x=BLN, y=y, mode="lines+markers", name=str(t), line=dict(width=3, color=ctx.warna[t]),
                                 customdata=[rp(v) for v in bulanan[t]],
                                 hovertemplate=f"%{{x}}<br>%{{customdata}}<extra>{t}</extra>"))
    nilai, label = ticks(float(bulanan.values.max()))
    fig.update_layout(title=judul, height=tinggi, legend=dict(orientation="h", y=-0.2),
                      yaxis=dict(tickvals=nilai, ticktext=label, rangemode="tozero", title="Omzet (Rupiah)"),
                      margin=dict(t=50, r=15, b=60, l=70))
    return fig


def tampilkan(kolom_atau_st, fig: go.Figure) -> None:
    kolom_atau_st.plotly_chart(fig, use_container_width=True)


def lbl(x: Optional[tuple]) -> str:
    return f"{BLN[x[1] - 1]} {x[0]}" if x else "-"


def pastikan_tema() -> None:
    """Buat .streamlit/config.toml bertema terang jika belum ada (berlaku setelah restart)."""
    cfg = Path(".streamlit/config.toml")
    if not cfg.exists():
        try:
            cfg.parent.mkdir(exist_ok=True)
            cfg.write_text(TEMA_TOML, encoding="utf-8")
        except OSError:
            pass


def ambil_rahasia(nama: str, bawaan: str = "") -> str:
    """Ambil nilai dari st.secrets bila tersedia, jika tidak pakai nilai bawaan."""
    try:
        return st.secrets.get(nama, "") or bawaan
    except Exception:
        return bawaan


def cek_password() -> None:
    """Gerbang password sederhana (hanya aktif jika APP_PASSWORD / secret terisi)."""
    kata_sandi = ambil_rahasia("APP_PASSWORD", APP_PASSWORD)
    if not kata_sandi or st.session_state.get("ok"):
        return
    banner("Laporan Kinerja Omzet Penjualan", "Masukkan password untuk melanjutkan")
    isian = st.text_input("Password", type="password")
    if isian:
        if hmac.compare_digest(isian, kata_sandi):
            st.session_state["ok"] = True
            st.rerun()
        st.error("Password salah.")
    st.stop()


# ============================================================ 6a. HALAMAN HARIAN
def _pembanding_harian(x: pd.DataFrame, t: pd.Timestamp) -> tuple:
    """(metrik hari t, metrik hari sama minggu lalu, daftar metrik hari sama N minggu terakhir yang ada transaksi)."""
    hist = [metrik(x[x["Tgl"] == t - pd.Timedelta(days=7 * i)]) for i in range(1, HARI_PEMBANDING + 1)]
    return metrik(x[x["Tgl"] == t]), hist[0], [h for h in hist if h["Jumlah nota"] > 0]


def _mtd(x: pd.DataFrame, t: pd.Timestamp) -> tuple:
    """(omzet bulan berjalan s.d. t, omzet bulan lalu s.d. tanggal yang sama)."""
    awal = t.replace(day=1)
    akhir_lalu = awal - pd.Timedelta(days=1)
    awal_lalu = akhir_lalu.replace(day=1)
    sd_lalu = awal_lalu.replace(day=min(t.day, akhir_lalu.day))
    return (x.loc[(x["Tgl"] >= awal) & (x["Tgl"] <= t), "Netto"].sum(),
            x.loc[(x["Tgl"] >= awal_lalu) & (x["Tgl"] <= sd_lalu), "Netto"].sum())


def _peringatan_harian(x: pd.DataFrame, t: pd.Timestamp, label: str) -> list:
    """Peringatan otomatis untuk satu store (atau gabungan) pada tanggal t."""
    m, _, ada = _pembanding_harian(x, t)
    r = rata(ada, "Sales Netto")
    if m["Jumlah nota"] == 0:
        return [f"{label}: belum ada transaksi pada tanggal ini, padahal biasanya ada."] if ada else []
    out = []
    if r and m["Sales Netto"] < AMBANG_OMZET_TURUN * r:
        out.append(f"{label}: omzet {rp(m['Sales Netto'])}, turun {pct(abs(growth(m['Sales Netto'], r)), False)} "
                   f"dari rata-rata hari yang sama {HARI_PEMBANDING} minggu terakhir.")
    if ada:
        diskon_biasa = sum(a["Diskon"] for a in ada) / max(sum(a["Bruto"] for a in ada), 1)
        diskon_kini = m["Diskon"] / m["Bruto"] if m["Bruto"] else 0
        if diskon_kini > AMBANG_DISKON_RASIO * diskon_biasa and diskon_kini - diskon_biasa >= AMBANG_DISKON_SELISIH:
            out.append(f"{label}: diskon {pct(diskon_kini * 100, False)} dari bruto, di atas biasanya ({pct(diskon_biasa * 100, False)}).")
        cogs_biasa = sum(a["COGS"] for a in ada) / max(sum(a["SAD"] for a in ada), 1)
        cogs_kini = m["COGS"] / m["SAD"] if m["SAD"] else 0
        if cogs_kini - cogs_biasa >= AMBANG_COGS_NAIK:
            out.append(f"{label}: COGS {pct(cogs_kini * 100, False)} dari Sales After Disc., di atas biasanya ({pct(cogs_biasa * 100, False)}).")
    return out


def halaman_harian(ctx: Konteks, pilih: str) -> None:
    """Laporan harian untuk satu store atau seluruh store."""
    semua = pilih == "SEMUA STORE"
    dd = ctx.df if semua else ctx.df[ctx.df["Store"] == pilih]
    nama = "Seluruh Store" if semua else f"Store {pilih}"
    banner("Laporan Harian", f"{nama} | Data terbaru s.d. {ctx.akhir:%d/%m/%Y}")
    tgl = st.date_input("Tanggal laporan", value=ctx.akhir.date(), min_value=ctx.df["Tgl"].min().date(),
                        max_value=ctx.akhir.date())
    t = pd.Timestamp(tgl)
    st.subheader(f"{HARI[t.dayofweek]}, {t:%d/%m/%Y}")
    if t.date() == ctx.akhir.date():
        st.caption("Ini hari terakhir di data. Pastikan data hari tersebut sudah lengkap sebelum laporan dibagikan.")

    m, minggu_lalu, ada = _pembanding_harian(dd, t)
    rt = rata(ada, "Sales Netto")
    g_mw, g_rt = growth(m["Sales Netto"], minggu_lalu["Sales Netto"]), (growth(m["Sales Netto"], rt) if rt else None)
    if m["Jumlah nota"] == 0:
        st.warning("Belum ada transaksi pada tanggal ini.")

    st.header("1. Ringkasan Hari Ini")
    kartu = []
    for nm, fm in [("Sales Netto", rp), ("Jumlah nota", angka), ("Rata-rata per nota", rp), ("Item terjual", angka),
                   ("Laba kotor", rp), ("Diskon", rp)]:
        r = rata(ada, nm)
        kartu.append((nm, fm(m[nm]),
                      f"Minggu lalu: {fm(minggu_lalu[nm])} ({pct(growth(m[nm], minggu_lalu[nm]))})<br>"
                      f"Rata-rata {HARI_PEMBANDING} minggu: {fm(r) if r is not None else 'n/a'} "
                      f"({pct(growth(m[nm], r)) if r else 'n/a'})"))
    kartu.append(("Gross margin", pct(m["Gross margin %"], False), f"Minggu lalu: {pct(minggu_lalu['Gross margin %'], False)}"))
    grid(kartu)

    st.header("2. Akumulasi Bulan Berjalan (MTD)")
    mtd, mtd_lalu = _mtd(dd, t)
    estimasi = mtd / t.day * t.days_in_month
    bulan_lalu = (t.replace(day=1) - pd.Timedelta(days=1))
    grid([(f"MTD {BLN[t.month - 1]} {t.year}", rp(mtd), f"Sampai tanggal {t.day}"),
          (f"{BLN[bulan_lalu.month - 1]} {bulan_lalu.year} s.d. tanggal sama", rp(mtd_lalu), ""),
          ("Pertumbuhan MTD", pct(growth(mtd, mtd_lalu)), "Dibanding bulan lalu"),
          ("Estimasi omzet akhir bulan", rp(estimasi), "Perkiraan kasar dari rata-rata harian")])

    st.header("3. Peringatan")
    notif = []
    for store in (ctx.stores if semua else [pilih]):
        notif += _peringatan_harian(dd[dd["Store"] == store], t, f"Store {store}")
    if notif:
        st.warning("\n".join("- " + n for n in notif))
    else:
        st.success("Tidak ada peringatan untuk tanggal ini.")
    st.caption(f"Peringatan: omzet di bawah {AMBANG_OMZET_TURUN:.0%} rata-rata hari yang sama {HARI_PEMBANDING} minggu terakhir, "
               f"diskon jauh di atas biasanya, COGS naik {AMBANG_COGS_NAIK * 100:.0f} poin persentase atau lebih, atau belum ada data.")

    baris = []
    if semua:
        st.header("4. Per Store")
        for store in ctx.stores:
            xs = dd[dd["Store"] == store]
            ms, ms_lalu, ada_s = _pembanding_harian(xs, t)
            rs = rata(ada_s, "Sales Netto")
            mtd_s, mtd_s_lalu = _mtd(xs, t)
            baris.append({"StoreCode": store, "Sales Netto": ms["Sales Netto"],
                          "vs Minggu Lalu": growth(ms["Sales Netto"], ms_lalu["Sales Netto"]),
                          f"vs Rata-rata {HARI_PEMBANDING} Minggu": growth(ms["Sales Netto"], rs) if rs else None,
                          "Nota": ms["Jumlah nota"], "Rata-rata per Nota": ms["Rata-rata per nota"],
                          "Diskon %": (ms["Diskon"] / ms["Bruto"] * 100) if ms["Bruto"] else None,
                          "MTD": mtd_s, "MTD vs Bulan Lalu": growth(mtd_s, mtd_s_lalu)})
        tabel = pd.DataFrame(baris).sort_values("Sales Netto", ascending=False)
        pemformat = {"Sales Netto": rp, "vs Minggu Lalu": pct, f"vs Rata-rata {HARI_PEMBANDING} Minggu": pct, "Nota": angka,
                     "Rata-rata per Nota": rp, "Diskon %": lambda v: pct(v, False), "MTD": rp, "MTD vs Bulan Lalu": pct}
        st.dataframe(tabel_format(tabel, pemformat), use_container_width=True, hide_index=True)

    if m["Jumlah nota"] > 0:
        st.header("5. Rincian Hari Ini" if semua else "4. Rincian Hari Ini")
        hari = dd[dd["Tgl"] == t]
        hari = hari.assign(Diskon=(hari["Bruto"] - hari["SAD"]).clip(lower=0))
        kiri, kanan = st.columns(2)
        tampilkan(kiri, hbar("Omzet per Group", hari.groupby("Group")["Netto"].sum(), BIRU))
        tampilkan(kanan, hbar("Metode Pembayaran", hari.groupby("Payment")["Netto"].sum(), ORANYE))
        tampilkan(kiri, hbar("10 Menu Terlaris", hari.groupby("Menu")["Netto"].sum(), UNGU))
        tampilkan(kanan, hbar("10 Menu Paling Banyak Didiskon", hari.groupby("Menu")["Diskon"].sum(), MERAH))

    st.header("Ringkasan")
    teks = [f"LAPORAN HARIAN - {nama}", f"{HARI[t.dayofweek]}, {t:%d/%m/%Y}", "",
            f"Sales Netto: {rp(m['Sales Netto'])} ({pct(g_mw)} vs minggu lalu; {pct(g_rt)} vs rata-rata {HARI_PEMBANDING} minggu)",
            f"Nota: {angka(m['Jumlah nota'])} | Rata-rata per nota: {rp(m['Rata-rata per nota'])}",
            f"Diskon: {rp(m['Diskon'])} | Laba kotor: {rp(m['Laba kotor'])} (margin {pct(m['Gross margin %'], False)})",
            f"MTD: {rp(mtd)} ({pct(growth(mtd, mtd_lalu))} vs bulan lalu) | Estimasi akhir bulan: {rp(estimasi)}"]
    if semua:
        kunci = f"vs Rata-rata {HARI_PEMBANDING} Minggu"
        teks += ["", "Per store:"] + [f"- {b['StoreCode']}: {rp(b['Sales Netto'])} ({pct(b[kunci])} vs rata-rata)"
                                      for b in sorted(baris, key=lambda z: -z["Sales Netto"])]
    if notif:
        teks += ["", "Perlu perhatian:"] + ["- " + n for n in notif]
    st.code("\n".join(teks), language=None)


# ============================================================ 6b. HALAMAN BULANAN
@dataclass
class Laporan:
    """Hasil perhitungan untuk store yang dipilih pada halaman bulanan."""
    d: pd.DataFrame
    nama: str
    S: dict
    SA: dict
    rank: list
    kontribusi: str
    ket_kontribusi: str
    pesan: list


def siapkan_laporan(ctx: Konteks, pilih: str) -> Laporan:
    semua = pilih == "SEMUA STORE"
    d = ctx.df if semua else ctx.df[ctx.df["Store"] == pilih]
    S = hitung(d, ctx)
    SA = S if semua else hitung(ctx.df, ctx)
    rank = [(s, S if s == pilih else hitung(ctx.df[ctx.df["Store"] == s], ctx)) for s in ctx.stores]
    rank.sort(key=lambda x: x[1]["tot"][ctx.Y], reverse=True)
    total = SA["tot"][ctx.Y]
    if semua:
        kontribusi, ket = "100%", f"{len(ctx.stores)} store"
    else:
        kontribusi = pct(S["tot"][ctx.Y] / total * 100, False) if total else "n/a"
        ket = f"Peringkat {[r[0] for r in rank].index(pilih) + 1} dari {len(ctx.stores)} store"
    return Laporan(d, "Seluruh Store" if semua else f"Store {pilih}", S, SA, rank, kontribusi, ket,
                   cek_data(ctx.df, ctx.akhir))


def bagian_kualitas_data(ctx: Konteks, lap: Laporan) -> None:
    if lap.pesan:
        st.warning(f"Kualitas data: ada {len(lap.pesan)} catatan yang perlu dicek sebelum laporan dibagikan.")
    else:
        st.success("Kualitas data: tidak ada catatan.")
    with st.expander("Detail kualitas data"):
        for p in lap.pesan[:25]:
            st.write("- " + p)
        if len(lap.pesan) > 25:
            st.caption(f"... dan {len(lap.pesan) - 25} catatan lain")
        hm = (ctx.df.assign(P=ctx.df["Tgl"].dt.strftime("%Y-%m")).groupby(["Store", "P"])["Tgl"].nunique()
              .unstack(fill_value=0))
        fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=list(hm.index), colorscale="Blues",
                                   hovertemplate="%{y}<br>%{x}: %{z} hari ada transaksi<extra></extra>"))
        fig.update_layout(title="Jumlah hari yang memiliki transaksi per store per bulan",
                          height=max(220, 60 * len(hm) + 120), margin=dict(t=50, r=15, b=40, l=10))
        tampilkan(st, fig)


def bagian_ringkasan(ctx: Konteks, lap: Laporan) -> None:
    S, Y, P = lap.S, ctx.Y, ctx.P
    tot, pt = S["tot"], S["pt"]
    nota = int(pt.loc[Y, "trn"])
    n = f"**{lap.nama}** mencatat total omzet (Sales Netto) **{rp(tot.sum())}** pada periode {ctx.tahun[0]}-{Y}. "
    n += f"Sampai dengan tanggal {ctx.Dd}/{ctx.M}/{Y}, omzet tahun berjalan sebesar **{rp(S['ytd_now'])}**"
    if S["ytd_g"] is not None:
        n += (f", {'naik' if S['ytd_g'] >= 0 else 'turun'} **{pct(abs(S['ytd_g']), False)}** "
              f"dibanding rentang tanggal yang sama tahun {P}")
    n += ". "
    if S["hi"]:
        n += f"Omzet bulanan tertinggi terjadi pada {lbl(S['hi'])} ({rp(S['hi'][2])})"
        n += f", sedangkan terendah pada {lbl(S['lo'])} ({rp(S['lo'][2])}). " if S["lo"] else ". "
    if nota:
        n += f"Pada {Y} tercatat {angka(nota)} nota dengan rata-rata {rp(tot[Y] / nota)} per nota. "
    if lap.nama != "Seluruh Store":
        n += f"Store ini berkontribusi {lap.kontribusi} dari total omzet {Y} ({lap.ket_kontribusi.lower()})."
    st.markdown('<div class="card narasi">' + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", n) + "</div>", unsafe_allow_html=True)


def bagian_kpi(ctx: Konteks, lap: Laporan) -> list:
    S, Y, P = lap.S, ctx.Y, ctx.P
    tot, pt = S["tot"], S["pt"]
    ada_p = P in pt.index

    def nota(t):
        return int(pt.loc[t, "trn"]) if t in pt.index else 0

    def margin(t):
        return (pt.loc[t, "sad"] - pt.loc[t, "cogs"]) / pt.loc[t, "sad"] * 100 if pt.loc[t, "sad"] else None

    def cogs_pct(t):
        return pt.loc[t, "cogs"] / pt.loc[t, "sad"] * 100 if pt.loc[t, "sad"] else None

    def laba(t):
        return pt.loc[t, "sad"] - pt.loc[t, "cogs"]

    kpi = [("Total omzet periode", rp(tot.sum()), f"{ctx.tahun[0]} - {Y}"),
           (f"Omzet {Y} (YTD s.d. {ctx.Dd}/{ctx.M})", rp(S["ytd_now"]), f"{P}: {rp(S['ytd_prev'])} (tanggal sama)"),
           (f"Pertumbuhan YTD vs {P}", pct(S["ytd_g"]), "Rentang tanggal yang sama")]
    kpi += [(f"Pertumbuhan {t} vs {t - 1}", pct(growth(tot[t], tot[t - 1])), f"Omzet {t}: {singkat(tot[t])}")
            for t in ctx.tahun[1:]]
    kpi += [
        (f"Rata-rata omzet bulanan {Y}", rp(S["rb"][Y]), f"{P}: {singkat(S['rb'].get(P, 0))}"),
        (f"Jumlah transaksi (nota) {Y}", angka(nota(Y)), f"{P}: {angka(nota(P))}"),
        (f"Rata-rata nilai per nota {Y}", rp(tot[Y] / nota(Y)) if nota(Y) else "n/a",
         f"{P}: {rp(tot[P] / nota(P)) if P in tot.index and nota(P) else 'n/a'}"),
        (f"Item terjual {Y}", angka(pt.loc[Y, "qty"]), f"{P}: {angka(pt.loc[P, 'qty']) if ada_p else 0}"),
        (f"Sales After Disc. {Y}", rp(pt.loc[Y, "sad"]), "Sebelum service charge & pajak"),
        (f"Service charge + pajak {Y}", rp(pt.loc[Y, "sc"] + pt.loc[Y, "tax"]),
         f"SC {singkat(pt.loc[Y, 'sc'])} | Pajak {singkat(pt.loc[Y, 'tax'])}"),
        (f"Total diskon {Y}", rp(max(0, pt.loc[Y, "bruto"] - pt.loc[Y, "sad"])), "TransBruto - Sales After Disc."),
        (f"COGS {Y}", rp(pt.loc[Y, "cogs"]), f"{P}: {rp(pt.loc[P, 'cogs']) if ada_p else 'n/a'}"),
        (f"COGS % dari Sales After Disc. {Y}", pct(cogs_pct(Y), False), f"{P}: {pct(cogs_pct(P), False) if ada_p else 'n/a'}"),
        (f"Laba kotor {Y}", rp(laba(Y)), f"{P}: {rp(laba(P)) if ada_p else 'n/a'}"),
        (f"Gross margin {Y}", pct(margin(Y), False), f"{P}: {pct(margin(P), False) if ada_p else 'n/a'}"),
        ("Bulan omzet tertinggi", lbl(S["hi"]), rp(S["hi"][2]) if S["hi"] else ""),
        ("Bulan omzet terendah", lbl(S["lo"]), rp(S["lo"][2]) if S["lo"] else ""),
        (f"Kontribusi terhadap total {Y}", lap.kontribusi, lap.ket_kontribusi)]
    grid(kpi)
    return kpi


def bagian_perbandingan(ctx: Konteks, d: pd.DataFrame) -> None:
    dmin, dmax = d["Tgl"].min().date(), d["Tgl"].max().date()
    kiri, kanan = st.columns(2)
    rentang = kiri.date_input("Periode utama", value=(max(dmin, ctx.akhir.replace(day=1).date()), dmax),
                              min_value=dmin, max_value=dmax)
    mode = kanan.radio("Dibandingkan dengan", ["Tahun lalu (tanggal sama)", "Periode sebelumnya (panjang sama)", "Pilih manual"])
    rentang2 = None
    if mode == "Pilih manual":
        rentang2 = kanan.date_input("Periode pembanding", value=(dmin, dmin), min_value=dmin, max_value=dmax)
    lengkap = isinstance(rentang, tuple) and len(rentang) == 2 and (
        mode != "Pilih manual" or (isinstance(rentang2, tuple) and len(rentang2) == 2))
    if not lengkap:
        st.info("Pilih tanggal awal dan tanggal akhir pada kalender.")
        return
    a1, a2 = pd.Timestamp(rentang[0]), pd.Timestamp(rentang[1])
    if mode.startswith("Tahun"):
        b1, b2 = a1 - pd.DateOffset(years=1), a2 - pd.DateOffset(years=1)
    elif mode.startswith("Periode"):
        durasi = a2 - a1 + pd.Timedelta(days=1)
        b2 = a1 - pd.Timedelta(days=1)
        b1 = b2 - durasi + pd.Timedelta(days=1)
    else:
        b1, b2 = pd.Timestamp(rentang2[0]), pd.Timestamp(rentang2[1])
    ma = metrik(d[(d["Tgl"] >= a1) & (d["Tgl"] <= a2)])
    mb = metrik(d[(d["Tgl"] >= b1) & (d["Tgl"] <= b2)])
    kartu = [("Pertumbuhan Sales Netto", pct(growth(ma["Sales Netto"], mb["Sales Netto"])),
              f"{rp(ma['Sales Netto'])} vs {rp(mb['Sales Netto'])}")]
    for nm, fm in [("Sales Netto", rp), ("Jumlah nota", angka), ("Item terjual", angka), ("Rata-rata per nota", rp),
                   ("COGS", rp), ("Laba kotor", rp), ("Diskon", rp)]:
        kartu.append((nm, fm(ma[nm]), f"Pembanding: {fm(mb[nm])} ({pct(growth(ma[nm], mb[nm]))})"))
    kartu.append(("Gross margin", pct(ma["Gross margin %"], False), f"Pembanding: {pct(mb['Gross margin %'], False)}"))
    grid(kartu)
    st.caption(f"Periode utama {a1:%d/%m/%Y} - {a2:%d/%m/%Y} dibandingkan dengan {b1:%d/%m/%Y} - {b2:%d/%m/%Y}.")


def bagian_tren(ctx: Konteks, lap: Laporan) -> None:
    kiri, kanan = st.columns([2.4, 1])
    tampilkan(kiri, grafik_garis(f"Tren Omzet Bulanan - {lap.nama}", lap.S["bul"], ctx))
    nilai = [float(lap.S["tot"][t]) for t in ctx.tahun]
    tv, tt = ticks(max(nilai))
    fig = go.Figure(go.Bar(x=[str(t) for t in ctx.tahun], y=nilai, marker_color=[ctx.warna[t] for t in ctx.tahun],
                           text=[singkat(v) for v in nilai], textposition="outside", customdata=[rp(v) for v in nilai],
                           hovertemplate="%{x}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title="Total Omzet per Tahun", height=380, yaxis=dict(tickvals=tv, ticktext=tt),
                      margin=dict(t=50, r=15, b=50, l=70))
    tampilkan(kanan, fig)


def bagian_komposisi(ctx: Konteks, lap: Laporan) -> None:
    Y, S = ctx.Y, lap.S
    kiri, kanan = st.columns(2)
    tampilkan(kiri, hbar(f"Omzet per Group ({Y})", S["grp"], BIRU))
    tampilkan(kanan, hbar(f"Omzet per Department ({Y})", S["dep"], HIJAU))
    tampilkan(kiri, hbar(f"COGS per Group ({Y})", lap.d[lap.d["Tahun"] == Y].groupby("Group")["COGS"].sum(), MERAH))
    tampilkan(kanan, hbar(f"Metode Pembayaran ({Y})", S["pay"], ORANYE))


def _menu_engineering(menu: pd.DataFrame) -> None:
    """Klasifikasi menu: Bintang, Kuda Kerja, Tanda Tanya, Beban (popularitas vs laba kotor per item)."""
    me = menu[menu["Qty"] > 0].copy()
    if len(me) < 4:
        st.info("Menu terlalu sedikit untuk dianalisis pada filter ini.")
        return
    me["CM/item"] = me["Laba Kotor"] / me["Qty"]
    ambang_pop = 0.7 / len(me) * me["Qty"].sum()
    ambang_cm = me["Laba Kotor"].sum() / me["Qty"].sum()
    me["Kelas"] = [("Bintang" if cm >= ambang_cm else "Kuda Kerja") if q >= ambang_pop
                   else ("Tanda Tanya" if cm >= ambang_cm else "Beban") for q, cm in zip(me["Qty"], me["CM/item"])]
    warna = {"Bintang": HIJAU, "Kuda Kerja": BIRU, "Tanda Tanya": ORANYE, "Beban": MERAH}
    fig = px.scatter(me, x="Qty", y="CM/item", color="Kelas", color_discrete_map=warna, hover_name="Menu",
                     hover_data={"Qty": ":,.0f", "CM/item": ":,.0f", "Laba Kotor": ":,.0f", "Kelas": False})
    fig.add_vline(x=ambang_pop, line_dash="dash", line_color="#999")
    fig.add_hline(y=ambang_cm, line_dash="dash", line_color="#999")
    fig.update_layout(title="Menu Engineering: popularitas vs laba kotor per item", height=520,
                      xaxis_title="Item terjual (Qty)", yaxis_title="Laba kotor per item (Rp)")
    tampilkan(st, fig)
    saran = {"Bintang": "Laris dan laba tinggi: pertahankan kualitas, jaga stok, tampilkan menonjol.",
             "Kuda Kerja": "Laris tapi laba kecil: pertimbangkan naik harga atau tekan COGS.",
             "Tanda Tanya": "Laba bagus tapi kurang laku: promosikan atau tempatkan lebih menonjol.",
             "Beban": "Kurang laku dan laba kecil: evaluasi resep dan harga, atau keluarkan dari menu."}
    ringkas = pd.DataFrame([{"Kelas": k, "Jumlah menu": int((me["Kelas"] == k).sum()),
                             "Sales Netto": me.loc[me["Kelas"] == k, "Netto"].sum(),
                             "Laba Kotor": me.loc[me["Kelas"] == k, "Laba Kotor"].sum(), "Saran": saran[k]} for k in saran])
    st.dataframe(tabel_format(ringkas, {"Sales Netto": rp, "Laba Kotor": rp}), use_container_width=True, hide_index=True)
    kelas = st.selectbox("Lihat daftar menu pada kelas", list(saran))
    daftar = (me[me["Kelas"] == kelas].sort_values("Laba Kotor", ascending=False)
              [["Menu", "Group", "Dept", "Qty", "CM/item", "Laba Kotor", "Netto"]]
              .rename(columns={"Netto": "Sales Netto", "CM/item": "Laba kotor per item"}))
    st.dataframe(tabel_format(daftar, {"Qty": angka, "Laba kotor per item": rp, "Laba Kotor": rp, "Sales Netto": rp}),
                 use_container_width=True, hide_index=True)
    st.caption("Ambang popularitas = 70% dari rata-rata porsi penjualan menu; ambang margin = rata-rata laba kotor per item. "
               "COGS dianggap total per baris.")


def bagian_analisis_menu(ctx: Konteks, d: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Analisis interaktif Group > Department > Menu. Mengembalikan tabel menu (untuk ekspor)."""
    c1, c2, c3, c4 = st.columns(4)
    tahun_pilih = c1.selectbox("Tahun", sorted(ctx.tahun, reverse=True))
    dm = d[d["Tahun"] == tahun_pilih]
    grup = c2.selectbox("Group", ["Semua"] + sorted(dm["Group"].unique()))
    if grup != "Semua":
        dm = dm[dm["Group"] == grup]
    dept = c3.selectbox("Department", ["Semua"] + sorted(dm["Dept"].unique()))
    if dept != "Semua":
        dm = dm[dm["Dept"] == dept]
    cari = c4.text_input("Cari nama menu")
    if cari:
        dm = dm[dm["Menu"].str.contains(cari, case=False, na=False, regex=False)]
    if dm.empty:
        st.info("Tidak ada data untuk filter tersebut.")
        return None

    menu = (dm.groupby("Menu").agg(Group=("Group", "first"), Dept=("Dept", "first"), Qty=("Qty", "sum"),
                                   Netto=("Netto", "sum"), SAD=("SAD", "sum"), COGS=("COGS", "sum"),
                                   Nota=("Nota", "nunique")).reset_index())
    menu["Laba Kotor"] = menu["SAD"] - menu["COGS"]
    menu["Margin %"] = (menu["Laba Kotor"] / menu["SAD"] * 100).where(menu["SAD"] > 0)
    total = menu["Netto"].sum()
    menu["Kontribusi %"] = menu["Netto"] / total * 100 if total else 0.0
    menu = menu.sort_values("Netto", ascending=False)
    sad, qty, cogs = menu["SAD"].sum(), menu["Qty"].sum(), menu["COGS"].sum()
    grid([("Sales Netto", rp(total), ""), ("Item terjual", angka(qty), ""), ("COGS", rp(cogs), ""),
          ("Laba kotor", rp(sad - cogs), ""), ("Gross margin", pct((sad - cogs) / sad * 100, False) if sad else "n/a", "")])

    tab_tree, tab_top, tab_tabel, tab_tren, tab_eng = st.tabs(
        ["Treemap (klik untuk drill-down)", "Top Menu", "Tabel Menu", "Tren per Menu", "Menu Engineering"])
    tabel_menu = None
    with tab_tree:
        positif = dm[dm["Netto"] > 0]
        if positif.empty:
            st.info("Tidak ada omzet positif pada filter ini.")
        else:
            fig = px.treemap(positif, path=["Group", "Dept", "Menu"], values="Netto")
            fig.update_traces(hovertemplate="%{label}<br>Rp %{value:,.0f}<extra></extra>")
            fig.update_layout(height=520, margin=dict(t=30, l=10, r=10, b=10))
            tampilkan(st, fig)
    with tab_top:
        ukuran = st.selectbox("Urutkan berdasarkan", ["Netto", "Qty", "COGS", "Laba Kotor"])
        jumlah = st.slider("Jumlah menu", 5, 30, 15)
        tampilkan(st, hbar(f"Top {jumlah} Menu - {ukuran} ({tahun_pilih})", menu.set_index("Menu")[ukuran], UNGU,
                           jumlah, ukuran != "Qty"))
    with tab_tabel:
        tabel_menu = (menu[["Menu", "Group", "Dept", "Qty", "Netto", "SAD", "COGS", "Laba Kotor", "Margin %", "Kontribusi %", "Nota"]]
                      .rename(columns={"Netto": "Sales Netto", "SAD": "Sales After Disc.", "Nota": "Jumlah Nota"})
                      .reset_index(drop=True))
        pemformat = {"Qty": angka, "Sales Netto": rp, "Sales After Disc.": rp, "COGS": rp, "Laba Kotor": rp,
                     "Jumlah Nota": angka, "Margin %": lambda v: pct(v, False), "Kontribusi %": lambda v: pct(v, False)}
        st.dataframe(tabel_format(tabel_menu, pemformat), use_container_width=True, hide_index=True)
        st.download_button("Unduh tabel (CSV)", tabel_menu.to_csv(index=False).encode("utf-8-sig"),
                           f"analisis_menu_{tahun_pilih}.csv", "text/csv")
    with tab_tren:
        pilihan = st.selectbox("Pilih menu", list(menu["Menu"]))
        bulanan = (d[d["Menu"] == pilihan].pivot_table(index="Bulan", columns="Tahun", values="Netto", aggfunc="sum", fill_value=0)
                   .reindex(index=range(1, 13), columns=ctx.tahun, fill_value=0))
        tampilkan(st, grafik_garis(f"Tren Omzet Bulanan - {pilihan}", bulanan, ctx))
    with tab_eng:
        _menu_engineering(menu)
    return tabel_menu


def bagian_pola_waktu(ctx: Konteks, d: pd.DataFrame) -> tuple:
    """Rata-rata omzet per hari dalam seminggu dan per tanggal. Mengembalikan (tahun terpilih, data tahun itu)."""
    tahun_pilih = st.selectbox("Tahun analisis (Pola Waktu dan Diskon)", sorted(ctx.tahun, reverse=True), key="thw")
    dw = d[d["Tahun"] == tahun_pilih]
    harian = dw.groupby("Tgl")["Netto"].sum()
    if harian.empty:
        st.info("Tidak ada data pada tahun tersebut.")
        return tahun_pilih, dw
    per_hari = harian.groupby(harian.index.dayofweek).mean().reindex(range(7))
    per_tanggal = harian.groupby(harian.index.day).mean().reindex(range(1, 32))
    kiri, kanan = st.columns(2)
    fig = go.Figure(go.Bar(x=HARI, y=per_hari.values, marker_color=[HIJAU if i >= 5 else BIRU for i in range(7)],
                           text=[singkat(v) if pd.notna(v) else "" for v in per_hari.values], textposition="outside",
                           customdata=[rp(v) if pd.notna(v) else "-" for v in per_hari.values],
                           hovertemplate="%{x}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title=f"Rata-rata Omzet per Hari ({tahun_pilih})", height=360, yaxis=dict(visible=False),
                      margin=dict(t=50, r=15, b=40, l=15))
    tampilkan(kiri, fig)
    fig = go.Figure(go.Bar(x=list(range(1, 32)), y=per_tanggal.values, marker_color=UNGU,
                           customdata=[rp(v) if pd.notna(v) else "-" for v in per_tanggal.values],
                           hovertemplate="Tanggal %{x}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title=f"Rata-rata Omzet per Tanggal ({tahun_pilih})", height=360, yaxis=dict(visible=False),
                      xaxis=dict(title="Tanggal", dtick=1), margin=dict(t=50, r=15, b=40, l=15))
    tampilkan(kanan, fig)
    st.caption(f"Rata-rata omzet tertinggi terjadi pada hari {HARI[int(per_hari.idxmax())]} ({rp(per_hari.max())}). "
               "Rata-rata dihitung hanya dari hari yang memiliki transaksi.")
    return tahun_pilih, dw


def bagian_diskon_pembayaran(dw: pd.DataFrame, tahun_pilih: int) -> None:
    dw = dw.assign(Diskon=(dw["Bruto"] - dw["SAD"]).clip(lower=0), Periode=dw["Tgl"].dt.strftime("%Y-%m"))
    if dw.empty:
        st.info("Tidak ada data pada tahun tersebut.")
        return
    bd = dw.groupby("Periode").agg(Diskon=("Diskon", "sum"), Bruto=("Bruto", "sum"))
    bd["Pct"] = (bd["Diskon"] / bd["Bruto"] * 100).where(bd["Bruto"] > 0)
    tv, tt = ticks(float(bd["Diskon"].max()))
    fig = go.Figure()
    fig.add_trace(go.Bar(x=list(bd.index), y=bd["Diskon"], name="Diskon (Rp)", marker_color=MERAH,
                         customdata=[rp(v) for v in bd["Diskon"]], hovertemplate="%{x}<br>%{customdata}<extra>Diskon</extra>"))
    fig.add_trace(go.Scatter(x=list(bd.index), y=bd["Pct"], name="Diskon % dari Bruto", yaxis="y2", mode="lines+markers",
                             line=dict(color="#1f4e8c", width=3)))
    fig.update_layout(title=f"Tren Diskon per Bulan ({tahun_pilih})", height=380, yaxis=dict(tickvals=tv, ticktext=tt),
                      yaxis2=dict(overlaying="y", side="right", ticksuffix="%", showgrid=False),
                      legend=dict(orientation="h", y=-0.2), margin=dict(t=50, r=50, b=60, l=70))
    tampilkan(st, fig)
    kiri, kanan = st.columns(2)
    tampilkan(kiri, hbar(f"Diskon per Group ({tahun_pilih})", dw.groupby("Group")["Diskon"].sum(), MERAH))
    tampilkan(kanan, hbar(f"10 Menu Paling Banyak Didiskon ({tahun_pilih})", dw.groupby("Menu")["Diskon"].sum(), MERAH))
    pv = dw.pivot_table(index="Periode", columns="Payment", values="Netto", aggfunc="sum", fill_value=0)
    fig = go.Figure()
    for i, metode in enumerate(pv.columns):
        fig.add_trace(go.Bar(x=list(pv.index), y=pv[metode], name=str(metode), marker_color=px.colors.qualitative.Plotly[i % 10]))
    fig.update_layout(barmode="stack", barnorm="percent", title=f"Komposisi Metode Pembayaran per Bulan ({tahun_pilih})",
                      height=380, yaxis=dict(ticksuffix="%"), legend=dict(orientation="h", y=-0.2),
                      margin=dict(t=50, r=15, b=60, l=50))
    tampilkan(st, fig)


def bagian_rincian_bulanan(ctx: Konteks, d: pd.DataFrame) -> None:
    ukur = st.radio("Tampilkan", ["Sales Netto", "COGS", "Laba Kotor"], horizontal=True)
    nilai = d["SAD"] - d["COGS"] if ukur == "Laba Kotor" else d["COGS" if ukur == "COGS" else "Netto"]
    bm = (d.assign(Nilai=nilai).pivot_table(index="Bulan", columns="Tahun", values="Nilai", aggfunc="sum", fill_value=0)
          .reindex(index=range(1, 13), columns=ctx.tahun, fill_value=0))

    def sel(t, i):
        if t == ctx.Y and i + 1 > ctx.M:
            return "-"
        return rp(bm[t].iloc[i]) + (" *" if (t == ctx.Y and i + 1 == ctx.M and ctx.partial) else "")

    tabel = pd.DataFrame({str(t): [sel(t, i) for i in range(12)] for t in ctx.tahun}, index=BLN)
    tabel.loc["TOTAL"] = [rp(bm[t].sum()) for t in ctx.tahun]
    tabel.index.name = "Bulan"
    st.dataframe(tabel, use_container_width=True)


def bagian_peringkat(ctx: Konteks, lap: Laporan) -> None:
    Y = ctx.Y
    total = lap.SA["tot"][Y]
    baris = [{"StoreCode": s, **{str(t): rp(h["tot"][t]) for t in ctx.tahun},
              f"Kontribusi {Y}": pct(h["tot"][Y] / total * 100, False) if total else "n/a",
              "Growth YTD": pct(h["ytd_g"])} for s, h in lap.rank]
    baris.append({"StoreCode": "TOTAL", **{str(t): rp(lap.SA["tot"][t]) for t in ctx.tahun},
                  f"Kontribusi {Y}": "100%", "Growth YTD": pct(lap.SA["ytd_g"])})
    st.dataframe(pd.DataFrame(baris), use_container_width=True, hide_index=True)


def catatan_kaki(ctx: Konteks) -> None:
    cat = ("Omzet = Sales Netto (termasuk service charge dan pajak). Pertumbuhan YTD membandingkan rentang tanggal yang "
           "sama tahun sebelumnya. Gross margin = (Sales After Disc. - COGS) / Sales After Disc. ")
    if ctx.partial:
        cat += f"* Bulan {BLN[ctx.M - 1]} {ctx.Y} belum penuh (data s.d. tanggal {ctx.Dd}). "
    if ctx.df.attrs.get("dilewati"):
        cat += f"{angka(ctx.df.attrs['dilewati'])} baris dilewati karena tanggal/angka tidak terbaca."
    st.caption(cat)


def buat_excel(ctx: Konteks, lap: Laporan, kpi: list, tabel_menu: Optional[pd.DataFrame]) -> bytes:
    """Ekspor laporan ke Excel (angka tetap numerik)."""
    d, out = lap.d, io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(kpi, columns=["KPI", "Nilai", "Keterangan"]).to_excel(xw, sheet_name="KPI", index=False)
        blok = []
        for nama, seri in [("Sales Netto", d["Netto"]), ("COGS", d["COGS"]), ("Laba Kotor", d["SAD"] - d["COGS"])]:
            pvt = (d.assign(Nilai=seri).pivot_table(index="Bulan", columns="Tahun", values="Nilai", aggfunc="sum", fill_value=0)
                   .reindex(index=range(1, 13), columns=ctx.tahun, fill_value=0))
            pvt.columns = [f"{nama} {t}" for t in ctx.tahun]
            blok.append(pvt)
        bulanan = pd.concat(blok, axis=1)
        bulanan.index = BLN
        bulanan.to_excel(xw, sheet_name="Bulanan", index_label="Bulan")
        pd.DataFrame([{"StoreCode": s, **{str(t): float(h["tot"][t]) for t in ctx.tahun}, "Growth YTD %": h["ytd_g"]}
                      for s, h in lap.rank]).to_excel(xw, sheet_name="Peringkat Store", index=False)
        if tabel_menu is not None:
            tabel_menu.to_excel(xw, sheet_name="Menu", index=False)
        pd.DataFrame({"Catatan": lap.pesan or ["Tidak ada catatan"]}).to_excel(xw, sheet_name="Kualitas Data", index=False)
    return out.getvalue()


def halaman_bulanan(ctx: Konteks, pilih: str) -> None:
    lap = siapkan_laporan(ctx, pilih)
    banner("Laporan Kinerja Omzet Penjualan",
           f"{lap.nama} | Data {ctx.df['Tgl'].min():%d/%m/%Y} s.d. {ctx.akhir:%d/%m/%Y} | {len(ctx.stores)} store | "
           "Basis omzet: Sales Netto | Diperbarui otomatis tiap 5 menit")
    bagian_kualitas_data(ctx, lap)

    st.header("1. Ringkasan Eksekutif")
    bagian_ringkasan(ctx, lap)
    st.header("2. Indikator Kinerja Utama (KPI)")
    kpi = bagian_kpi(ctx, lap)
    st.header("3. Perbandingan Periode")
    bagian_perbandingan(ctx, lap.d)
    st.header("4. Analisis Tren")
    bagian_tren(ctx, lap)
    st.header("5. Komposisi Omzet")
    bagian_komposisi(ctx, lap)
    st.header("6. Analisis Group, Department, dan Menu")
    tabel_menu = bagian_analisis_menu(ctx, lap.d)
    st.header("7. Pola Waktu")
    tahun_pilih, dw = bagian_pola_waktu(ctx, lap.d)
    st.header("8. Analisis Diskon dan Pembayaran")
    bagian_diskon_pembayaran(dw, tahun_pilih)
    st.header("9. Rincian Bulanan")
    bagian_rincian_bulanan(ctx, lap.d)
    st.header("10. Peringkat Seluruh Store")
    bagian_peringkat(ctx, lap)
    catatan_kaki(ctx)

    with st.sidebar:
        st.divider()
        try:
            st.download_button("Unduh laporan (Excel)", buat_excel(ctx, lap, kpi, tabel_menu),
                               f"laporan_omzet_{lap.nama.replace(' ', '_')}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except ImportError:
            st.caption("Untuk ekspor Excel, instal dulu: pip install openpyxl")


# ============================================================ 7. APLIKASI
def muat_data(file, sumber: str) -> pd.DataFrame:
    """Muat data dari file unggahan atau Google Sheets; hentikan halaman dengan pesan jelas jika gagal."""
    try:
        if file is not None:
            df = muat("upload", file.getvalue())
        elif sumber:
            df = muat(sumber)
        else:
            banner("Laporan Kinerja Omzet Penjualan", "Sumber data belum diatur")
            st.info("Isi CSV_URL dengan link Publish to web (CSV) dari Google Sheets, atau unggah file CSV di sidebar.")
            st.stop()
    except DataError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001 - tampilkan apa pun penyebabnya kepada pengguna
        st.error(f"Gagal memuat data: {e}\nAnda bisa mengunggah CSV manual di sidebar.")
        st.stop()
    if df.empty:
        st.error("Tidak ada baris valid. Periksa format TransDate (contoh 20240906) dan Sales Netto.")
        st.stop()
    return df


def main() -> None:
    pastikan_tema()
    st.set_page_config(page_title=f"{BRAND} - Laporan Kinerja Omzet", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    cek_password()

    with st.sidebar:
        st.header("Filter")
        file = st.file_uploader("Atau unggah CSV manual", type=["csv", "txt"])
        if st.button("Muat ulang data"):
            st.cache_data.clear()
            st.rerun()

    ctx = Konteks.dari(muat_data(file, url_csv(ambil_rahasia("CSV_URL", CSV_URL))))
    with st.sidebar:
        halaman = st.radio("Halaman", ["Laporan Bulanan", "Laporan Harian"])
        pilih = st.selectbox("StoreCode", ["SEMUA STORE"] + ctx.stores)

    if halaman == "Laporan Harian":
        halaman_harian(ctx, pilih)
    else:
        halaman_bulanan(ctx, pilih)


main()
