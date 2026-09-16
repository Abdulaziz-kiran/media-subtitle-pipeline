# Sezon/film ajan orkestrasyonu

Bu belge, kullanıcının tek bir yüksek seviyeli komutla (`"Bu animenin 1. sezonunu çevir"`) bütün akışı başlatabilmesi için rol sınırlarını ve iş paylaşımını tanımlar. Ana koordinatör içerik üreticisi değil süreç yöneticisidir.

## Roller

### 1. Ana koordinatör

Modeli ve eforu kullanıcı/çalışma ortamı seçer; skill en güçlü modeli zorunlu tutmaz.

Yapar:
- sezon/film işini başlatır,
- hazırlık, sezon bağlamı, çeviri, review, repair, varsayılan içerik incelemesi ve gerekirse adjudication ajanlarını çağırır,
- dosya yolları, hash'ler, kısa makbuzlar, hata kodları ve aşama durumlarını izler,
- hangi bölümün hazır olduğunu ve hangi işçinin tekrar çağrılması gerektiğini belirler,
- finalize ve arşivleme bariyerlerini uygular.

Yapmaz:
- kaynak altyazıyı kendi bağlamına almaz,
- tam çeviri veya review dosyalarını okumaz,
- dilsel karar vermez,
- işçi başarısını serbest metin "tamamlandı" mesajından kabul etmez.

## 2. Hazırlık/operasyon ajanı

Yerel Python/FFmpeg araçlarını çalıştırır. Kaynak dosyaları keşfeder, altyazıları çıkarır, bölüm kimliklerini kurar, manifest/read-pack/job klasörlerini hazırlar ve deterministic komutların başarısını doğrular. Dilsel karar vermez.

## 3. Sezon Bağlam Ajanı

Normal 12-24 bölümlük bir sezon için **tek taze ajan** bütün `season_reading_pack.json` dosyasını bir kez okur ve tek kanonik `season_context.json` üretir. Ayrıntılı görev sözleşmesi `references/sezon-baglami.md` içindedir.

Bu ajan:
- sezon çapında karakterleri,
- yönlü ilişkileri ve hitapları,
- karakter seslerini,
- terminolojiyi,
- tekrar eden espri/callback/ifadeleri,
- bölüm bazlı çeviri notlarını,
- gelecekteki bilgiyi erken açıklamayı önleyen guardrail'leri,
- çözülemeyen belirsizlikleri,
- içerik filtresi açıksa yalnız metinden görülebilen hassas sahne adaylarını
satır/hash kanıtıyla çıkarır. Adaylar kesim kararı değildir.

Ayrı ikinci bağlam ajanı varsayılan değildir. Yalnız sezon platform sınırına sığmıyorsa, ilk ajan belirli bir kapsamı çözemediğini açıkça bildiriyorsa veya kullanıcı bağımsız ikinci doğrulama istiyorsa açılır. İkinci ajan mümkünse yalnız problemli kapsamı okur.

## 4. Bölüm görünümü

`season_context.json` hiçbir bölüm çevirmenine doğrudan verilmez. `season_context.py derive-episode` ilgili bölüm için `context.json` üretir. Gelecek bölüm occurrence'ları, henüz geçerli olmayan ilişki/ses kayıtları ve spoiler niteliğindeki ham bilgi görünümden çıkarılır; yalnız güvenli guardrail kalır.

`series_context.json` ayrı katmandır: önceki finalize + bağımsız review sonrasında gerçekten onaylanmış Türkçe terim ve ilişki kararlarını hash-zincirli biçimde taşır. Çevirmen böylece hem spoiler-güvenli kaynak bağlamını hem de geçmişte onaylanmış Türkçe kararları görür.

## 5. Çevirmen ajanı

Normal anime/dizi bölümü için varsayılan **bir bölüm = bir taze çevirmen**dir. Her 20 satırlık batch için yeni ajan açılmaz; aynı ajan atanmış bölümün batch'lerini sırayla işler.

İş paylaşımı `resources/orchestration_profile.json` ile sınırlandırılır ve `scripts/translator_assignment.py --job <iş>` tarafından somut `translator_plan.json` dosyasına çevrilir:
- farklı bölüm kimlikleri aynı çevirmen parçasında asla karıştırılmaz,
- normal bölüm tek işçide kalır,
- yalnız çevrilebilir satır sayısı split eşiğini aşarsa aynı bölüm kendi içinde bölünür,
- bölme mevcut batch/sahne sınırlarında yapılır,
- bir işçi yalnız kendisine atanmış kesintisiz aralığı yazar.

Çevirmen başlangıçta yalnız:
- `context.json`,
- varsa `series_context.json`,
- `profile.json`,
- kendisine atanmış `requests/batch-*.json`
okur. Kaynak metinden fuzzy/prefix/substring eşleştirmeyle satır seçmek yasaktır; ID/hash sözleşmesi korunur.

