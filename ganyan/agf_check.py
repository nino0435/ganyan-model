"""AGF bütünlük kuralı: yarış tahmini yazılabilir/geçerli sayılabilir mi?

TJK açılışta (ya da bazı atlar için) geçici '%0' basabiliyor. Böyle bir AGF'yle yazılan tahmin
ilk-yazan-kazanır (INSERT OR IGNORE) olduğu için kalıcı olur ve ileri testi bozar.
Kural: koşudaki HER atın AGF'si bilinmeli ve > 0 olmalı, toplam ~%100 olmalı.
"""
import math

SUM_MIN = 95.0
SUM_MAX = 105.0


def _bad(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0


def agf_complete(active_values, all_values=None):
    """active_values: koşan atların AGF'si; all_values: (varsa) koşudan çekilenler dahil tüm atlar.

    Her koşan atın AGF'si bilinmeli ve > 0 olmalı; toplam (çekilenler dahil) ~%100 olmalı
    (çekilen at AGF'yi toplamdan düşürebileceği için toplam tüm atlar üzerinden bakılır).
    """
    act = list(active_values)
    if not act or any(_bad(v) for v in act):
        return False
    allv = [v for v in (all_values if all_values is not None else act) if not _bad(v)]
    return SUM_MIN <= sum(float(v) for v in allv) <= SUM_MAX
