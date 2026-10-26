"""
Gerçek kaynak adaptörleri
=========================
Her adaptör: fetch(cfg: dict) -> float | None   (fiyat ya da endeks düzeyi)

Doğrulama durumu (26 Ekim 2026):
  marketfiyati   : API şeması açık kaynak istemciden (mtcnbzks/market-fiyati-mcp-server)
                   alındı; uç nokta POST https://api.marketfiyati.org.tr/api/v2/search.
                   Bu oturumda canlı çağrı yapılamadı (sandbox dış ağa kapalı) ->
                   ilk çalıştırmada `python collector/smoke_test.py` ile doğrulayın.
  petrolofisi    : 81 ilin fiyatı statik HTML tabloda; satır biçimi
                   "ISTANBUL (AVRUPA) | 76.30 63.59 TL/LT +KDV | ..." (ilk sayı KDV dahil).
  evds           : TCMB EVDS REST API (anahtar gerekir: evds2.tcmb.gov.tr'den ücretsiz).
                   TÜİK 5-basamak alt endeksleri (349 seri) -> online verisi olmayan
                   kalemler için en iyi carry-forward kaynağı.
  ibb_hal        : İBB Açık Veri CKAN datastore. resource_id portaldan alınmalı
                   (site botlara kapalı, elle bakın: data.ibb.gov.tr -> "hal fiyat").
  playwright     : JS ile render edilen sayfalar (Opet il tablosu, pazar yerleri).
  html_regex     : genel son çare.
Her adaptör robots.txt'ye uyar ve host başına >=2 sn bekler (Politeness).
"""
from __future__ import annotations
import os, re, json, statistics, urllib.parse, urllib.robotparser, time
from typing import Optional

import requests

UA = "WebTUFE-Replica/0.1 (akademik/kisisel arastirma; iletisim: EPOSTA_GIRIN)"
_last: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _polite(url: str, min_gap: float = 2.0) -> bool:
    host = urllib.parse.urlparse(url).netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(f"https://{host}/robots.txt"); rp.read()
            _robots[host] = rp
        except Exception:
            _robots[host] = None
    rp = _robots[host]
    if rp is not None and not rp.can_fetch(UA, url):
        return False
    gap = time.time() - _last.get(host, 0)
    if gap < min_gap:
        time.sleep(min_gap - gap)
    _last[host] = time.time()
    return True


def _tr_float(s: str) -> float:
    s = s.strip().replace("TL", "").replace("₺", "").strip()
    if "," in s:                       # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    return float(s)


# ---------------------------------------------------------------- marketfiyati
MF_URL = "https://api.marketfiyati.org.tr/api/v2/search"
MF_ID_URL = "https://api.marketfiyati.org.tr/api/v2/searchByIdentity"

def marketfiyati(cfg: dict) -> Optional[float]:
    """
    cfg:
      keywords     : arama metni (ör. "Uno Tam Buğday Ekmeği 350 g")
      product_id   : (tercih) sabit ürün kimliği -> searchByIdentity; SKU sabitliği için şart
      market       : (ops.) tek zincir adı filtresi (ör. "Migros"); yoksa tüm zincirler
      agg          : "median" (varsayılan) | "min" | "mean"  -> depolar arası toplulaştırma
      lat, lon, distance : konum (varsayılan İstanbul merkez, 15 km)
    Döner: seçilen ürünün o günkü fiyatı (TL).
    Not: aynı maddeye 3-6 farklı product_id koyun; Jevons ortalaması tek ürünün
    kampanya gürültüsünü sönümler.
    """
    if not _polite(MF_URL):
        return None
    body = {"latitude": cfg.get("lat", 41.03), "longitude": cfg.get("lon", 28.98),
            "distance": cfg.get("distance", 15000), "keywords": cfg.get("keywords", "")}
    if cfg.get("product_id"):
        url = MF_ID_URL
        body.update({"identity": cfg["product_id"], "identityType": "id"})
    else:
        url = MF_URL
    r = requests.post(url, json=body, timeout=15,
                      headers={"User-Agent": UA, "content-type": "application/json"})
    r.raise_for_status()
    content = r.json().get("content") or []
    if not content:
        return None
    prod = content[0]
    depots = prod.get("productDepotInfoList") or []
    if cfg.get("market"):
        depots = [d for d in depots if cfg["market"].lower() in d["marketAdi"].lower()]
    prices = [float(d["price"]) for d in depots if d.get("price")]
    if not prices:
        return None
    agg = cfg.get("agg", "median")
    return {"median": statistics.median, "min": min, "mean": statistics.fmean}[agg](prices)