Çevirmen bağlamı veya kanonik sözlüğü doğrudan değiştirmez. Gerçek bir belirsizlik görürse onu hedefli problem kaydı olarak işaretleyebilir; her satıra yapay güven puanı üretmez.

## 6. Bağımsız reviewer

Çeviri tamamlanıp aday kurulduktan sonra taze, bağımsız reviewer kaynak ↔ aday karşılaştırması yapar. Kontrol kapsamı en az:
- anlam kayması,
- olumsuzluk,
- özne/nesne,
- iyelik yönü,
- soru yapısı,
- hitap ve sosyal mesafe,
- terminoloji,
- karakter sesi/kayıt,
- ima/mizah/kelime oyunu,
- atlama veya kaynakta olmayan ekleme,
- satır/format/karaoke bağları.

Reviewer normal akışta çeviri dosyasını topluca yeniden yazmaz. Sorunları `issues.json` içinde satır kimliği, hata sınıfı, gerekçe ve düzeltme yönüyle raporlar. Sorun yoksa final review kaydını üretir.

## 7. Repair ajanı

Repair yalnız reviewer'ın doğrulanmış sorun kapsamını, gerekli komşu satırları ve bölüm bağlamını görür. Bölümü yeniden çevirmeye veya işaretlenmemiş satırları stil amacıyla değiştirmeye yetkili değildir. Düzeltme sonrası aday yeniden kurulur ve değişen kapsam reviewer tarafından yeniden incelenir.

## 8. Adjudicator / hakem

Normal akışta çağrılmaz. Translator/reviewer/repair arasında gerçekten çözülemeyen semantik bir anlaşmazlık kaldığında yalnız problemli satır + yakın bağlam + ilgili kanıt ile taze güçlü ajan çağrılır. Bütün bölümü yeniden okumak varsayılan değildir.

## 9. İçerik İnceleme Ajanı

Yeni videolu işlerde kullanıcı tercihiyle varsayılan aktiftir. Sezon Bağlam Ajanının bütün sezonu ikinci kez okutmaz. Her bölüm için `season_context.py derive-filter-review` çıktısını alır; bu küçük paket yalnız etkin filtre profilini, kaynak hash'ini ve o bölüme ait metin adaylarını taşır.

Ajanın görevi:
- bölümün tamamını görsel olarak taramak,
- metin adaylarının çevresini görüntü/ses/hikâye bağlamında daha yoğun doğrulamak,
- konuşmasız sahneleri de aramak,
- yalnız profil kapsamındaki kesin sahneler için başlangıç/bitiş zamanı, kategori, gerekçe ve somut kanıt yazmak,
- kesim gerekiyorsa mevcut `content_filter_pipeline.py` aracını çağırmak.

Ajan videoyu kendi yöntemleriyle yeniden kodlamaz veya zaman çizelgesini elle düzenlemez. Semantik kararı verir; keyframe hizalaması, video/altyazı kesimi, yeniden zamanlama ve kanıt arşivi deterministik motora aittir. Metin adayı olmaması bölümün temiz olduğunu kanıtlamaz.

## 10. Seri bağlamının ilerlemesi

Final ve bağımsız review sonrasında yalnız kalıcılaşmış Türkçe kararlar `series_update.json` üzerinden `series_context.py advance` ile yeni hash-zincirli revizyona taşınır. Sezon bağlamının kaynak analizi bu aşamada yeniden yazılmaz.

## 11. Model/efor profili

Rol-model varsayımları kod içine dağıtılmaz. Tek kaynak `resources/orchestration_profile.json` dosyasıdır. Kullanıcı çalışma anında bunları geçersiz kılabilir.

Mevcut tercih:
- Antigravity doğrudan kullanımında ana Gemini 3.8 Flash Medium ise `inherit` orta katmanı, `flash` yüksek katmanı sağlar; sezon bağlamı/reviewer/içerik-inceleme/adjudicator `flash`, çevirmen/repair/hazırlık `inherit` kullanır.
- Codex orkestratör olsa bile işçiler ağırlıklı olarak Antigravity/agy üzerinden Gemini 3.8 Flash kullanabilir; Codex tarafında preparation düşük, season-context yüksek, translator orta, reviewer yüksek, content-filter-reviewer yüksek, repair orta, adjudicator yüksek efor hedefidir.

Bu değerler operasyon profili, kalite kanıtı değildir; gerçek çalışma modeli/eforu yalnız telemetri varsa doğrulanmış sayılır.

## 12. Ana koordinatörün gördüğü şey

Ana koordinatöre en fazla kısa durum/makbuz dönmelidir, örneğin:

```json
{
  "job": "S01E07",
  "stage": "translation",
  "status": "complete",
  "artifact_sha256": "...",
  "warnings": 0
}
```

Tam altyazı, uzun log, tam `technical_report.json`, render görseli veya review metni ana koordinatöre taşınmaz.
