"""
Web TÜFE tarzı günlük tüketici fiyat endeksi motoru
===================================================

Katmanlar (alttan üste):
  1. Ürün (SKU)  ->  günlük fiyat relativesi  r = p_t / p_{t-1}    (matched sample)
  2. Madde (COICOP 7. düzey) -> Jevons: exp(mean(ln r))  ile zincirlenen madde endeksi
  3. Grup / Ana grup / Genel -> ağırlıklı toplulaştırma
        - "laspeyres": TÜİK usulü zincirleme Laspeyres (yıllık sabit ağırlık,
                       Aralık bağlantı ayı; ağırlıklar fiyat-güncellenir)
        - "fisher"   : webtufe-PCE usulü, aylık dinamik ağırlıkla
                       sqrt(Laspeyres x Paasche)
  4. Aylık endeks = ayın ilk 24 gününün geometrik ortalaması (webtufe kuralı)
     Aylık enflasyon, yıllık (YoY) enflasyon, kümülatif.

Bütün fonksiyonlar saf pandas; hiçbir veri kaynağına bağımlı değildir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# 1-2. Ürün -> Madde (Jevons)
# --------------------------------------------------------------------------

def jevons_item_index(prices: pd.DataFrame,
                      min_obs: int = 3,
                      base_value: float = 100.0,
                      clip_log: float | None = np.log(3.0),
                      max_gap_days: int = 3) -> pd.DataFrame:
    """
    prices: uzun format DataFrame, sütunlar = [date, item, sku, price]
            date  : gün (datetime)
            item  : COICOP madde kodu (ör. '0111201' ya da 'ekmek')
            sku   : site+ürün kimliği (eşleştirilmiş ürün)
            price : TL fiyat (>0)

    Dönüş: geniş format DataFrame (index=date, columns=item), madde endeksi.

    Kurallar:
      * Matched-sample: bir SKU, hem t hem t-1'de fiyatı varsa relative üretir.
        (Ürün giriş/çıkışı endeksi sıçratmaz — TÜİK/Jevons standardı.)
      * Günlük relative'in logu +-ln(3) ile kırpılır (aykırı değer / hatalı
        scrape koruması). None verilirse kırpma yapılmaz.
      * Bir gün için madde altında min_obs'dan az eşleşme varsa o gün madde
        endeksi önceki güne eşit taşınır (carry-forward).
    """
    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[df["price"] > 0]
    # Aynı sku aynı gün birden fazla gözlem -> medyan (flash-sale gürültüsü)
    df = df.groupby(["item", "sku", "date"], as_index=False)["price"].median()
    df = df.sort_values(["item", "sku", "date"])
    df["logp"] = np.log(df["price"])

    # Önceki gözlem günü ve fiyatı
    g = df.groupby(["item", "sku"])
    df["prev_date"] = g["date"].shift(1)
    df["prev_logp"] = g["logp"].shift(1)
    # Ardışık iki gözlem arası en fazla max_gap_days ise eşleşir (GitHub Actions
    # cron'u bir gün atlarsa zincir kopmasın). Daha uzun boşluk (stok yok,
    # delist) -> o SKU'nun zinciri kopar, yeniden başlar. Çok günlük boşlukta
    # değişim, boşluğun SON gününe yazılır; ilk-24-gün ortalaması bunu yumuşatır.
    gap = (df["date"] - df["prev_date"]).dt.days
    matched = df[(gap >= 1) & (gap <= max_gap_days)].copy()
    matched["dlog"] = matched["logp"] - matched["prev_logp"]
    if clip_log is not None:
        matched["dlog"] = matched["dlog"].clip(-clip_log, clip_log)

    daily = (matched.groupby(["date", "item"])["dlog"]
             .agg(["mean", "count"]).reset_index())
    daily.loc[daily["count"] < min_obs, "mean"] = 0.0  # carry-forward

    all_dates = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    items = sorted(df["item"].unique())
    dlog_wide = (daily.pivot(index="date", columns="item", values="mean")
                 .reindex(index=all_dates, columns=items).fillna(0.0))
    idx = base_value * np.exp(dlog_wide.cumsum())
    idx.index.name = "date"
    return idx


# --------------------------------------------------------------------------
# 3. Toplulaştırma
# --------------------------------------------------------------------------

def _price_updated_weights(w: pd.Series, item_idx: pd.DataFrame,
                           link_date, ref_date) -> pd.Series:
    """
    TÜİK'in 'fiyat-güncellenmiş ağırlık' adımı.
    Harcama ağırlıkları (w) bir referans dönemine (ör. HBA yılı) aittir;
    bağlantı ayına (Aralık) taşınmak için her maddenin ref->link fiyat
    değişimiyle çarpılıp yeniden normalize edilir.
    ref_date None ise ağırlıklar zaten bağlantı ayına ait kabul edilir.
    """
    if ref_date is None:
        return w / w.sum()
    rel = item_idx.loc[link_date] / item_idx.loc[ref_date]
    w2 = (w * rel).dropna()
    return w2 / w2.sum()


def chained_laspeyres(item_idx: pd.DataFrame,
                      weights_by_year: dict[int, pd.Series],
                      link_month: int = 12,
                      base_value: float = 100.0,
                      ref_dates: dict[int, pd.Timestamp] | None = None) -> pd.Series:
    """
    TÜİK usulü yıllık zincirleme Laspeyres.
      I_t = I_link(y) * sum_i w_i,y * ( P_i,t / P_i,link(y) )
    link(y) = yıl y-1'in Aralık ayı (günlük seride Aralık'ın son günü).
    weights_by_year: {2025: Series(index=item, value=ağırlık), 2026: ...}
    Ağırlıklar yüzde ya da pay olabilir; normalize edilir.
    İlk yılın bağlantı noktası serinin ilk günüdür.
    """
    item_idx = item_idx.sort_index()
    years = sorted(weights_by_year)
    out = pd.Series(index=item_idx.index, dtype=float)
    level_at_link = base_value
    link_date = item_idx.index[0]
    for y in years:
        w = weights_by_year[y].reindex(item_idx.columns).dropna()
        w = _price_updated_weights(
            w, item_idx, link_date,
            (ref_dates or {}).get(y))
        cols = w.index
        seg_mask = (item_idx.index >= link_date) & (item_idx.index.year == y)
        seg = item_idx.loc[seg_mask, cols]
        if seg.empty:
            continue
        rel = seg.div(item_idx.loc[link_date, cols], axis=1)
        out.loc[seg.index] = level_at_link * (rel * w).sum(axis=1)
        # bir sonraki yılın bağlantı noktası: bu yılın Aralık son günü
        dec = item_idx.index[(item_idx.index.year == y)
                             & (item_idx.index.month == link_month)]
        if len(dec):
            link_date = dec[-1]
            level_at_link = out.loc[link_date]
    if pd.isna(out.iloc[0]):
        out.iloc[0] = base_value
    return out.ffill()


def chained_fisher(item_idx: pd.DataFrame,
                   weights_by_month: dict[pd.Period, pd.Series],
                   base_value: float = 100.0) -> pd.Series:
    """
    webtufe-PCE usulü aylık zincirleme Fisher-Ideal.
      Ay m içindeki her gün t için (bağlantı: m-1'in son günü L):
        L_t = sum_i w_i,m-1 * (P_i,t / P_i,L)          (Laspeyres)
        P_t = 1 / sum_i w_i,m   / (P_i,t / P_i,L)      (Paasche)
        F_t = sqrt(L_t * P_t);  I_t = I_L * F_t
    weights_by_month: {Period('2025-01','M'): Series(item->ağırlık), ...}
    """
    item_idx = item_idx.sort_index()
    out = pd.Series(index=item_idx.index, dtype=float)
    months = sorted(weights_by_month)
    link_date = item_idx.index[0]
    level_at_link = base_value
    for k, m in enumerate(months):
        w_cur = weights_by_month[m].reindex(item_idx.columns).dropna()
        w_prev = (weights_by_month[months[k - 1]] if k > 0 else w_cur)
        cols = w_cur.index.intersection(w_prev.index)
        w_cur = w_cur[cols] / w_cur[cols].sum()
        w_prev = w_prev[cols] / w_prev[cols].sum()
        seg = item_idx[(item_idx.index.to_period("M") == m)
                       & (item_idx.index > link_date)][cols]
        if seg.empty:
            continue
        rel = seg.div(item_idx.loc[link_date, cols], axis=1)
        lasp = (rel * w_prev).sum(axis=1)
        paas = 1.0 / (w_cur / rel).sum(axis=1)
        fisher = np.sqrt(lasp * paas)
        out.loc[seg.index] = level_at_link * fisher
        link_date = seg.index[-1]
        level_at_link = out.loc[link_date]
    out.iloc[0] = base_value
    return out.ffill()


# --------------------------------------------------------------------------
# 4. Aylık okuma ve enflasyon oranları
# --------------------------------------------------------------------------

def monthly_index(daily: pd.Series, first_n_days: int = 24) -> pd.Series:
    """
    webtufe kuralı: aylık endeks = ayın ilk `first_n_days` gününün
    geometrik ortalaması. (TÜİK fiyat derleme takvimi ayın ilk ~3 haftası.)
    """
    s = daily.dropna()
    s = s[s.index.day <= first_n_days]
    return np.exp(np.log(s).groupby(s.index.to_period("M")).mean())


def inflation_table(monthly: pd.Series) -> pd.DataFrame:
    m = monthly.sort_index()
    return pd.DataFrame({
        "endeks": m,
        "aylik_%": (m / m.shift(1) - 1) * 100,
        "yillik_%": (m / m.shift(12) - 1) * 100,
        "yilbasi_%": (m / m.groupby(m.index.year).transform("first").shift(1) - 1) * 100,
    })


def contributions(item_idx: pd.DataFrame, weights: pd.Series,
                  t0, t1) -> pd.DataFrame:
    """
    t0->t1 arası manşet değişime madde/grup katkıları (Laspeyres yaklaşımı):
      katkı_i = w_i * (P_i,t1/P_i,t0 - 1) * 100 (puan)
    Fon yöneticisi gözüyle 'hangi kalem enflasyonu sürüklüyor' sorusunun cevabı.
    """
    w = weights.reindex(item_idx.columns).dropna()
    w = w / w.sum()
    chg = item_idx.loc[t1, w.index] / item_idx.loc[t0, w.index] - 1
    df = pd.DataFrame({"agirlik_%": w * 100, "degisim_%": chg * 100,
                       "katki_puan": w * chg * 100})
    return df.sort_values("katki_puan", ascending=False)
