# KTufe — Günlük veriyle, haftalık raporlanan tüketici fiyat endeksi

Web TÜFE mantığında, GitHub Actions üzerinde kendi kendine çalışan Türkiye TÜFE nowcast'ı.
Veri **günlük** toplanır (fiyat relatifleri ardışık gözlem ister), endeks **haftalık** hesaplanıp
raporlanır. Ham veri ve endeksler repoda yaşar: her hafta yeniden üretilebilir, denetlenebilir.

## Nasıl çalışır
```
collector/sepet.yaml ──► collect.yml (her gün 06:15 TR) ──► data/raw/YYYY-MM-DD.csv
                                                                   │
engine/index_engine.py ◄── weekly.yml (Pazartesi 08:00 TR) ◄───────┘
        │
        ├── data/index/item_index.csv       madde endeksleri (günlük)
        ├── data/index/headline_daily.csv   manşet + 13 ana grup (günlük)
        ├── data/index/monthly.csv          ilk-24-gün aylık endeks, aylık %, yıllık %
        └── reports/latest.md  ──► README'deki özet bloğu
```

**Hesap zinciri (TÜİK / Web TÜFE ile aynı):** SKU → madde: Jevons (geometrik ortalama,
matched-sample, ±ln3 kırpma). Madde → manşet: zincirleme Laspeyres, TÜİK ağırlıkları,
Aralık bağlantısı. Aylık okuma: ayın ilk 24 gününün geometrik ortalaması.
`engine/validate_tuik.py` motoru TÜİK'in 13 ana grup verisiyle test eder (hata ≤ 0,01 puan);
haftalık iş bu testi her seferinde çalıştırır.

## Kaynaklar
| Kaynak | Kalemler | Not |
|---|---|---|
| Market Fiyatı (Sanayi ve Tek. Bak., kamu verisi) | işlenmiş gıda, temizlik, kişisel bakım | `POST api.marketfiyati.org.tr/api/v2/search` |
| Petrol Ofisi il tablosu | benzin, motorin, LPG | statik HTML, KDV dahil |
| TCMB EVDS — TÜİK alt endeksleri | kira, tarifeler, ilaç, eğitim, hizmetler | aylık; ay içinde sabit taşınır (`EVDS_API_KEY` secret) |
| İBB Açık Veri — Hal fiyatları | taze meyve-sebze | `resource_id` portaldan girilmeli |
| Playwright | giyim, beyaz eşya, telefon, otomobil, yemek | ürün URL'leri `sepet.yaml`'da doldurulmalı |

