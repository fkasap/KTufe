"""
Doğrulama: TÜİK'in 13 ana grup endeksi + yıllık ana grup ağırlıklarıyla
manşet TÜFE'yi motorla yeniden üret, TÜİK Genel Endeks ile karşılaştır.

Beklenti: fark yalnızca yuvarlamadan (endeksler 2 ondalık, ağırlıklar 2
ondalık) kaynaklanmalı -> aylık enflasyonda |hata| < ~0.05 puan.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pandas as pd
import numpy as np
from index_engine import chained_laspeyres, inflation_table, contributions

root = pathlib.Path(__file__).resolve().parents[1]
idx = pd.read_csv(root / "data/reference/tuik_anagrup_endeks_2025b100.csv", index_col=0)
w = pd.read_csv(root / "data/reference/tuik_anagrup_agirlik.csv", index_col=0)

idx.index = pd.PeriodIndex(idx.index, freq="M").to_timestamp(how="end").normalize()
groups = [c for c in idx.columns if c != "GENEL"]
item_idx = idx[groups]
weights = {int(y): w.loc[y, groups] for y in w.index if int(y) >= 2024}

rebuilt = chained_laspeyres(item_idx, weights, base_value=idx["GENEL"].iloc[0])

cmp = pd.DataFrame({"TUIK_genel": idx["GENEL"], "motor": rebuilt})
cmp["fark_endeks"] = cmp["motor"] - cmp["TUIK_genel"]
cmp["TUIK_aylik_%"] = (cmp["TUIK_genel"].pct_change() * 100).round(2)
cmp["motor_aylik_%"] = (cmp["motor"].pct_change() * 100).round(2)
cmp["fark_aylik_puan"] = (cmp["motor_aylik_%"] - cmp["TUIK_aylik_%"]).round(2)

pd.set_option("display.width", 160)
print(cmp.round(3).to_string())
print("\nMutlak aylık hata: ort %.3f, maks %.3f puan" %
      (cmp["fark_aylik_puan"].abs().mean(), cmp["fark_aylik_puan"].abs().max()))

# Yıllık enflasyon karşılaştırması
yoy_t = (idx["GENEL"] / idx["GENEL"].shift(12) - 1) * 100
yoy_m = (rebuilt / rebuilt.shift(12) - 1) * 100
print("\nEylül 2026 yıllık: TÜİK %.2f  motor %.2f" % (yoy_t.iloc[-1], yoy_m.iloc[-1]))

# Katkı analizi: Eylül 2026 aylık değişime ana grup katkıları
t1 = item_idx.index[-1]; t0 = item_idx.index[-2]
print("\nEylül 2026 aylık enflasyona ana grup katkıları (puan):")
print(contributions(item_idx, w.loc[2026, groups], t0, t1).round(2).to_string())

cmp.round(3).to_csv(root / "reports/dogrulama_tuik.csv")
