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
import os, re, json, statistics, urllib.parse, urllib.robotparser, time, datetime as dt
from typing import Optional

import requests

LAST_NOTE: dict = {"v": ""}

def _note(msg: str):
    LAST_NOTE["v"] = str(msg)[:220].replace("\n", " ")


def _clean(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


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
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[1]) == 3):
        s = s.replace(".", "")         # 1.965.000 / 39.999 -> binlik ayracı
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
    # İl adı sayfada tablodan önce (il seçim listesinde) de geçer; bu yüzden
    # il adını fiyat hücresi izleyen ilk eşleşmeyi alıyoruz.
    cell = r"(\d{2,3}[.,]\d{2})\s*\d{2,3}[.,]\d{2}\s*TL/(?:LT|KG)\s*\+?KDV"
    m = re.search(re.escape(cfg["il"]) + r"\s*" + r"\s*".join([cell] * 6), text, re.I)
    if not m:
        return None
    # Sütun sırası: 95 | Diesel | Gazyağı | Kalorifer | Fuel Oil | Otogaz
    order = {"benzin": 1, "motorin": 2, "gazyagi": 3, "lpg": 6}
    try:
        return _tr_float(m.group(order[cfg["urun"]]))
    except (IndexError, KeyError):
        return None


# ------------------------------------------------------------------- EVDS
def evds(cfg: dict) -> Optional[float]:
    """
    TÜİK alt endeksini TCMB EVDS'den çeker (aylık; günlere taşınır).
    cfg: series = "TP.TUKFIY2025.04110" (gerçek kira) vb.
    Anahtar: ortam değişkeni EVDS_API_KEY.
    """
    key = os.environ.get("EVDS_API_KEY", "").strip()
    if not key:
        return None
    col = cfg["series"].replace(".", "_")
    if col in _EVDS_CACHE:
        return _EVDS_CACHE[col]
    if _EVDS_DOWN.get("down"):          # bu çalıştırmada EVDS yanıt vermiyor: 25 kez bekleme
        return None
    start = (dt.date.today() - dt.timedelta(days=200)).strftime("%d-%m-%Y")
    end = dt.date.today().strftime("%d-%m-%Y")
    path = f"/service/evds/series={cfg['series']}&startDate={start}&endDate={end}&type=json"
    last_err = None
    for host in ("https://evds2.tcmb.gov.tr", "https://evds3.tcmb.gov.tr"):
        try:
            r = requests.get(host + path, headers={"key": key, "User-Agent": UA}, timeout=12)
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or "json" not in ctype:
                # Tanı: EVDS hata sayfalarını HTML döndürür (yanlış anahtar, IP engeli,
                # host değişikliği). İlk 160 karakteri logla, anahtarı asla loglama.
                print(f"[evds] {host} HTTP {r.status_code} {ctype} :: {r.text[:160]!r}")
                last_err = f"HTTP {r.status_code}"
                continue
            items = r.json().get("items", [])
            vals = [float(it[col]) for it in items if it.get(col) not in (None, "")]
            _EVDS_CACHE[col] = vals[-1] if vals else None
            return _EVDS_CACHE[col]
        except Exception as e:
            print(f"[evds] {host} {type(e).__name__}: {e}")
            last_err = e
    _EVDS_DOWN["down"] = True
    print("[evds] iki host da başarısız; bu çalıştırmada kalan EVDS kalemleri atlanıyor")
    return None


_EVDS_CACHE: dict[str, Optional[float]] = {}
_EVDS_DOWN: dict[str, bool] = {}


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
    Gerçek tarayıcı (Chromium) ile sayfa; pattern önce görünür metinde, sonra ham
    HTML'de (meta og:title vb.) aranır. cfg: url, pattern, wait_ms (vars. 5000)
    LCW gibi WAF arkasındaki siteler düz HTTP istemcisine 403 verir; Playwright
    normal tarayıcı gibi davranır, robots.txt'ye uyum _polite ile korunur.
    """
    if not _polite(cfg["url"]):
        _note("robots disallow"); return None
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(locale="tr-TR", viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()
        try:
            pg.goto(cfg["url"], timeout=45000, wait_until="domcontentloaded")
            pg.wait_for_timeout(cfg.get("wait_ms", 5000))
            txt = pg.inner_text("body")
            html = pg.content()
            title = pg.title()
        finally:
            b.close()
    for hay in (txt, html):
        m = re.search(cfg["pattern"], hay, re.S)
        if m:
            return _tr_float(m.group(1))
    _note(f"nomatch title={title[:50]} textlen={len(txt)} :: {txt[:100]}")
    return None


def html_regex(cfg: dict) -> Optional[float]:
    if not _polite(cfg["url"]):
        _note("robots disallow"); return None
    r = requests.get(cfg["url"], headers={"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}, timeout=25)
    if r.status_code != 200:
        _note(f"HTTP {r.status_code} len={len(r.text)}"); return None
    if "charset" not in r.headers.get("content-type", "").lower():
        r.encoding = r.apparent_encoding or "utf-8"      # Togg: charset başlığı yok -> mojibake
    text = _clean(r.text)
    nth = int(cfg.get("nth_distinct", 1))              # Apple: n. farklı tutar (256 GB=1, 512 GB=2)
    for hay in (text, r.text):
        if nth > 1:
            seen = []
            for m in re.finditer(cfg["pattern"], hay, re.S):
                if m.group(1) not in seen:
                    seen.append(m.group(1))
                if len(seen) == nth:
                    return _tr_float(seen[-1])
            continue
        m = re.search(cfg["pattern"], hay, re.S)
        if m:
            return _tr_float(m.group(1))
    title = re.search(r"<title>(.*?)</title>", r.text, re.S | re.I)
    _note(f"nomatch len={len(r.text)} title={title.group(1).strip()[:50] if title else '-'} :: {text[:90]}")
    return None


# ------------------------------------------------------------ EVDS (dosya)
_EVDS_FILE = None
def evds_file(cfg: dict) -> Optional[float]:
    """
    TÜİK alt endeksini data/reference/evds_alt_endeksler.csv'den okur (EVDS yurt dışı
    runner IP'sine HTML doğrulama sayfası döndürdüğü için aylık tazelenen anlık görüntü).
    cfg: series = "TP.TUKFIY2025.04110". Son satır = TÜİK'in son açıkladığı ay.
    """
    global _EVDS_FILE
    import pandas as pd, pathlib
    if _EVDS_FILE is None:
        f = pathlib.Path(__file__).resolve().parents[1] / "data/reference/evds_alt_endeksler.csv"
        _EVDS_FILE = pd.read_csv(f, index_col=0) if f.exists() else pd.DataFrame()
    col = cfg["series"]
    if col not in _EVDS_FILE.columns:
        _note("seri dosyada yok"); return None
    v = _EVDS_FILE[col].dropna()
    return float(v.iloc[-1]) if len(v) else None


ADAPTERS = {
    "evds_file": evds_file,
    "marketfiyati": marketfiyati,
    "petrolofisi": petrolofisi,
    "evds": evds,
    "ibb_hal": ibb_hal,
    "playwright": playwright_text,
    "html_regex": html_regex,
    "carry_forward": lambda cfg: None,
}
