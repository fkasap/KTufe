"""
TÜİK ana grup endeks + ağırlıklarını EVDS'den tazele (haftalık iş, EVDS_API_KEY varsa).
Başarısız olursa mevcut referans dosyalarına dokunmaz.
"""
import os, sys, pathlib, requests, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]
key = os.environ.get("EVDS_API_KEY", "").strip()
if not key:
    sys.exit(0)
G = ["GENEL"] + [f"{i:02d}" for i in range(1, 14)]
UA = "KTufe/0.1 (github.com/fkasap/KTufe)"

def pull(prefix, start, end):
    series = "-".join(f"TP.{prefix}.{g}" for g in G)
    url = f"https://evds2.tcmb.gov.tr/service/evds/series={series}&startDate={start}&endDate={end}&type=json"
    r = requests.get(url, headers={"key": key, "User-Agent": UA}, timeout=30)
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        print(f"[refresh_tuik] {prefix}: HTTP {r.status_code} :: {r.text[:120]!r}"); return None
    df = pd.DataFrame(r.json()["items"])
    df = df.rename(columns={f"TP_{prefix}_{g}": g for g in G})[["Tarih"] + G]
    return df

try:
    e = pull("TUKFIY2025", "01-12-2023", "31-12-2030")
    if e is not None:
        e["tarih"] = pd.to_datetime(e["Tarih"], format="%Y-%m").dt.strftime("%Y-%m")
        e = e.set_index("tarih")[G].apply(pd.to_numeric, errors="coerce").dropna(how="all")
        e.to_csv(ROOT / "data/reference/tuik_anagrup_endeks_2025b100.csv"); print("endeks güncellendi:", e.index[-1])
    a = pull("TUKFIYAGRLK", "01-01-2023", "31-12-2030")
    if a is not None:
        a["yil"] = pd.to_numeric(a["Tarih"], errors="coerce"); a = a.dropna(subset=["yil"])
        a = a.set_index(a["yil"].astype(int))[G].apply(pd.to_numeric, errors="coerce")
        a.to_csv(ROOT / "data/reference/tuik_anagrup_agirlik.csv"); print("ağırlık güncellendi:", a.index[-1])
except Exception as ex:
    print("[refresh_tuik] atlandı:", type(ex).__name__, ex)
