"""
data/raw/*.csv  ->  bölge bazında madde endeksi -> manşet -> Türkiye birleşimi -> rapor

Bölgeler (collector/sepet.yaml `regions`): istanbul, ankara, ...  "TR" = bölgelerin
pay_tr ile ağırlıklı geometrik birleşimi (şehir eklendikçe paylar güncellenir).

Ağırlıklar: TÜİK 2026 sepetinden (data/reference/madde_agirlik_2026_turetilmis.csv).
sepet.yaml'daki coicop kodu TÜİK koduyla eşleşirse (5 ya da 7 basamak) o ağırlık;
eşleşmezse yaml'daki `agirlik` yedek olarak kullanılır.

Çıktılar:
  data/index/<bolge>_item_index.csv, <bolge>_headline_daily.csv, <bolge>_monthly.csv
  data/index/TR_headline_daily.csv, TR_monthly.csv
  reports/latest.md
"""
import sys, pathlib, glob
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import numpy as np, pandas as pd, yaml
from index_engine import (jevons_item_index, chained_laspeyres, monthly_index,
                          inflation_table, contributions)

# ---------------------------------------------------------------- girdi
files = sorted(glob.glob(str(ROOT / "data/raw/*.csv")))
if not files:
    sys.exit("data/raw boş — önce collector çalışmalı")
raw = pd.concat([pd.read_csv(f, dtype={"item": str, "sku": str, "region": str}) for f in files], ignore_index=True)
if "region" not in raw.columns:            # eski format (bölgesiz) -> istanbul say
    raw["region"] = "istanbul"
raw = raw[raw["status"] == "ok"].dropna(subset=["price"])
raw["date"] = pd.to_datetime(raw["date"])

cfg = yaml.safe_load(open(ROOT / "collector/sepet.yaml", encoding="utf-8"))
regions = cfg.get("regions") or [{"id": "istanbul", "pay_tr": 1.0}]

# ---------------------------------------------------------------- ağırlıklar
tuik = pd.read_csv(ROOT / "data/reference/tuik_sepet_agirlik_2026.csv", dtype={"kod": str})
tuik_w = tuik.dropna(subset=["agirlik"]).set_index("kod")["agirlik"]      # düzey 2-5
madde = pd.read_csv(ROOT / "data/reference/madde_agirlik_2026_turetilmis.csv", dtype={"kod": str})
madde_w = madde.set_index("kod")["agirlik_esit_pay"]                       # düzey 7

def weight_for(item):
    kod = str(item["coicop"]).replace(".", "")
    if kod in madde_w.index:  return float(madde_w[kod]), "tuik_madde(esit_pay)"
    if kod in tuik_w.index:   return float(tuik_w[kod]),  "tuik_duzey%d" % len(kod)
    return float(item["agirlik"]), "yaml_yaklasik"

w_rows = [(it["coicop"], it["anagrup"], *weight_for(it), bool(it.get("artik"))) for it in cfg["items"]]
W = pd.DataFrame(w_rows, columns=["coicop", "anagrup", "agirlik", "kaynak", "artik"]).set_index("coicop")
# "Artık" kalem: ana grubun TÜİK ağırlığı - sepetteki alt sınıfların toplamı.
# Böylece 13 ana grubun ağırlığı TÜİK ile birebir, toplam = 100.
for g in W["anagrup"].unique():
    m = (W["anagrup"] == g)
    if W.loc[m, "artik"].any():
        rest = float(tuik_w[g]) - W.loc[m & ~W["artik"], "agirlik"].sum()
        if rest < 0:   # sepet alt sınıfları ana grubu aşıyorsa (kod örtüşmesi) orantılı ölçekle
            W.loc[m & ~W["artik"], "agirlik"] *= float(tuik_w[g]) / W.loc[m & ~W["artik"], "agirlik"].sum()
            rest = 0.0
        W.loc[m & W["artik"], "agirlik"] = rest
        W.loc[m & W["artik"], "kaynak"] = "tuik_anagrup_artik"
    elif abs(W.loc[m, "agirlik"].sum() - float(tuik_w[g])) > 1e-6:
        # artık kalemi olmayan grup: toplamı TÜİK ana grup ağırlığına ölçekle
        W.loc[m, "agirlik"] *= float(tuik_w[g]) / W.loc[m, "agirlik"].sum()
w = W["agirlik"]; ana = W["anagrup"]
ANA_AD = {"01": "Gıda ve alkolsüz içecekler", "02": "Alkollü içecekler ve tütün", "03": "Giyim ve ayakkabı",
          "04": "Konut, su, elektrik, gaz", "05": "Mobilya ve ev eşyası", "06": "Sağlık", "07": "Ulaştırma",
          "08": "Bilgi ve iletişim", "09": "Eğlence, spor ve kültür", "10": "Eğitim", "11": "Lokanta ve konaklama",
          "12": "Sigorta ve finansal hizmetler", "13": "Kişisel bakım ve çeşitli"}

