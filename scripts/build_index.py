"""
data/raw/*.csv  ->  madde endeksi -> manşet (zincirleme Laspeyres) -> aylık/haftalık rapor

Çıktılar:
  data/index/item_index.csv      günlük madde endeksleri
  data/index/headline_daily.csv  günlük manşet
  data/index/monthly.csv         ilk-24-gün aylık endeks, aylık %, yıllık %
  reports/latest.md              haftalık özet (README'ye de gömülür)

Veri henüz azken (ilk 2-3 hafta) yıllık % NaN olur; bu normaldir.
"""
import sys, pathlib, glob, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import numpy as np, pandas as pd, yaml
from index_engine import (jevons_item_index, chained_laspeyres, monthly_index,
                          inflation_table, contributions)

# ---- ham veriyi oku
files = sorted(glob.glob(str(ROOT / "data/raw/*.csv")))
if not files:
    sys.exit("data/raw boş — önce collector çalışmalı")
raw = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
raw = raw[raw["status"] == "ok"].dropna(subset=["price"])
raw["date"] = pd.to_datetime(raw["date"])

# EVDS kaynaklı kalemler aylık endekstir: değer, ay içinde sabit kalır.
# Kayıt zaten günlük tekrar edildiği için Jevons relative'i 0 -> doğru davranış.

# ---- sepet ağırlıkları
cfg = yaml.safe_load(open(ROOT / "collector/sepet.yaml", encoding="utf-8"))
w = pd.Series({it["coicop"]: float(it["agirlik"]) for it in cfg["items"]})
ana = pd.Series({it["coicop"]: it["anagrup"] for it in cfg["items"]})

# ---- endeks
item_idx = jevons_item_index(raw.rename(columns={"item": "item"}), min_obs=1)
years = sorted(set(item_idx.index.year))
headline = chained_laspeyres(item_idx, {y: w for y in years})
mon = inflation_table(monthly_index(headline))

# ---- ana grup endeksleri
grp = {}
for g in sorted(ana.unique()):
    cols = ana[ana == g].index.intersection(item_idx.columns)
    if len(cols):
        grp[g] = chained_laspeyres(item_idx[cols], {y: w[cols] for y in years})
grp = pd.DataFrame(grp)

# ---- yaz
out = ROOT / "data/index"; out.mkdir(parents=True, exist_ok=True)
item_idx.round(4).to_csv(out / "item_index.csv")
pd.concat([headline.rename("GENEL"), grp], axis=1).round(4).to_csv(out / "headline_daily.csv")
mon.round(3).to_csv(out / "monthly.csv")

# ---- haftalık rapor
today = item_idx.index[-1]
week_ago = today - pd.Timedelta(days=7)
wk = (headline.iloc[-1] / headline.asof(week_ago) - 1) * 100 if week_ago >= headline.index[0] else np.nan
cur_m = mon.index[-1]
mtd = mon["aylik_%"].iloc[-1]
kapsam = raw[raw["date"] == today]["item"].nunique()
contrib = contributions(item_idx, w, headline.index[max(0, len(headline) - 8)], today).head(8)

lines = [
    f"# KTüfe haftalık özet — {today:%d.%m.%Y}",
    "",
    f"- **Son 7 gün manşet değişimi:** {wk:+.2f}%" if pd.notna(wk) else "- Son 7 gün: yetersiz veri",
    f"- **{cur_m} ay-içi (ilk 24 gün geo. ort., önceki aya göre):** {mtd:+.2f}%" if pd.notna(mtd) else f"- {cur_m}: önceki ay verisi yok",
    f"- **Yıllık:** {mon['yillik_%'].iloc[-1]:.2f}%" if pd.notna(mon["yillik_%"].iloc[-1]) else "- Yıllık: 12 ay dolmadı",
    f"- Kapsam: bugün {kapsam} madde / {raw[raw['date']==today]['sku'].nunique()} SKU fiyatlandı",
    "",
    "## Son 7 güne en büyük katkılar (puan)",
    "",
    contrib.round(2).to_markdown(),
    "",
    "_Yöntem: SKU→madde Jevons, madde→manşet zincirleme Laspeyres (TÜİK ağırlıkları),",
    "aylık okuma = ayın ilk 24 gününün geometrik ortalaması (Web TÜFE kuralı)._",
]
(ROOT / "reports/latest.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
