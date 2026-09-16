# Çeviri iş akışı ve dosya sözleşmesi

## Sezon başlangıcı (dizi/anime)

Kullanıcı sezonu tek komutla çevirmek istediğinde koordinatör önce bütün bölüm kaynaklarını hazırlar, `season_manifest.json` oluşturur ve yalnız bir Season Context ajanına okunacak temiz paketi üretir:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py prepare-pack \
  --manifest <season_manifest.json> --output <season_reading_pack.json>
```

Season Context ajanı `references/sezon-baglami.md` sözleşmesine göre bütün paketi bir kez okuyup `season_context.json` yazar. Ardından:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py validate --context <season_context.json>
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py inspect --context <season_context.json>
```

Her bölüm hazırlanırken LLM'ye sezonun tamamı yeniden okutulmaz. Spoiler-güvenli bölüm görünümü deterministik olarak türetilir:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py derive-episode \
  --context <season_context.json> --episode-id S01E01 --output <episode-context.json>
```

Bu `episode-context.json` normal `run_pipeline.py prepare --context` girdisidir. `season_context.json` kaynak analizi olarak sabit kalır; review sonrası onaylanmış Türkçe kararlar ayrı `series_context.py` revizyonlarında gelişir.

`<skill_dir>` bu dosyanın üstündeki skill klasörüdür. Bağlantıdan açılmışsa gerçek klasörü çöz. Komutları görevi yürüten ajan çalıştırır.

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py prepare --input kaynak.ass --job is/bolum01 --context context.json
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py status --job is/bolum01
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py handoff --job is/bolum01
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py receipt --job is/bolum01 --stage translation
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py record-token-usage --job is/bolum01 --input olculmus-token-kullanimi.json
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py build --job is/bolum01
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py finalize --job is/bolum01 --output teslim/bolum01.tr.ass
uv run --project <skill_dir> python <skill_dir>/scripts/run_pipeline.py resume-from-archive --archive arsiv/paket --job is/bolum01-yeni
```

`handoff`, yeni sohbet veya bağlam sıkıştırması sonrası için sabit boyutluya yakın kısa devir özeti verir. Altyazı metnini, eski batch listesini, FFmpeg loglarını ve görselleri cevaba katmaz; toplam/mevcut/eksik parti sayısını, sıradaki eylemi ve başlangıçta okunacak en küçük dosya listesini bildirir. Alt ajan desteği olmayan fallback'te dizi işinin her bölümü için ayrı sohbet/görev aç; alt ajan desteğinde ise tek seri koordinatör sohbeti ve `receipt` protokolünü kullan. Devamı sohbet transkriptinden değil iş klasöründen al. Uzun tek işte sohbet değiştirirken mevcut batch'i önce `translations/` altına yaz. `handoff` dosya içeriğini doğrulamaz; normal `build` ve `finalize` hash/kapsama denetimleri geçerliliğini korur.

Alt ajanlı seri akışında ana sohbet `handoff` veya `status` yerine `receipt` kullanır. Bu komut `context`, `translation`, `review` ve `delivery` aşamalarında iş dosyalarını yerelde doğrular, sabit alanlı en fazla 2 KB makbuz yazar ve konsola yalnız makbuz yolu/hash'i ile durumu döndürür. Makbuz altyazı, çeviri, bağlam özeti, review özeti, log veya görsel içermez.

