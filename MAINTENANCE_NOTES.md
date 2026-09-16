# Skill Bakım Notları — Codex / Antigravity Ajan İçin

Bu dosya, media-subtitle-pipeline skill'ine yapılan bakım düzeltmeleri ve açık kalan maddelerini izler. Codex veya başka bir ajan bu skill üzerinde çalışmaya başladığında önce bu notları okumalıdır.

Dosyanın kendisi motor çıktısı veya arşiv parçası değildir; salt bir geliştirici notudur.

---

## Son Düzeltmeler

### 0.5 Varsayılan izleme molası kararı (2026-09-14, Codex)

**Dosyalar:** `scripts/run_pipeline.py`, `scripts/viewing_breaks_policy.py`, `scripts/viewing_breaks_beta.py`

Yeni işte kalıcı tercih açıkken `prepare --video` ham video/subtitle/analiz parametrelerini sabitler. Video yoksa `no_media` ölçülmemiş durumudur. Video varsa aday analizi ve gerçek sahne incelemesi tamamlanmadan final verilmez: bağlanmış `reviewed_no_suitable` veya mevcut beta chapter kaydına bağlı `selected_applied` gerekir. Aday raporu hash'i gerçek iş dosyasından doğrulanır. Chapter'lar ham video kopyasına uygulanır, sonra mux bu chapter'ları Türkçe altyazılı kopyaya taşır; farklı medya hash'leri sessizce birbirinin yerine kullanılmaz.

### 0.4 Kimlik-temelli düz metin içe aktarma (2026-09-14, Codex)

**Dosyalar:** `scripts/run_pipeline.py`, `tests/test_pipeline.py`, `references/is-akisi.md`

Yeni işlerde biçime duyarsız bir batch, `import-translations` ile yalnız hazırlanan `request_sha256` ve eksiksiz açık `id` listesi üzerinden yazılabilir. Araç kaynak metni karşılaştırmaz: alt dize/prefix/fuzzy eşleştirme yoktur; bilinmeyen, eksik, yinelenen kimlik ve eski istek hash'i reddedilir. Yanıtın mevcut bağları hazırlanmış `response_shape`tan korunur. Etiketli, karaoke ve romaji satırları kompakt yolca sessizce düzleştirilemez; tam kaynak-bağlı şemayı kullanır. Tarihsel Sonny iş/çıktıları bu düzeltmeyle değiştirilmedi.

### 0.3 Strict orkestrasyon makbuzları (2026-09-14, Codex)

**Dosyalar:** `scripts/orchestration_contract.py`, `scripts/run_pipeline.py`, `scripts/archive_delivery.py`, `scripts/usage_ledger.py`

Yeni `prepare` işleri iş manifestindeki sürümlü işaret ve `orchestration.json` planıyla açılır. Finalden önce koordinatör, alt ajan yeteneğini kaynaklı `available|unavailable` olarak kapatır; çevirmen ve inceleyici kendi role makbuzlarını yazar. Makbuzlar yerel çeviri/aday/review hash'lerini bağlar; ajanın kimliği ile uzaktaki model/efor yalnız `agent_declared`, `platform_observed` veya `unavailable` olarak dürüstçe kaydedilir. Strict final çevirmen, inceleyici ve koordinatör için token kaydı (ölçüm veya gerekçeli `unavailable`) ister. Ölçülmüş gerçek sıfır kabul edilir, fakat telemetri kaynağı ve gerekçesi zorunludur. Tek parent-oturum toplamı yalnız koordinatöre bir kez yazılır; şema roller arası aynı ölçümün çakışmadığını kanıtlamaz.

İnceleyicinin son düzeltmesi çevirmenin ilk makbuzunu bayatlatmaz: çevirmen makbuzu ilk kaynak-bağlı snapshot'ı, inceleyici makbuzu son aday/review girişini kanıtlar. Eski işlerde strict işaret yoktur ve okunabilir kalır. Değişmez arşiv plan/makbuzları hash envanterine alır. Arşivden devam yeni bir yazılabilir denemedir; marker kalır, fakat eski role makbuzları, yetenek durumu ve token defteri yeni final için sıfırlanır.

### 0.2 Kullanım defteri kapanışı ve bağımsız review varsayılanı (2026-09-14, Codex)

Sonny Boy 02–07 saha incelemesinde bütün teslimlerin boş `runs` defteri ve `same_agent_second_pass` ile bittiği görüldü. Yeni yönerge, koordinatörün teslimden önce çevirmen ve inceleyici için tek kümülatif deftere gerçek ölçüm veya gerekçeli `unavailable` yazmasını ister. Alt ajan desteğinde bağımsız review varsayılandır; atlanırsa somut fallback gerekçesi review özetine girer. Bu belge değişikliği final için yeni katı kod kapısı eklemez.

