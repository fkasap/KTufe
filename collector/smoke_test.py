"""
Duman testi: sepet.yaml'daki her kaynak türünden BİR örnek çağrı yapar ve
hangi kaynağın canlı yanıt verdiğini raporlar. İlk kurulumda çalıştırın:

    export EVDS_API_KEY=...        # evds2.tcmb.gov.tr -> Profil -> API Anahtarı
    python collector/smoke_test.py

Çıktı: kaynak | durum | örnek değer | not
"""
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adapters import ADAPTERS

TESTS = [
    ("marketfiyati", {"keywords": "ekmek 250 g"},
     "Boş dönerse: lat/lon/distance'ı genişletin ya da keywords'ü platformda deneyin"),
    ("petrolofisi", {"il": "ISTANBUL (AVRUPA)", "urun": "benzin"},
     "None ise sayfa yapısı değişmiş olabilir; regex'i güncelleyin"),
    ("evds", {"series": "TP.TUKFIY2025.04110"},
     "None ise EVDS_API_KEY yok ya da hatalı"),
    ("ibb_hal", {"resource_id": "RESOURCE_ID_GIRIN", "urun": "DOMATES"},
     "resource_id'yi data.ibb.gov.tr'den 'hal fiyat' aramasıyla alın"),
]

print(f"{'kaynak':<14}{'durum':<10}{'deger':<14}not")
for name, cfg, note in TESTS:
    t0 = time.time()
    try:
        v = ADAPTERS[name](cfg)
        status = "OK" if v is not None else "BOS"
    except Exception as e:
        v, status = None, f"HATA:{type(e).__name__}"
    print(f"{name:<14}{status:<10}{str(v)[:12]:<14}{note}  ({time.time()-t0:.1f}s)")