# ----------------------------------------------------------------- akaryakıt
PO_URL = "https://www.petrolofisi.com.tr/akaryakit-fiyatlari"

def petrolofisi(cfg: dict) -> Optional[float]:
    """
    cfg: il = "ISTANBUL (AVRUPA)", urun = "benzin" | "motorin" | "lpg"
    81 il tek sayfada statik HTML tablo. KDV dahil (ilk) fiyat alınır.
    """
    if not _polite(PO_URL):
        return None
    html = requests.get(PO_URL, headers={"User-Agent": UA}, timeout=20).text
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = re.search(re.escape(cfg["il"]) + r"(.{0,300})", text, re.I)
    if not m:
        return None
    nums = re.findall(r"(\d{2,3}[.,]\d{2})\s*\d{2,3}[.,]\d{2}\s*TL/(?:LT|KG)", m.group(1))
    order = {"benzin": 0, "motorin": 1, "lpg": 2}
    try:
        return _tr_float(nums[order[cfg["urun"]]])
    except (IndexError, KeyError):
        return None


# ------------------------------------------------------------------- EVDS
def evds(cfg: dict) -> Optional[float]:
    """
    TÜİK alt endeksini TCMB EVDS'den çeker (aylık; günlere taşınır).
    cfg: series = "TP.TUKFIY2025.04110" (gerçek kira) vb.
    Anahtar: ortam değişkeni EVDS_API_KEY.
    """
    key = os.environ.get("EVDS_API_KEY")
    if not key:
        return None
    url = ("https://evds2.tcmb.gov.tr/service/evds/series=" + cfg["series"] +
           "&startDate=01-01-2024&endDate=31-12-2030&type=json")
    r = requests.get(url, headers={"key": key, "User-Agent": UA}, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])
    col = cfg["series"].replace(".", "_")
    vals = [float(it[col]) for it in items if it.get(col) not in (None, "")]
    return vals[-1] if vals else None


# ----------------------------------------------------------------- İBB Hal
IBB_DS = "https://data.ibb.gov.tr/api/3/action/datastore_search"

def ibb_hal(cfg: dict) -> Optional[float]:
    """
    cfg: resource_id (CKAN kaynak kimliği), urun = "DOMATES", alan = "ORTALAMA_UCRET"
    Günlük toptan ortalama fiyat; perakende marjı sabit varsayılır (relatif önemli).
    """
    if not _polite(IBB_DS):
        return None
    r = requests.get(IBB_DS, params={"resource_id": cfg["resource_id"],
                                     "q": cfg["urun"], "limit": 50, "sort": "_id desc"},
                     headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    recs = r.json()["result"]["records"]
    recs = [x for x in recs if cfg["urun"].lower() in str(x.get("MAL_ADI", x.get("URUN", ""))).lower()]
    if not recs:
        return None
    return float(str(recs[0][cfg.get("alan", "ORTALAMA_UCRET")]).replace(",", "."))


# -------------------------------------------------------------- Playwright
def playwright_text(cfg: dict) -> Optional[float]:
    """
    JS-render gerektiren sayfalar. cfg: url, pattern (regex, grup 1 fiyat), wait_ms
    pip install playwright && playwright install chromium
    """
    if not _polite(cfg["url"]):
        return None
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.goto(cfg["url"], timeout=30000)
        pg.wait_for_timeout(cfg.get("wait_ms", 2500))
        txt = pg.inner_text("body")
        b.close()
    m = re.search(cfg["pattern"], txt, re.S)
    return _tr_float(m.group(1)) if m else None


def html_regex(cfg: dict) -> Optional[float]:
    if not _polite(cfg["url"]):
        return None
    r = requests.get(cfg["url"], headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    m = re.search(cfg["pattern"], r.text, re.S)
    return _tr_float(m.group(1)) if m else None


ADAPTERS = {
    "marketfiyati": marketfiyati,
    "petrolofisi": petrolofisi,
    "evds": evds,
    "ibb_hal": ibb_hal,
    "playwright": playwright_text,
    "html_regex": html_regex,
    "carry_forward": lambda cfg: None,
}
