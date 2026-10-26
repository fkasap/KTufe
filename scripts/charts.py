"""
Haftalık rapor grafikleri (PNG, reports/charts/):
  <bolge>_anagrup_haftalik.png  13 ana grup + manşet, son 7 gün değişimi (yatay çubuk)
  <bolge>_anagrup_aylik.png     13 ana grup + manşet, ay-içi değişim (ilk 24 gün geo. ort.)
  <bolge>_maddeler_aylik.png    en çok artan / azalan 15'er madde (aylık)
  TR_ktufe_vs_tuik.png          aylık değişim: KTüfe (TR) vs TÜİK, son 12 ay

Tasarım: tek seri -> tek renk, manşet çubuğu koyu; değer etiketleri metin renginde;
ızgara soluk; sıralı çubuklar; karşılaştırma grafiğinde 2 renk + legend + etiket.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from index_engine import monthly_index

OUT = ROOT / "reports/charts"; OUT.mkdir(parents=True, exist_ok=True)
C_MAIN, C_HEAD, C_NEG, C_TUIK = "#9B2C2C", "#4A1414", "#2F5D8A", "#D9A441"
INK, MUTED, GRID = "#1F2328", "#6B7280", "#E5E7EB"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": INK, "text.color": INK})
ANA_AD = {"01": "Gıda ve alkolsüz içecekler", "02": "Alkollü içecekler ve tütün", "03": "Giyim ve ayakkabı",
          "04": "Konut, su, elektrik, gaz", "05": "Mobilya ve ev eşyası", "06": "Sağlık", "07": "Ulaştırma",
          "08": "Bilgi ve iletişim", "09": "Eğlence, spor ve kültür", "10": "Eğitim", "11": "Lokanta ve konaklama",
          "12": "Sigorta ve finansal hizmetler", "13": "Kişisel bakım ve çeşitli", "GENEL": "KTüfe"}


def hbar(series: pd.Series, title: str, subtitle: str, path, headline_key="GENEL", pos=C_MAIN):
    s = series.dropna().sort_values()
    fig, ax = plt.subplots(figsize=(9, 0.38 * len(s) + 1.4), dpi=160)
    colors = [C_HEAD if k == headline_key else (pos if v >= 0 else C_NEG) for k, v in s.items()]
    bars = ax.barh(range(len(s)), s.values, color=colors, height=0.62)
    ax.set_yticks(range(len(s))); ax.set_yticklabels([ANA_AD.get(k, k) for k in s.index])
    for lbl, k in zip(ax.get_yticklabels(), s.index):
        if k == headline_key: lbl.set_fontweight("bold")
    span = max(abs(s.min()), abs(s.max()), 0.1)
    for b, v in zip(bars, s.values):
        ax.text(v + (0.015 * span if v >= 0 else -0.015 * span), b.get_y() + b.get_height() / 2,
                f"{v:+.2f}%", va="center", ha="left" if v >= 0 else "right",
                fontsize=9.5, color=INK, fontweight="bold" if False else None)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.xaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
    ax.set_xlim(min(0, s.min()) - (0.18 * span if s.min() < 0 else 0), max(0, s.max()) + 0.25 * span)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold")
    ax.set_title(subtitle, loc="left", fontsize=9.5, color=MUTED)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight", facecolor="white"); plt.close(fig)


def group_changes(headline_daily: pd.DataFrame):
    """(haftalık %, aylık %) — sütunlar: GENEL + ana gruplar."""
    today = headline_daily.index[-1]; wk = today - pd.Timedelta(days=7)
    weekly = (headline_daily.iloc[-1] / headline_daily.asof(wk) - 1) * 100 if wk >= headline_daily.index[0] else None
    mon = {c: monthly_index(headline_daily[c]) for c in headline_daily.columns}
    monthly = pd.Series({c: (m.iloc[-1] / m.iloc[-2] - 1) * 100 if len(m) > 1 else np.nan for c, m in mon.items()})
    label = str(next(iter(mon.values())).index[-1])
    return weekly, monthly, label


def item_movers(item_idx: pd.DataFrame, names: dict, n=15):
    mon = {c: monthly_index(item_idx[c]) for c in item_idx.columns}
    ch = pd.Series({c: (m.iloc[-1] / m.iloc[-2] - 1) * 100 for c, m in mon.items() if len(m) > 1}).dropna()
    ch.index = [names.get(c, c) for c in ch.index]
    return pd.concat([ch.nlargest(n), ch.nsmallest(n)]).drop_duplicates()


def ktufe_vs_tuik(tr_monthly: pd.DataFrame, path):
    tuik = pd.read_csv(ROOT / "data/reference/tuik_anagrup_endeks_2025b100.csv", index_col=0)["GENEL"]
    tuik.index = pd.PeriodIndex(tuik.index, freq="M"); tuik = tuik.pct_change() * 100
    k = tr_monthly["aylik_%"].dropna()
    idx = k.index.union(tuik.index[-12:])[-12:]
    df = pd.DataFrame({"KTüfe": k.reindex(idx), "TÜİK": tuik.reindex(idx)})
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=160); x = np.arange(len(df)); wdt = 0.38
    for i, (col, c) in enumerate([("KTüfe", C_MAIN), ("TÜİK", C_TUIK)]):
        b = ax.bar(x + (i - 0.5) * wdt, df[col].fillna(0), wdt - 0.03, color=c, label=col)
        for xi, v in zip(x, df[col]):
            if pd.notna(v): ax.text(xi + (i - 0.5) * wdt, v + 0.05, f"{v:+.2f}", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(x); ax.set_xticklabels([p.strftime("%b %y") for p in idx], fontsize=8.5)
    ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%"); ax.legend(frameon=False, loc="upper left")
    fig.suptitle("Aylık değişim: KTüfe (Türkiye) ve TÜİK", x=0.01, ha="left", fontsize=13, fontweight="bold")
    ax.set_title("Son 12 ay, %  — TÜİK verisi EVDS'den; KTüfe ay-içi okuma", loc="left", fontsize=9.5, color=MUTED)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight", facecolor="white"); plt.close(fig)


def render_all(regions, item_names: dict) -> dict:
    """build_index.py'den çağrılır; üretilen dosya yollarını döner."""
    made = {}
    for rid, ad in [(r["id"], r.get("ad", r["id"])) for r in regions] + [("TR", "Türkiye")]:
        f = ROOT / f"data/index/{rid}_headline_daily.csv"
        if not f.exists(): continue
        hd = pd.read_csv(f, index_col=0, parse_dates=True)
        weekly, monthly, label = group_changes(hd)
        if weekly is not None:
            hbar(weekly, f"Ana gruplar: haftalık değişim — {ad}", f"Son 7 gün ({hd.index[-1]:%d.%m.%Y}), %",
                 OUT / f"{rid}_anagrup_haftalik.png"); made[f"{rid}_haftalik"] = f"charts/{rid}_anagrup_haftalik.png"
        if monthly.notna().any():
            hbar(monthly, f"Ana gruplar: aylık değişim — {ad}", f"{label} ay-içi (ilk 24 gün), %",
                 OUT / f"{rid}_anagrup_aylik.png"); made[f"{rid}_aylik"] = f"charts/{rid}_anagrup_aylik.png"
        fi = ROOT / f"data/index/{rid}_item_index.csv"
        if fi.exists() and rid != "TR":
            mv = item_movers(pd.read_csv(fi, index_col=0, parse_dates=True), item_names)
            if len(mv):
                hbar(mv, f"En çok / en az değişen maddeler — {ad}", f"{label}, aylık %", OUT / f"{rid}_maddeler_aylik.png",
                     headline_key=None); made[f"{rid}_maddeler"] = f"charts/{rid}_maddeler_aylik.png"
    trm = ROOT / "data/index/TR_monthly.csv"
    if trm.exists():
        ktufe_vs_tuik(pd.read_csv(trm, index_col=0).pipe(lambda d: d.set_index(pd.PeriodIndex(d.index, freq="M"))),
                      OUT / "TR_ktufe_vs_tuik.png"); made["tuik"] = "charts/TR_ktufe_vs_tuik.png"
    return made
