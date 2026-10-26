"""Dördüncü sonda: Boyner sitemap'ten giyim ürünleri + JSON-LD fiyat; Hal Kayıt Sistemi fiyat sayfası."""
import re, json, time, datetime as dt, requests, pathlib, gzip, io
UA = "KTufe-Probe/0.1 (akademik enflasyon olcumu; github.com/fkasap/KTufe)"
H = {"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}
def get(u):
    r = requests.get(u, headers=H, timeout=(10, 25))
    if "charset" not in r.headers.get("content-type","").lower(): r.encoding = r.apparent_encoding or "utf-8"
    return r
def save(out): json.dump(out, open(f"reports/probe_deep_{dt.date.today()}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
pathlib.Path("reports").mkdir(exist_ok=True); out = {}
KEYS = {"jean": r"-jean-|kot-pantolon", "tisort": r"-tisort-|t-shirt", "gomlek": r"-gomlek-", "mont": r"-mont-|-kaban-|sisme",
        "kazak": r"-kazak-|-triko-", "elbise": r"-elbise-", "sneaker": r"sneaker|spor-ayakkabi", "bot": r"-bot-|-cizme-",
        "cocuk": r"cocuk", "ic_giyim": r"boxer|-sutyen-|-corap-"}
try:
    sm = get("https://sitemap.boyner.com.tr/bynsitemap/product.xml")
    out["product_xml_status"] = sm.status_code; out["product_xml_len"] = len(sm.content)
    txt = sm.text
    locs = re.findall(r"<loc>([^<]+)</loc>", txt)
    out["product_xml_locs"] = len(locs); out["product_xml_sample"] = locs[:5]
    # alt sitemap'ler varsa ilk 2'sini aç
    prod_urls = [l for l in locs if "-p-" in l]
    subs = [l for l in locs if l.endswith(".xml") or l.endswith(".xml.gz")]
    for s in subs[:3]:
        time.sleep(1); r = get(s); body = r.content
        if s.endswith(".gz"): body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        prod_urls += re.findall(r"<loc>([^<]+-p-\d+)</loc>", body.decode("utf-8", "ignore"))
        if len(prod_urls) > 200000: break
    out["prod_urls_total"] = len(prod_urls)
    picks = {}
    for k, pat in KEYS.items():
        picks[k] = [u for u in prod_urls if re.search(pat, u)][:6]
    out["picks"] = picks; save(out)
    # her kategoriden 2 ürünü doğrula
    out["verified"] = []
    for k, urls in picks.items():
        for u in urls[:2]:
            try:
                time.sleep(1.2); p = get(u); b = p.text
                og = re.search(r'property="og:title"\s+content="([^"]{0,120})"', b)
                ld = re.findall(r'"price"\s*:\s*"?([\d.]+)"?', b)[:3]
                avail = re.search(r'"availability"\s*:\s*"?([^",}]+)', b)
                out["verified"].append({"k": k, "url": u, "status": p.status_code, "og": og.group(1) if og else "",
                                        "ld": ld, "avail": avail.group(1) if avail else ""})
            except Exception as e:
                out["verified"].append({"k": k, "url": u, "err": repr(e)[:100]})
            save(out)
except Exception as e:
    out["boyner_err"] = repr(e)[:200]; save(out)
# Hal Kayıt Sistemi
for host in ["https://www.hal.gov.tr/", "https://www.hal.gov.tr/Sayfalar/FiyatSorgula.aspx", "https://hal.ticaret.gov.tr/"]:
    try:
        r = get(host); txt = r.text
        clean = re.sub(r"<script.*?</script>|<style.*?</style>", " ", txt, flags=re.S|re.I); clean = re.sub(r"<[^>]+>|\s+", " ", clean)
        out[f"hal {host}"] = {"status": r.status_code, "len": len(txt),
            "title": (re.search(r"<title>(.*?)</title>", txt, re.S|re.I).group(1).strip()[:80] if re.search(r"<title>", txt, re.I) else ""),
            "links": re.findall(r'href="([^"]*)"[^>]*>([^<]{0,60}(?:[Ff]iyat|[Bb]ülten)[^<]{0,40})<', txt)[:12],
            "domates": (re.search(r"(?i)domates.{0,200}", clean) or [""])[0] if re.search(r"(?i)domates", clean) else "",
            "sample": clean[:400]}
    except Exception as e:
        out[f"hal {host}"] = {"err": repr(e)[:160]}
    save(out)
print(json.dumps(out, ensure_ascii=False)[:2500])
