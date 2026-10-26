"""Üçüncü sonda: Boyner kategori/ürün keşfi + Hal Kayıt Sistemi fiyat sayfası -> reports/probe_deep_<tarih>.json"""
import re, json, time, datetime as dt, requests, pathlib, urllib.parse
UA = "KTufe-Probe/0.1 (akademik enflasyon olcumu; github.com/fkasap/KTufe)"
H = {"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}
PRICE = r"\d{1,3}(?:\.\d{3})*,\d{2}\s*(?:TL|₺)|\d{1,3}(?:\.\d{3})+\s*(?:TL|₺)"
def get(u):
    r = requests.get(u, headers=H, timeout=(10, 20))
    if "charset" not in r.headers.get("content-type","").lower(): r.encoding = r.apparent_encoding or "utf-8"
    return r
out = {}
# --- Boyner: ana sayfadaki kategori linkleri (metin + href), giyim/ayakkabı olanlar
try:
    b = get("https://www.boyner.com.tr/").text
    cats = re.findall(r'<a[^>]+href="(/[^"]*-c-\d+[^"]*)"[^>]*>(.*?)</a>', b, re.S)
    seen = {}
    for href, txt in cats:
        t = re.sub(r"<[^>]+>|\s+", " ", txt).strip()[:40]
        if href not in seen and re.search(r"jean|pantolon|ti[sş]ört|g[öo]mlek|mont|kaban|kazak|triko|elbise|ayakkab|bot|sneaker|i[çc] giyim|[çc]ocuk|bebek", href+t, re.I):
            seen[href] = t
    out["boyner_cats"] = dict(list(seen.items())[:60])
    # sitemap da dene
    sm = get("https://www.boyner.com.tr/sitemap.xml"); out["boyner_sitemap_status"] = sm.status_code
    out["boyner_sitemap_sample"] = re.findall(r"<loc>([^<]+)</loc>", sm.text)[:15]
except Exception as e:
    out["boyner_err"] = repr(e)[:200]
# --- Boyner: bulunan ilk 4 giyim kategorisinden 3'er ürün + JSON-LD fiyat
out["boyner_products"] = []
for href in list(out.get("boyner_cats", {}))[:3]:
    try:
        time.sleep(1); c = get("https://www.boyner.com.tr" + href).text
        links = []
        for m in re.finditer(r'href="(/[^"]+-p-\d+)"', c):
            if m.group(1) not in links: links.append(m.group(1))
            if len(links) >= 3: break
        rec = {"cat": href, "status": "ok", "links": links, "prods": []}
        for l in links[:2]:
            time.sleep(1); p = get("https://www.boyner.com.tr" + l).text
            og = re.search(r'property="og:title"\s+content="([^"]{0,120})"', p)
            ld = re.findall(r'"price"\s*:\s*"?([\d.]+)', p)[:3]
            rec["prods"].append({"url": l, "og": og.group(1) if og else "", "ld_prices": ld})
        out["boyner_products"].append(rec)
        json.dump(out, open(f"reports/probe_deep_{dt.date.today()}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        out["boyner_products"].append({"cat": href, "err": repr(e)[:120]})
# --- Hal Kayıt Sistemi
for host in ["https://hal.gov.tr/", "https://www.hal.gov.tr/", "https://hal.ticaret.gov.tr/"]:
    try:
        r = get(host); txt = r.text
        links = re.findall(r'href="([^"]*)"[^>]*>([^<]{0,60}(?:[Ff]iyat|[Bb]ülten|[Rr]apor)[^<]{0,40})<', txt)
        out[f"hal {host}"] = {"status": r.status_code, "len": len(txt), "prices": re.findall(PRICE, txt)[:6],
                              "title": (re.search(r"<title>(.*?)</title>", txt, re.S|re.I).group(1).strip()[:80] if re.search(r"<title>", txt, re.I) else ""),
                              "links": links[:12], "sample": re.sub(r"<[^>]+>|\s+", " ", txt)[:0]}
        # fiyat tablosu metninden örnek satır
        clean = re.sub(r"<script.*?</script>|<style.*?</style>", " ", txt, flags=re.S|re.I); clean = re.sub(r"<[^>]+>|\s+", " ", clean)
        m = re.search(r"(DOMATES|Domates).{0,160}", clean); out[f"hal {host}"]["domates"] = m.group(0) if m else ""
        break
    except Exception as e:
        out[f"hal {host}"] = {"err": repr(e)[:160]}
pathlib.Path("reports").mkdir(exist_ok=True)
json.dump(out, open(f"reports/probe_deep_{dt.date.today()}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