### 0.1 Görsel QA yetkisi, alt ajan kanıt sınırı ve paralel seri kuralı (2026-09-14, Codex)

PNG/render görsel QA artık yalnız kullanıcının açık talebiyle çalışır; istenmediğinde görüntüsüz teknik ve dil denetimi sürer ve teslim özeti bu sınırı açıklar. Antigravity `Model: "inherit"` çağrısı devralma isteği olarak korunur, fakat çalışma anı telemetrisi olmadan gerçek model/efor veya maliyet kanıtı sayılmaz. Model/efor görünüyorsa kaynaklı kayda geçirilir; görünmüyorsa gerekçeli `unavailable` kullanılır ve boş `runs` sıfır değil kaydedilmemiş ölçümdür. Seri bölümleri paralel hazırlanacaksa tek sabit snapshot kullanır; ayrı iş klasörleri sonrası tek küratör bağlam güncellemelerini sırayla birleştirir. Uygulama planı kullanıcı yetkisini durdurmaz, gerçek platform izin/güvenlik engeli atlanmaz.

### 0. Kalıcı çıktı ve token kullanımı kaydı (2026-09-13, Codex)

**Dosyalar:** `scripts/usage_ledger.py`, `scripts/run_pipeline.py`, `scripts/archive_delivery.py`, `scripts/analyze_audit.py`

Her yeni iş, boş fakat sıfır anlamına gelmeyen `token_usage.json` ile açılır. Koordinatör gerçek uygulama/API sayısını `measured`, sayı görünmüyorsa gerekçeli `unavailable` olarak kaydeder; kod maliyet veya token tahmini yapmaz. Çok işli denetim, kapsamdaki her iş ölçülmedikçe toplam token sayısını boş bırakır. `receipt` yalnız küçük kullanım durum özetini taşır.

Kalıcı ek üretimler (değerlendirme notu, görsel, ses veya ileride üretilen başka çıktı) `job/artifacts/` altına konur ve final arşivinde hash envanteriyle korunur. Kaynak video buraya konmaz; altyazı işi tarafından gelecekte üretilen bir video özellikle saklanmak istenirse bu klasöre açıkça eklenebilir. Bu değişiklik, arşivin dosya envanteri/hardlink/symlink korumalarını değiştirmez.

### 1. Render regresyon testi: libass renderer çözümlemesi eklendi (2026-09-11, Antigravity)

**Dosya:** `tests/test_render_regressions.py`

**Sorun:** Test doğrudan `ffmpeg` binary adını çağırıyordu. Sistem FFmpeg'inde libass desteği yoksa (macOS temel paketi `ass` filtresini içermez) test `exit status 8` ile kırılıyordu. Skill'in üretim araçları (`verify_render_qa.py`) ise `find_renderer()` ile libass destekli binary'yi buluyor (`ffmpeg-full`, `SUBTITLE_FFMPEG` env vb.).

**Düzeltme:** Test artık `find_renderer()` fonksiyonunu kullanıyor. libass destekli binary yoksa test `skipTest` ile atlanıyor — hata yerine kontrollü atlanma.

### 2. Orkestrasyon belgesi: koordinatör akış diyagramı eklendi

**Dosya:** `references/ajan-orkestrasyonu.md`

**Eklenen:** "Koordinatör akış diyagramı" bölümü — Mermaid flowchart. Seri başlatmadan teslimata kadar tüm receipt/build/review/finalize/advance adımları ve dallanma koşulları tek diyagramda.

**Amaç:** Yeni bir ajan bu skill'i ilk kez okuduğunda, 49 satırlık prosedür metnini kavramadan önce sürecin genel haritasını görebilir.

---

## Açık Maddeler ve Gelecek Codex Oturumları İçin Öneriler

### A. Antigravity/Codex entegrasyon örneği (isteğe bağlı)

Orkestrasyon belgesi kasıtlı olarak platforma bağlı ajan API'si çağırmıyor — dosya ve makbuz protokolüne odaklanıyor. Bu tasarım doğru. Ama pratikte bir Antigravity koordinatörünün `invoke_subagent` ile çevirmen/inceleyici ajanları nasıl başlatacağını gösteren kısa bir örnek belge (`references/antigravity-entegrasyon-ornegi.md`) faydalı olabilir. Skill'in kurallarını ihlal etmez; sadece onboarding hızlandırır.

**Durum:** Tamamlandı (`references/antigravity-entegrasyon-ornegi.md`). Alt ajanların `invoke_subagent` çağrılarında model ve efor seviyesini korumak için `Model: "inherit"` kuralı zorunlu kılındı.

### B. Karaoke piksel regresyon testinin kapsamı

