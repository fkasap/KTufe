"""
Erişim sondası: GitHub runner IP'sinden aday kaynaklara GET at; HTTP kodu, robots izni,
sayfa başlığı ve fiyat benzeri metin var mı -> reports/probe_<tarih>.csv
Hiçbir veri toplanmaz; yalnızca ulaşılabilirlik ölçülür (site başına 1 istek).
"""
import re, csv, sys, time, datetime as dt, urllib.robotparser, urllib.parse, requests, pathlib
UA = "KTufe-Probe/0.1 (akademik enflasyon olcumu; github.com/fkasap/KTufe)"
CANDS = [
 # giyim / ayakkabı
 ("koton", "https://www.koton.com/erkek-jean/"), ("defacto", "https://www.defacto.com.tr/erkek-jean"),
 ("mavi", "https://www.mavi.com/erkek/jean/c/1"), ("flo", "https://www.flo.com.tr/erkek-spor-ayakkabi"),
 ("boyner", "https://www.boyner.com.tr/erkek-jean-pantolon-c-1022"), ("decathlon", "https://www.decathlon.com.tr/erkek/giyim"),
 ("hm", "https://www2.hm.com/tr_tr/erkek/urunler/jean.html"), ("zara", "https://www.zara.com/tr/tr/erkek-jean-l659.html"),
 ("lcw", "https://www.lcw.com/erkek-jean-t-194"), ("colins", "https://www.colins.com.tr/erkek-jean"),
 ("hepsiburada", "https://www.hepsiburada.com/erkek-kot-pantolon-c-12087132"), ("trendyol", "https://www.trendyol.com/erkek-kot-pantolon-x-g2-c120"),
 ("n11", "https://www.n11.com/giyim-ve-ayakkabi/erkek-giyim/pantolon/kot-pantolon"),
 # beyaz eşya / elektronik
 ("beko", "https://www.beko.com.tr/camasir-makinesi"), ("vestel", "https://www.vestel.com.tr/camasir-makinesi"),
 ("samsung", "https://www.samsung.com/tr/smartphones/all-smartphones/"), ("mediamarkt", "https://www.mediamarkt.com.tr/tr/category/camasir-makinesi-1310.html"),
 ("teknosa", "https://www.teknosa.com/camasir-makinesi-c-100005003"),
 # hal / gıda toptan
 ("ibb_hal", "https://data.ibb.gov.tr/api/3/action/package_search?q=hal"), ("ankara_hal", "https://www.ankara.bel.tr/hal-fiyatlari"),
 ("tarim_hal", "https://www.hal.gov.tr/"),
 # lokanta
 ("yemeksepeti", "https://www.yemeksepeti.com/"), ("getir_yemek", "https://getir.com/yemek/"),
 ("kahvedunyasi", "https://www.kahvedunyasi.com/"), ("starbucks", "https://www.starbucks.com.tr/menu"),
 # kira
 ("sahibinden", "https://www.sahibinden.com/kiralik-daire/istanbul"), ("hepsiemlak", "https://www.hepsiemlak.com/istanbul-kiralik"),
 ("emlakjet", "https://www.emlakjet.com/kiralik-konut/istanbul/"),
 # ulaşım / diğer
 ("thy", "https://www.turkishairlines.com/tr-tr/"), ("pegasus", "https://www.flypgs.com/"),
 ("evds", "https://evds2.tcmb.gov.tr/service/evds/series=TP.DK.USD.A&startDate=01-01-2026&endDate=05-01-2026&type=json"),
]
def robots_ok(url):
    host = urllib.parse.urlparse(url).netloc
    rp = urllib.robotparser.RobotFileParser()
    try: rp.set_url(f"https://{host}/robots.txt"); rp.read(); return rp.can_fetch(UA, url)
    except Exception: return None
rows = []
for name, url in CANDS:
    rec = {"name": name, "url": url, "robots": robots_ok(url)}
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}, timeout=25, allow_redirects=True)
        body = r.text
        title = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
        rec.update(status=r.status_code, final_url=r.url[:90], length=len(body),
                   title=(title.group(1).strip()[:70] if title else ""),
                   price_like=len(re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}\s*(?:TL|₺)|\d{1,3}(?:\.\d{3})+\s*TL", body)),
                   ctype=r.headers.get("content-type","")[:40],
                   blocked=bool(re.search(r"access denied|captcha|cloudflare|incapsula|bot|doğrulama|robot", body[:3000], re.I)))
    except Exception as e:
        rec.update(status=f"ERR {type(e).__name__}")
    rows.append(rec); print(rec); time.sleep(1.5)
out = pathlib.Path("reports") / f"probe_{dt.date.today()}.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name","status","robots","blocked","price_like","length","ctype","title","final_url","url"], extrasaction="ignore")
    w.writeheader(); w.writerows(rows)
print("yazıldı:", out)