# ---------------------------------------------------------------- bölge döngüsü
out = ROOT / "data/index"; out.mkdir(parents=True, exist_ok=True)
headlines, monthlies, item_by_region = {}, {}, {}
for r in regions:
    rid = r["id"]
    sub = raw[raw["region"] == rid]
    if sub.empty:
        continue
    item_idx = jevons_item_index(sub, min_obs=1)
    item_idx.columns = item_idx.columns.astype(str)
    years = sorted(set(item_idx.index.year))
    hl = chained_laspeyres(item_idx, {y: w for y in years})
    grp = {}
    for g in sorted(ana.unique()):
        cols = ana[ana == g].index.intersection(item_idx.columns)
        if len(cols):
            grp[g] = chained_laspeyres(item_idx[cols], {y: w[cols] for y in years})
    item_idx.round(4).to_csv(out / f"{rid}_item_index.csv")
    pd.concat([hl.rename("GENEL"), pd.DataFrame(grp)], axis=1).round(4).to_csv(out / f"{rid}_headline_daily.csv")
    mon = inflation_table(monthly_index(hl)); mon.round(3).to_csv(out / f"{rid}_monthly.csv")
    headlines[rid], monthlies[rid], item_by_region[rid] = hl, mon, item_idx

# ---------------------------------------------------------------- Türkiye birleşimi
# Bölge endekslerinin pay_tr ile ağırlıklı geometrik ortalaması (log-lineer birleşim;
# TÜİK'in bölge->Türkiye toplulaştırmasına yakın, yeni bölge eklenince kırılmaz).
pays = {r["id"]: float(r.get("pay_tr", 0)) for r in regions if r["id"] in headlines}
tot = sum(pays.values()) or 1.0
tr = sum(np.log(headlines[k]) * (v / tot) for k, v in pays.items())
tr = np.exp(tr).rename("GENEL")
tr.round(4).to_csv(out / "TR_headline_daily.csv")
tr_mon = inflation_table(monthly_index(tr)); tr_mon.round(3).to_csv(out / "TR_monthly.csv")
headlines["TR"], monthlies["TR"] = tr, tr_mon

# ---------------------------------------------------------------- rapor
today = tr.index[-1]
week_ago = today - pd.Timedelta(days=7)
def wk(h): return (h.iloc[-1] / h.asof(week_ago) - 1) * 100 if week_ago >= h.index[0] else np.nan
def fmt(x, s="%"): return f"{x:+.2f}{s}" if pd.notna(x) else "—"

rows = []
for rid in [r["id"] for r in regions if r["id"] in headlines] + ["TR"]:
    m = monthlies[rid]
    ad = next((r.get("ad", rid) for r in regions if r["id"] == rid), "Türkiye (birleşik)")
    rows.append((ad, fmt(wk(headlines[rid])), fmt(m["aylik_%"].iloc[-1]),
                 fmt(m["yillik_%"].iloc[-1]) if pd.notna(m["yillik_%"].iloc[-1]) else "12 ay dolmadı"))
tbl = pd.DataFrame(rows, columns=["Bölge", "Son 7 gün", f"{monthlies['TR'].index[-1]} ay-içi", "Yıllık"])

first = next(iter(item_by_region))
contrib = contributions(item_by_region[first], w, headlines[first].index[max(0, len(headlines[first]) - 8)], today).head(8)
kapsam = raw[raw["date"] == today].groupby("region")["sku"].nunique().to_dict()

lines = [
    f"# KTüfe haftalık özet — {today:%d.%m.%Y}", "",
    tbl.to_markdown(index=False), "",
    f"- Kapsam (bugün fiyatlanan SKU): {kapsam}",
    f"- Ağırlık kaynağı: {W['kaynak'].value_counts().to_dict()}",
    f"- Türkiye birleşimi payları: {pays}", "",
    f"## {regions[0].get('ad', first)} — son 7 güne en büyük katkılar (puan)", "",
    contrib.round(2).to_markdown(), "",
    "_Yöntem: SKU→madde Jevons, madde→manşet zincirleme Laspeyres (TÜİK 2026 ağırlıkları;",
    "madde ağırlığı = alt sınıf ağırlığının eşit payı), aylık okuma = ayın ilk 24 gününün",
    "geometrik ortalaması. Doğrulama kıyası: TÜİK bölgesel TÜFE (İstanbul TR10, Ankara TR51)._",
]
# ---------------------------------------------------------------- grafikler
sys.path.insert(0, str(ROOT / "scripts"))
from charts import render_all
names = {it["coicop"]: it["ad"] for it in cfg["items"]}
charts = render_all(regions, names)
lines += ["", "## Grafikler", ""]
if "tuik" in charts: lines += [f"![KTüfe vs TÜİK]({charts['tuik']})", ""]
for rid, ad in [(r["id"], r.get("ad", r["id"])) for r in regions] + [("TR", "Türkiye")]:
    sec = [f"![{ad} haftalık]({charts[k]})" for k in (f"{rid}_haftalik",) if k in charts]
    sec += [f"![{ad} aylık]({charts[k]})" for k in (f"{rid}_aylik",) if k in charts]
    sec += [f"![{ad} maddeler]({charts[k]})" for k in (f"{rid}_maddeler",) if k in charts]
    if sec: lines += [f"### {ad}", ""] + sec + [""]

(ROOT / "reports/latest.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
