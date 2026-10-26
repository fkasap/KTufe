"""İkinci sonda: açık sitelerde ürün sayfası düzeyinde fiyat HTML'de mi? -> reports/probe_deep_<tarih>.json"""
import re, json, time, datetime as dt, requests, pathlib, urllib.parse
UA = "KTufe-Probe/0.1 (akademik enflasyon olcumu; github.com/fkasap/KTufe)"
H = {"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}
PRICE = r"\d{1,3}(?:\.\d{3})*,\d{2}\s*(?:TL|₺)|\d{1,3}(?:\.\d{3})+\s*(?:TL|₺)"
def get(u):
    r = requests.get(u, headers=H, timeout=30); 
    if "charset" not in r.headers.get("content-type","").lower(): r.encoding = r.apparent_encoding or "utf-8"
    return r
def snap(name, url, link_re, max_links=3):
    out = {"name": name, "cat_url": url}
    try:
        r = get(url); body = r.text
        out["cat_status"] = r.status_code
        links = []
        for m in re.finditer(link_re, body):
            u = urllib.parse.urljoin(url, m.group(1))
            if u not in links: links.append(u)
            if len(links) >= max_links: break
        out["links"] = links
        out["cat_prices"] = re.findall(PRICE, body)[:8]
        out["cat_jsonld"] = '"@type":"Product"' in body.replace(" ", "") or "ItemList" in body
        out["products"] = []
        for u in links[:2]:
            time.sleep(2); p = get(u); b = p.text
            og = re.search(r'property="og:title"\s+content="([^"]{0,160})"', b)
            ld = re.search(r'"price"\s*:\s*"?([\d.,]+)', b)
            out["products"].append({"url": u, "status": p.status_code, "len": len(b),
                "title": (re.search(r"<title>(.*?)</title>", b, re.S|re.I) or [None, ""])[1].strip()[:80] if re.search(r"<title>", b, re.I) else "",
                "og_title": og.group(1) if og else "", "jsonld_price": ld.group(1) if ld else "",
                "prices": re.findall(PRICE, b)[:6]})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:160]
    print(json.dumps(out, ensure_ascii=False)[:600]); return out
res = [
 snap("boyner_jean", "https://www.boyner.com.tr/erkek-jean-pantolon-c-1022", r'href="(/[^"]+-p-\d+)"'),
 snap("boyner_kadin_kazak", "https://www.boyner.com.tr/kadin-kazak-c-1051", r'href="(/[^"]+-p-\d+)"'),
 snap("boyner_ayakkabi", "https://www.boyner.com.tr/erkek-spor-ayakkabi-c-1174", r'href="(/[^"]+-p-\d+)"'),
 snap("defacto_jean", "https://www.defacto.com.tr/erkek-jean", r'href="(/[^"]*-\d{5,}[^"]*)"'),
 snap("defacto_kadin", "https://www.defacto.com.tr/kadin-elbise", r'href="(/[^"]*-\d{5,}[^"]*)"'),
 snap("vestel_cm", "https://www.vestel.com.tr/camasir-makinesi", r'href="(/[^"]*camasir-makinesi[^"]*)"'),
 snap("vestel_bd", "https://www.vestel.com.tr/buzdolabi", r'href="(/[^"]*buzdolabi[^"]*)"'),
 snap("kahvedunyasi", "https://www.kahvedunyasi.com/", r'href="(https?://www\.kahvedunyasi\.com/[^"]*(?:kahve|cikolata)[^"]*)"'),
 snap("hal_gov", "https://www.hal.gov.tr/", r'href="([^"]*(?:Fiyat|fiyat)[^"]*)"'),
]
pathlib.Path("reports").mkdir(exist_ok=True)
json.dump(res, open(f"reports/probe_deep_{dt.date.today()}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