4 karaoke modu (`k`, `K`, `kf`, `ko`) testi artık libass bulunamazsa atlanıyor. `ffmpeg-full` kurulu sistemlerde çalışır. Ancak CI ortamında otomatik çalıştırmak istenirse `ffmpeg-full` bağımlılığını dökümante et veya test ortamı için Docker tarifi hazırla.

**Durum:** Şu an gereksiz. Kişisel kullanımda `ffmpeg-full` kurulu olduğunda testler geçiyor.

### C. Seri bağlam boyut sınırı

`series_context.py` dosya boyutunu 2 MB ile sınırlıyor (satır 92). 100+ bölümlük uzun serilerde sözlük, alias ve evidence büyümesi bu sınıra yaklaşabilir. Şu an sorun yok; ileride compaction veya arşivleme stratejisi gerekebilir.

### D. `inspect` çıktısının terim sayacı ötesinde özet vermesi

`inspect` kasıtlı olarak terim içeriğini döndürmüyor — yalnız sayaçlar. Bu doğru tasarım. Ama koordinatör ajanın "bu seride toplam kaç terim var, son bölümde kaç eklendi" bilgisini bir bakışta görmesi faydalı olabilir. `advance` çıktısına `added_count` / `changed_count` eklenebilir.

**Durum:** Düşük öncelik. Mevcut `counts` yeterli.

### E. `resume-from-archive` kesim kanıtlarını taşıyor ama incelemeyi güncel saymıyor

Bu zaten doğru davranış ve belgeli. Not olarak burada: `resume-from-archive` ile açılan yeni işte eski review'ı geçerli saymadığından, devam eden iş için tekrar inceleme gerekir.

### F. `provenance.json` üretimi ve `archive_delivery.py` entegrasyonu

`SKILL.md` satır 41-47'de tanımlanan bağımsız `provenance.json` (Çeviri Üretim Pasaportu ve Geriye Dönük Analiz Kaydı), mevcut `scripts/archive_delivery.py` tarafından bağımsız bir dosya olarak henüz otomatik üretilmemekte veya zorunlu tutulmamaktadır. İlgili telemetri ve doğrulama verileri şu an `technical_report.json`, `worker_receipts/*.json`, `orchestration.json` ve `token_usage.json` içinde dağıtık bulunmaktadır. Bu durum 2.4.1 revizyonu öncesinden gelen tarihsel bir dokümantasyon/motor tutarsızlığıdır; bir sonraki sürümde ya deterministik bir `generate_provenance` adımı eklenmeli ya da doküman makbuz mimarisine uyarlanmalıdır.


---

## Motor Sürümü

Güncel: **2.4.1**. Bu sürüm sezon bağlamı, ajan orkestrasyonu ve varsayılan içerik filtresi için işlevsel değişiklikler içerir.

## 2.4.1 — Varsayılan içerik filtresi

- `auto_content_filter` kalıcı kullanıcı tercihi olarak varsayılan açıldı.
- Sezon Bağlam Ajanı metinden görülebilen hassas sahne adaylarını çıkarıyor; adaylar tek başına kesim yetkisi değil.
- Yeni İçerik İnceleme Ajanı bölümün tamamını görsel olarak doğruluyor; Antigravity/Codex+AGY profilinde High katman kullanıyor.
- Kesim semantiği ajan tarafından, mekanik video/altyazı kesimi ise mevcut deterministik `content_filter_pipeline.py` tarafından yapılıyor.
- Kapsam ve sınırlar `resources/content_filter_profile.json` içinde tanımlandı.
- `season_context.py derive-filter-review` yalnız hedef bölümün adaylarını küçük bir devir paketi olarak çıkarıyor.



## 2.4.0 — Sezon bağlamı ve rol ayrımı

- Yeni `season_context.py`: tam sezon okuma paketi, katı sezon bağlam doğrulaması ve spoiler-güvenli bölüm görünümü üretimi.
- `season_context.json` (sabit kaynak analizi) ile `series_context.json` (review sonrası onaylanmış Türkçe karar defteri) ayrıldı.
- Bağlam ajanı normal sezonda tek kez bütün sezonu okur; ayrı ikinci bağlam ajanı yalnız sınır/belirsizlik/doğrulama ihtiyacında açılır.
- Reviewer normal akışta çeviriyi doğrudan yeniden yazmaz; hedefli `issues.json` → repair → yeniden review modeli benimsendi.
- Antigravity ve Codex+Antigravity rol/efor profilleri `resources/orchestration_profile.json` altında merkezileştirildi.
- Normal bölüm için tek translator varsayıldı; bölüm kimlikleri asla aynı işçi parçasında karıştırılmaz. Çok uzun bölüm/film yalnız profil eşiğinde mevcut sahne/batch sınırlarından bölünür.
