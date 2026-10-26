"""
Günlük fiyat toplayıcı iskeleti
===============================

Tasarım ilkeleri (webtufe'nin yaptığı işin sürdürülebilir hali):
  * Kaynak başına bir "adaptör": fetch(sku_cfg) -> fiyat (float) ya da None.
    Önce resmi/açık uç noktalar (JSON API, fiyat listesi), scraping son çare.
  * robots.txt kontrolü + istek başına bekleme + User-Agent kimliği.
    Engellenen/izin vermeyen site için adaptör None döner, sistem kırılmaz.
  * Her SKU bir COICOP madde koduna bağlıdır (sepet.yaml). Endeks motoru
    yalnızca (date, item, sku, price) görür; kaynak ayrıntısı ona sızmaz.
  * Ham çekimler data/raw/YYYY-MM-DD.parquet olarak saklanır; temizleme
    ayrı adımdır (yeniden işlenebilirlik = revizyon mekanizması).
  * Online verisi olmayan maddeler (kira, eğitim, sağlık hizmeti...) için
    'policy: carry_forward' ya da 'policy: manual' (aylık elle girilen fiyat).

Kullanım:
    python collector/collector.py --config collector/sepet_ornek.yaml --out data/raw
"""
from __future__ import annotations

import argparse, json, re, sys, time, datetime as dt, pathlib, urllib.robotparser, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

try:
    import requests
except ImportError:  # requests yoksa sadece manual/carry_forward çalışır
    requests = None

UA = "WebTUFE-Replica/0.1 (+kisisel arastirma; iletisim: sizin@mail)"


# --------------------------------------------------------------------------
# Nezaket katmanı
# --------------------------------------------------------------------------
class Politeness:
    def __init__(self, min_gap_s: float = 2.0):
        self.min_gap = min_gap_s
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        host = urllib.parse.urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.set_url(f"https://{host}/robots.txt"); rp.read()
            except Exception:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(UA, url)

    def wait(self, url: str):
        host = urllib.parse.urlparse(url).netloc
        gap = time.time() - self._last.get(host, 0)
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last[host] = time.time()


POLITE = Politeness()


# --------------------------------------------------------------------------
# Adaptörler: her biri sku_cfg (dict) alır, fiyat döner
# --------------------------------------------------------------------------
def adapter_json_api(cfg: dict) -> Optional[float]:
    """Resmi/açık JSON uç noktası. cfg: {url, json_path: 'a.b.0.price'}"""
    if requests is None or not POLITE.allowed(cfg["url"]):
        return None
    POLITE.wait(cfg["url"])
    r = requests.get(cfg["url"], headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    node = r.json()
    for key in cfg["json_path"].split("."):
        node = node[int(key)] if key.isdigit() else node[key]
    return float(node)


def adapter_html_regex(cfg: dict) -> Optional[float]:
    """Son çare: sayfa metninden regex ile fiyat. cfg: {url, pattern}"""
    if requests is None or not POLITE.allowed(cfg["url"]):
        return None
    POLITE.wait(cfg["url"])
    r = requests.get(cfg["url"], headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    m = re.search(cfg["pattern"], r.text)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def adapter_manual(cfg: dict) -> Optional[float]:
    """Elle girilen aylık fiyat tablosu. cfg: {file, key} -> en son geçerli fiyat."""
    tbl = pd.read_csv(cfg["file"], parse_dates=["gecerlilik"])
    tbl = tbl[tbl["key"] == cfg["key"]].sort_values("gecerlilik")
    tbl = tbl[tbl["gecerlilik"] <= pd.Timestamp.today()]
    return float(tbl["price"].iloc[-1]) if len(tbl) else None


ADAPTERS: dict[str, Callable[[dict], Optional[float]]] = {
    "json_api": adapter_json_api,
    "html_regex": adapter_html_regex,
    "manual": adapter_manual,
    "carry_forward": lambda cfg: None,   # motor önceki günü taşır
}
# Gerçek kaynak adaptörleri (marketfiyati, petrolofisi, evds, ibb_hal, playwright)
try:
    from adapters import ADAPTERS as _REAL
    ADAPTERS.update(_REAL)
except ImportError:
    pass


# --------------------------------------------------------------------------
# Çalıştırıcı
# --------------------------------------------------------------------------
@dataclass
class Observation:
    date: str
    region: str
    item: str
    sku: str
    price: Optional[float]
    source: str
    status: str
    note: str = ""


# Konuma duyarlı adaptörler: bölge başına ayrı çağrı yapılır. Diğerleri
# (EVDS, playwright, html_regex) tek çağrı -> her bölgeye aynı değer yazılır.
GEO_ADAPTERS = {"marketfiyati": lambda sku, r: {**sku, "lat": r["lat"], "lon": r["lon"]},
                "petrolofisi": lambda sku, r: {**sku, "il": r.get("po_il", sku.get("il"))},
                "ibb_hal": lambda sku, r: sku if r.get("hal") == "ibb" else None}


def run(config_path: str, out_dir: str, today: Optional[dt.date] = None) -> pd.DataFrame:
    import yaml
    cfg = yaml.safe_load(open(config_path, encoding="utf-8"))
    today = today or dt.date.today()
    regions = cfg.get("regions") or [{"id": "TR", "lat": 41.03, "lon": 28.98}]
    obs: list[Observation] = []
    for item in cfg["items"]:
        for sku in item.get("skus", []):
            fn = ADAPTERS[sku["adapter"]]
            geo = GEO_ADAPTERS.get(sku["adapter"])
            targets = [(r, geo(sku, r)) for r in regions] if geo else [(None, sku)]
            shared = None
            for r, s in targets:
                if s is None:          # bu bölgede bu kaynak yok (ör. Ankara'da İBB Hal)
                    continue
                note = ""
                try:
                    try:
                        from adapters import LAST_NOTE; LAST_NOTE["v"] = ""
                    except ImportError:
                        LAST_NOTE = {"v": ""}
                    p = fn(s)
                    status = "ok" if p else ("carry_forward" if sku["adapter"] == "carry_forward" else "missing")
                    note = LAST_NOTE["v"] if p is None else ""
                except Exception as e:  # tek SKU hatası günü bozmaz
                    p, status, note = None, f"error:{type(e).__name__}", str(e)[:200].replace("\n", " ")
                if r is None:          # konumsuz kaynak: tüm bölgelere kopyala
                    for rr in regions:
                        obs.append(Observation(str(today), rr["id"], item["coicop"], sku["id"], p,
                                               sku["adapter"], status, note))
                else:
                    obs.append(Observation(str(today), r["id"], item["coicop"], sku["id"], p,
                                           sku["adapter"], status, note))
    df = pd.DataFrame([o.__dict__ for o in obs])
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / f"{today}.csv", index=False)
    print(df["status"].value_counts().to_string())
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (varsayılan bugün)")
    a = ap.parse_args()
    run(a.config, a.out, dt.date.fromisoformat(a.date) if a.date else None)