## Kurulum
1. Repo **Settings → Secrets → Actions**: `EVDS_API_KEY` ekle (evds2.tcmb.gov.tr, ücretsiz).
2. `collector/sepet.yaml` içindeki `RESOURCE_ID_GIRIN` ve `URUN_URL_GIRIN` yer tutucularını doldur
   (doldurulmayanlar `missing` yazar, endeks o SKU'yu atlar — sistem çalışmaya devam eder).
3. Yerelde bir kez `python collector/smoke_test.py` çalıştırıp hangi kaynağın yanıt verdiğini gör.
4. **Actions → Günlük fiyat çekimi → Run workflow** ile ilk çekimi elle tetikle.
5. 8+ gün veri birikince **Haftalık TÜFE hesabı** anlamlı sonuç verir; 12 ay sonra yıllık % dolar.

## Bilinçli tasarım kararları
- **Günlük toplama, haftalık hesap.** Haftalık toplama matched-sample'ı bozar ve ilk-24-gün
  kuralını imkânsız kılar. Günlük çekim ~5 dk sürer, ücretsiz kota içindedir.
- **Boşluk toleransı 3 gün.** Cron atlarsa ya da site cevap vermezse SKU zinciri kopmaz
  (`max_gap_days`). Daha uzun boşluk = delist kabul edilir, zincir yeniden başlar.
- **Carry-forward kalemler** (kira, tarife, hizmet; ağırlığın ~%40'ı) TÜİK alt endeksiyle
  taşınır. Bu eksik veri değil, tercihtir: bu kalemler ay içinde değişmez; sürpriz, günlük
  fiyatlanan %60'tan gelir.
- **Datacenter IP'si.** Runner ABD'dedir; bir kaynak botu engellerse `status=blocked`
  yazılır ve retry yapılmaz. Engel kalıcıysa o kaynak için self-hosted runner ya da
  TR'deki bir makineden günlük `collector.py` çalıştırıp sonucu push etmek gerekir.
- **Nezaket.** robots.txt'ye uyulur, host başına ≥2 sn beklenir, kimlikli User-Agent kullanılır.
  Pazar yeri URL'lerini eklemeden önce kullanım şartlarını siz değerlendirin.

## Sınırlar (dürüstçe)
Bu bir nowcast'tır: TÜİK aylık rakamına ±0,3–0,5 puan yaklaşmak hedef, tutturmak değil.
TÜİK 81 ilde 39 bin işyerinden fiyat alır; burada İstanbul ağırlıklı online fiyat var.
Madde içi ağırlıklar TÜİK'in 428 maddelik dosyası eklenene kadar yaklaşıktır
(`agirlik_durum: yaklasik`); ana grup ağırlıkları EVDS'den kesindir.

## Bölgeler ve ağırlıklar (güncelleme 26.10.2026)
- **Bölgeli toplama:** `sepet.yaml > regions` — İstanbul (TR10) ve Ankara (TR51). Market Fiyatı
  bölge koordinatıyla, Petrol Ofisi il adıyla ayrı çağrılır; İBB Hal yalnız İstanbul. Konumsuz
  kaynaklar (EVDS alt endeksleri) her bölgeye aynı yazılır. **Türkiye** = bölge endekslerinin
  `pay_tr` ile ağırlıklı geometrik birleşimi (şehir eklenince paylar güncellenir).
- **TÜİK 2026 sepeti** `data/reference/tuik_sepet_agirlik_2026.csv` (TÜİK Veri Portalı,
  DF_TUFE_SDMX_TT04). TÜİK ağırlığı **5. düzeyde (174 alt sınıf) biter; 428 maddeye ağırlık
  yayınlamaz.** `madde_agirlik_2026_turetilmis.csv` alt sınıf ağırlığını maddelere eşit böler
  (79 alt sınıf tek maddeli → o maddeler kesin). Sepetteki kodlar TÜİK 5. düzey kodlarıdır;
  her ana grubun kalanı `artik: true` kalemiyle EVDS alt endeksinden taşınır → 13 ana grup
  ağırlığı TÜİK ile birebir.
- **Grafikler** (`reports/charts/`, haftalık iş üretir): bölge başına ana grup haftalık ve
  aylık değişim, en çok/en az değişen maddeler; Türkiye için KTüfe–TÜİK aylık karşılaştırma.
- **Doğrulama kıyası:** TÜİK bölgesel TÜFE (İBBS-2: TR10 İstanbul, TR51 Ankara) aynı veri
  portalından; EVDS'de bölgesel seri yok.

## EVDS verisi nasıl geliyor (26.10.2026 sonrası)
TCMB EVDS, GitHub runner'ının yurt dışı IP'sine JSON yerine HTML doğrulama sayfası döndürüyor
(HTTP 200, `text/html`). Bu yüzden EVDS canlı çağrılmaz; TÜİK alt endeksleri
`data/reference/evds_alt_endeksler.csv` dosyasından okunur (`evds_file` adaptörü). Dosya
TÜİK'in her ayın 3'ünde açıkladığı veriden sonra tazelenir (25 seri, 2024-12'den itibaren).
Tazeleme: EVDS erişimi olan bir yerden `scripts/refresh_tuik.py` ya da elle. Kira, tarife,
eğitim gibi bu kalemler ay içinde değişmediği için günlük çekimde canlı veri kaybı yoktur.

## Kaynak durumu — 26.10.2026 canlı testleri (GitHub bulut runner, ABD IP)
| Kaynak | Sonuç | Not |
|---|---|---|
| Market Fiyatı (40 SKU) | ✅ 37 ok | Zincirler ulusal fiyat uyguluyor; İstanbul=Ankara |
| Petrol Ofisi (3 ürün × 2 il) | ✅ 6/6 | Tek bölgesel fark üreten canlı kaynak |
| Toyota (6 model) | ✅ 6/6 | Model çapalı, kampanyalı fiyat |
| Apple TR (3 ürün) | ✅ 3/3 | iPhone 17 256/512, MacBook Air |
| EVDS alt endeksleri (21 seri) | ✅ dosyadan | Canlı EVDS yurt dışı IP'ye kapalı |
| LCW giyim (30 SKU) | ❌ Access Denied | IP engeli; self-hosted (TR) runner'da çalışır |
| Arçelik | ❌ robots disallow | Uyuluyor; TÜİK taşıma |
| Togg | ⏳ Playwright'a alındı | Fiyat tablosu JS ile yükleniyor |
| İBB Hal | ❌ zaman aşımı | IP engeli olası; resource_id de girilmeli |
| Lokanta zincirleri | ❌ fiyat yok | Konum/sipariş akışı gerektiriyor; TÜİK taşıma |

**Öneri:** `collect.yml` için Mac'te self-hosted runner (TR IP). EVDS canlı, LCW, Hal tek
hamlede açılır; haftalık hesap bulutta kalır. `runs-on: [self-hosted, macOS]` yeterli.
