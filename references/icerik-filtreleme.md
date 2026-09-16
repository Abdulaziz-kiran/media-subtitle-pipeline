# Varsayılan içerik filtresi

Bu özellik kullanıcı tercihiyle varsayılan aktiftir. Amaç çeviri metnini yumuşatmak değil; kapsam içindeki doğrulanmış sahneleri medya zaman çizelgesinden çıkarmaktır.

## Rol ayrımı

1. **Sezon Bağlam Ajanı (High katman)** bütün sezon metnini zaten okurken yalnız metinden fark edilebilen adayları `content_filter_candidates` alanına ekler. Kesim zamanı belirlemez ve adayını kesim kararı saymaz.
2. **İçerik İnceleme Ajanı (High katman)** bölüm bazında çalışır. Bütün sezonu yeniden okumaz. `derive-filter-review` çıktısını, bölüm videosunu ve gerekirse yakın altyazı bağlamını inceler. Bölümün tamamında görsel tarama yapar; metin adaylarını daha yoğun doğrular; konuşmasız sahneleri de arar. Sonuçta yalnız gerçekten kapsam içindeki aralıkları `cuts.json` olarak yazar.
3. **Deterministik kesim motoru** `content_filter_pipeline.py` planı anahtar karelere göre uygular, video ve altyazıyı aynı zaman haritasıyla keser, gerekirse altyazı bağlam notunu ekler ve kanıt paketini arşivler. Kesim semantiğine karar vermez.

Ayrı bir “kesme ajanı” açılmaz. İçerik İnceleme Ajanı planı hazırlar ve mevcut Python aracını çağırabilir; böylece karar ile mekanik uygulama ayrılır ama gereksiz bir LLM rolü oluşmaz.

## Varsayılan kapsam

Kanonik tanımlar `resources/content_filter_profile.json` içindedir. Özet:

- açık romantik/cinsel dudaktan öpüşme → kes,
- gösterilen veya açık biçimde ima edilen cinsel eylem / belirgin cinsel yakınlaşma → kes,
- yatak/yatak odasında romantik-cinsel yakınlığın sahnenin odağı olduğu sahne → kes,
- sıradan uyuma, dinlenme, hastalık, normal konuşma → kesme,
- ailevi/platonik yanak veya alın öpücüğü → varsayılan olarak kesme,
- yalnız diyalogdaki cinsel gönderme → sahnenin kendisi kapsamda değilse kesme,
- belirsiz durum → görsel doğrulama olmadan kesme.

## Neden bağlam ajanı tek başına yapmıyor?

Altyazı metni sahnenin anlamını ve muhtemel bölgeleri bulmada ucuz bir ön filtre sağlar, fakat sessiz bir öpüşme veya görüntüyle anlatılan yatak sahnesi metinde hiç görünmeyebilir. Öte yandan İçerik İnceleme Ajanına sezonun bütün metnini yeniden okutmak da gereksizdir. Bu yüzden görevler birbirini tamamlar: sezon ajanı ucuz aday üretir, bölüm ajanı görsel doğrulama yapar.

## Maliyet mantığı

Bu rol uzun çeviri çıktısı üretmez. Girdisi görüntü/açıklama bakımından nispeten büyük olabilir, ancak çıktısı birkaç kesim kaydıdır. Yanlış sahne kesmenin maliyeti yüksek olduğundan High katmanı mantıklıdır. Antigravity profilinde `flash`, Codex + Antigravity worker profilinde High kullanılır.

## Çalışma sırası

Normal bölüm akışı:

`hazırlık → sezon bağlamı → çeviri → bağımsız dil denetimi/repair → içerik inceleme → Python kesimi → teknik QA/mux/finalize`

Kesim çeviriden sonra yapılır. Bu, mevcut kanıt/arşiv ve subtitle-retiming motorunu bozmadan çalışır. Birkaç kesilecek satırın çevrilmesi küçük bir maliyet oluşturur; bunun karşılığında tek iş klasörü ve daha az kırılgan bir akış korunur.

## Güvenlik sınırı

`content_filter_candidates` veya altyazı anahtar sözcüğü tek başına kesim yetkisi değildir. Her üretim kesiminde `category`, `cut_reason`, somut `evidence`, `reviewed_by`, başlangıç/bitiş zamanı ve etkin politika bulunmalıdır. Görüntü gerçekten incelenmediyse kesim yapılmaz.