Bölüm `prepare` edildikten sonra çevirmen paylaşımını elle tahmin etme:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/translator_assignment.py --job <iş>
```

Normal bölüm profil eşiğinin altındaysa tek işçi atanır. Çok uzun bölüm/film varsa yalnız mevcut batch/sahne sınırlarında kesintisiz aralıklar oluşturulur; farklı bölüm kimlikleri aynı planda birleştirilmez.

`prepare`, boş bir `token_usage.json` defteri oluşturur; bu sıfır token kullanımı anlamına gelmez, henüz ölçüm yazılmadığını gösterir. Strict işte koordinatör teslimden önce çevirmen, inceleyici ve koordinatör rollerinin tamamını içeren tek kümülatif defteri yazar. Her ajan çalışması için gerçek uygulama/API ölçümü varsa rol, model, kaynak, giriş/çıkış/cache token sayıları `measured` olarak kaydedilir. Ölçüm yüzeyi yoksa `unavailable` ve somut neden yazılır; uygulamada görünen model/efor çağrı bağlamı olabilir fakat çalışma anı telemetrisi değildir. Tek ana-oturum toplamı yalnız `coordinator` rolüne bir kez yazılır; rol kırılımı görünmüyorsa çevirmen/inceleyici sayısı `unavailable` kalır, toplam kopyalanmaz. Şema roller arası ölçüm çakışmasını otomatik kanıtlamaz. Tahmin, oran veya maliyet uydurulmaz. `record-token-usage` dosyayı şemaya göre denetleyip işe koyar. `receipt` yalnız defterin özet durumunu gösterir. Çok işli kalite/maliyet değerlendirmesi `analyze_audit.py` ile yapıldığında toplam token sayıları, kapsamdaki bütün işler ölçülmedikçe boş kalır.

`prepare` kaynağı bir kez kopyalar, hash'ini ve çevrilecek kimlikleri sabitler. Mevcut iş klasörünü ezmez. Profil değişikliği `--profile` ile verilebilir. `context.json` önceden hazırlanmış ve `context_prepared:true` olmalıdır. Her `context_sources` girdisi `kind`, `reference`, `finding` taşır. `context_checks`, sözlük/ilişki/ses/belirsizlik/şarkı alanlarının `populated`, `reviewed_none_found` veya `not_applicable` durumunu içerikle tutarlı biçimde belirtir. Tek harflik özet/kaynak beyanı reddedilir; bu biçim kontrolleri kaynağın doğruluğunu tek başına kanıtlamaz. Sonradan değişen bağlam incelemeyi geçersizleştirir.

`auto_viewing_breaks:true` olan yeni işte video verildiyse `prepare --video <ham-mkv>` ham video hash'ini, kaynak altyazı hash'ini ve sabit analiz parametrelerini iş manifestine bağlar. Ardından:

```sh
python <skill_dir>/scripts/run_pipeline.py analyze-viewing-breaks --job <iş>
```

komutu yalnız bu üç bağla eşleşen `viewing_breaks/candidates-<hash>.json` adayını üretir; aynı dosya varsa doğrulayıp yeniden kullanır. Mekanik adaylar hikâye kararı değildir. Görüntü, ses ve yakın diyalog incelendikten sonra uygun durak yoksa şu küçük girdiyi kaydet:

```json
{"status":"reviewed_no_suitable","reason":"Görüntü, ses ve yakın diyalog incelendi; güvenli bir ara noktası bulunamadı.","reviewed_by":"inceleyen"}
```

```sh
python <skill_dir>/scripts/run_pipeline.py record-viewing-break-outcome --job <iş> --input <sonuc.json>
```

Komut gerçek aday raporunun dosya hash'ini, video/subtitle/parametre bağlarını kendisi kaydeder. Durak seçildiyse önce aynı ham videoya `viewing_breaks_beta.py apply --job <iş>` uygula; sonra `{"status":"selected_applied","chapter_record_file":"chapters-<12hex>.json"}` girdisini aynı komuta ver. Türkçe ASS paketleme bu chapter'lı yeni kopyadan `mux_mkv.py` ile yapılır; mux mevcut chapter metadata'sını korur. Ham video, chapter'lı kopya ve son mux çıktısı birbirinin hash'i yerine geçirilmez. Video verilmemiş salt altyazı işinde `no_media`/`not_assessed` kaydı yeterlidir; uygun durak bulunmadığı iddia edilmez. Video verilmiş işte `pending` ile finalize reddedilir. Bu akış render/PNG görsel QA'sını başlatmaz.

Her `requests/batch-NNNN.json` dosyası sahne boşluklarına göre bölünmüş, azami 20 hedef satır ve iki komşu bağlam satırı içerir. Sahne birden fazla dosyaya bölünüyorsa ortak bağlamı koru. Ajan cevabı `translations/batch-NNNN.json` konumuna yazar:

```json
{"source_sha256":"istekteki gerçek hash","lines":[{"index":0,"tr_text":"Türkçe karşılık","unchanged_reason":""}]}
```

Sadece o partideki kimlikleri doldur. Negatif, yinelenen, eksik veya yanlış kaynağa ait kimlik reddedilir. Aynen kalması gereken özel ad/ünlem varsa somut `unchanged_reason` gerekir. Bu alan uzun İngilizce cümleleri çevirmeden geçirmek için kullanılmaz. Gerçek satır sonu yerine ASS `\N` kullan.

Biçime duyarsız bir batch için yeni işlerde varsayılan yazma yolu, kaynak cümlesini aramak değil açık kimlikli içe aktarmadır. Ajan yalnız istek dosyasındaki `request_sha256` ve her hedef satırın `id` değerini kullanır:

```json
{"schema_version":1,"request_sha256":"istekteki tam hash","lines":[{"id":0,"tr_text":"Türkçe karşılık"}]}
```

```sh
python <skill_dir>/scripts/run_pipeline.py import-translations --job <iş> --batch batch-0001.json --input <kimlikli-ceviri.json>
```

Komut tam kapsama ister; bilinmeyen, eksik veya yinelenen `id`, yanlış/eskimiş istek hash'i ve mevcut batch'i ezme isteği reddedilir. Kaynak metnini substring, prefix veya fuzzy eşleştirme ile kimlik yerine kullanma. `unchanged_reason` ancak gerçekten kaynakla aynı bırakılan satır için giriş nesnesine eklenebilir. Etiketli, karaoke veya romaji satırı varsa bu dar yol reddeder; isteğin tam `response_shape` şemasını kaynak bağlarıyla kullan.

Etiketsiz satır `tr_text` kullanır. ASS etiketli satırda isteğin oluşturduğu sabit parçaları doldur:

```json
{"index":0,"parts":[{"part":0,"source_text":"","tr_text":""},{"part":1,"source_text":"Stop","tr_text":"Dur"},{"part":2,"source_text":" here.","tr_text":" burada."}],"unchanged_reason":""}
```

Araç `source_text` bağını ve görünür kaynak slotlarının görünür karşılık taşımasını doğrular, özgün etiketleri parçaların arasına kendisi koyar; serbest `tr_text` veya taşınabilir marker kabul etmez. Türkçe sözdizimi biçim kapsamını değiştirmeyi zorunlu kılıyorsa en az 20 karakterlik somut `scope_change_reason` gerekir; bu istisna görsel/anlamsal incelemenin yerine geçmez. Karaoke satırında Türkçe `tr_text`, `romaji_status`, `romaji_source` ve varsa sabit `romaji_parts` kullanılır. `verified` romaji somut kaynak gerektirir; romaji slotlarında satır kaçışı reddedilir. Araç karaoke etiketlerinden sonra `\N` öncesinde biçim sıfırlaması ekleyerek Türkçe satıra zaman etiketi taşınmasını engeller. Biçime duyarlı her satırın review kaydında `formatting_reviewed:true` gerekir.

`build` yalnız aday üretir. `technical_report.json` dosyasında her satırın okuma hızı, satır uzunluğu, süre ve sorunları bulunur. Dosya adı ve script çıkış kodu dil kalitesi anlamına gelmez. `reassemble_ass.py` eski doğrudan çağrılar için aynı katı altyapıyı kullanır; çıktısı `candidate_needs_review` durumundadır.

İngilizce kaynaklı işte finalden önce `resources/learning_report_template.json` şemasına göre `learning_report.json` yaz. Tahmini CEFR'yi İngilizce altyazıyla okuma ve altyazısız dinleme için ayrı ver; `A1`–`C2` veya komşu aralık kullan. `confidence` yalnız `low|medium|high`, `fit_for_learner` yalnız `comfortable|productive_stretch|intensive_support` olur. Her evidence nesnesi `line_index`, satırda gerçekten geçen `source_excerpt` ve `reason`; her öğrenme noktası bunlara ek olarak `meaning_tr` ve `why_useful` taşır. En az birer tane zorunludur. `personal_assessment:false` bu raporun kişisel sınav olmadığını makinece sabitler. Kod yalnız şema ve alıntı bağını doğrulayabilir; CEFR/anlam/gerekçe ikinci dilsel geçişte incelenir. `review.json` içindeki `learning_report_reviewed:true`, dosyanın gerçek SHA-256 değeri ve somut inceleme özeti olmadan final verilmez.

Zaman değişikliği gerekiyorsa ses ve kesme sınırlarını inceleyip şu biçimde `timing_windows.json` yaz:

```json
{"12":{"min_end_ms":18200,"max_end_ms":18800,"evidence":"12. repliğin konuşması 18,2 sn'de bitiyor; 18,8 sn'ye kadar sessiz ve aynı plan."}}
```

Kaynak bitiş zamanı bu aralıkta olmalıdır. Araç en fazla profilin izin verdiği uzatmayı yapar, sonraki diyalogdan önce durur ve süreye bağlı ASS efektlerini kendiliğinden değiştirmez. Güvenilir pencere yoksa anlamı koruyarak kısalt; zorunlu bir istisnayı açık gerekçeyle inceleme kaydına geçir.

`review.json`, `review-template.json` yapısından hazırlanır. Ajan adı, inceleme modu ve yapılan kontrolün özeti zorunludur. Her hedef satır `reviewed:true`, `issues:[]` olmalıdır. Çözülemeyen anlam sorununu boş listeyle gizleme. Teknik istisna biçimi:

```json
{"index":12,"code":"MIN_DURATION","reason":"Kaynaktaki ani kesinti 0,9 sn; uzatma sonraki konuşmayı örtecek. Kısa tepki bu sürede okunuyor."}
```

Muafiyet yalnız mevcut sorunla eşleşir. Negatif/bozuk zaman veya boş metin muaf tutulamaz. Review, kaynak ve aday dosya hash'lerine bağlıdır. Kod bir insan/ajanın gerçekten ne okuduğunu kanıtlayamaz; inceleme kaydı açık bir beyan olarak saklanır, bağımsız doğrulama diye sunulmaz.

`finalize`, teslimi varsayılan olarak `~/Downloads/torrent/alyazılar/<eser>/<teslim--hash>/` altında ayrıca arşivler. `--archive-root` yalnız farklı bir kalıcı kök isteniyorsa kullanılır. Yeni strict işte `orchestration.json` ve `worker_receipts/` da pakete hash envanteriyle girer. `resume-from-archive` yeni, yazılabilir bir deneme açar: strict işaretini korur ama çalışma anı planını, role makbuzlarını ve token defterini sıfırlar; eski kanıt değişmez kaynak arşivde kalır ve yeni finali karşılayamaz. Paket final/kaynak ASS, QA belgesi, `job.json`, istek ve çeviri partileri, aday, bağlam, profil, review, teknik rapor, `token_usage.json`, varsa öğrenme raporu ve işte kayıtlı kesim raporlarını içerir. İşin ürettiği başka kalıcı çıktı da `job/artifacts/` altında tutulursa alt dizinleriyle birlikte pakete alınır; kaynak video buraya konmaz. Paket değişmez çalışma kaydıdır: `status` salt okunur çalışır, `build` ve `finalize` reddedilir; tekrar arşivleme mevcut dosya envanterini ve bütün hash'leri yeniden denetler. Bu, yazılabilir diskte imzalı/WORM depolama anlamına gelmez.

İki ajan aynı işi aynı anda düzenlemez. Komutlar kısa süreli dosya kilidi alır; elle yazılan çeviri partilerinde işi paylaşmak gerekiyorsa ayrık parti sahipleri belirle ve birleştirmeyi tek ajan yapsın.

## 2.3.1 ek kurallar

Etiketsiz çeviriye de ASS etiketi, süslü parantez, gerçek newline veya ASS marker'ı eklenemez. Normal diyalogda motorun desteklediği `\N` satır ayrımı kullanılabilir. Sabit slot kimliği gerçek `int` olmalı; `bool` kimlik kabul edilmez.

Karaokede `\r` tek başına karaoke saatini sıfırlamaz. Motor iki satır sınırına `{\kt0\k0}{\r}\N` ekler. Kaynağın zaman etiketleri üst satırda kalır. Dört karaoke türünde gerçek libass piksel regresyonu Türkçe alt satırın sabitliğini sınar; diğer oynatıcılar ayrıca denenmelidir. Romaji ve Türkçe şarkı alanları düz tek satırlık metindir.

Kaynak Japonca değilse ve doğrulanmış zamanlı romaji kaynakta korunmuyorsa harici Japonca söz/ses dayanağı için `romaji_evidence` gerekir: `kind` (`japanese_lyrics|original_audio`), `reference`, `reviewed_by`, en az 20 karakter `review_summary`, Japonca `japanese_text`, `language` (`ja|jpn`), `review_attested:true`, 64 haneli `source_sha256`. Araç alanların biçimini denetler; referansın ve Japonca okunuşun gerçek doğruluğu inceleyen ajanın beyanıdır. Yalnız İngilizce anlamdan okunuş türetilmez.

İngilizce kaynakta anlaşılır konuşma yoksa `listening_without_subtitles:"not_assessed"`, `listening_assessment_status:"not_assessed"` ve somut `listening_limitations` kullanılır. Bu bir CEFR seviyesi değildir; ölçüm yokluğunu belirten kontrollü durumdur. Dinleme değerlendirilmişse kontrollü CEFR değeri ve `assessed` durumu kullanılır. Okuma değerlendirmesi ve kaynak alıntısı zorunlulukları değişmez.

Arşivin yalnız dosya hash'leri değil tam envanteri de doğrulanır: fazla, eksik, yinelenmiş veya yol dışına çıkan kayıtlar; symlink, hardlink ve özel dosyalar reddedilir. Yalnız kökteki `archive-manifest.json` envanter dışında kalır; aynı isimli iç dosya bu kuralı atlatamaz. `resume-from-archive` kesim kanıtlarını taşır, incelemeyi otomatik güncel saymaz. Harici `--review` verildiğinde arşive gerçekten doğrulanan inceleme kopyalanır.
