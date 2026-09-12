# Medya araçları

Başlamadan `doctor.py` ile Python/pysubs2, FFmpeg/FFprobe ve libass çizme desteğini kontrol et. `uv` bağımlılığı kilitli sürümden kurar. macOS temel FFmpeg paketi libass içermiyorsa `ffmpeg-full` gerekir; araç mevcut temel kurulumu değiştirmeden bu yan sürümü bulur. Başka sistemde `SUBTITLE_FFMPEG` ile libass destekli ikili verilebilir.

Bütün komutlarda `uv run --project <skill_dir> python <skill_dir>/scripts/` önekini kullan.

- `extract_subtitles.py --video film.mkv --output ham/` doğru dilde tek anlamlı tam metin parçayı seçer. Çoklu dosya için `--dir`; belirsizlikte rapora her adayın satır sayısı, zaman aralığı ve beş gerçek içerik örneği eklenir. Bunları inceleyip `--stream <index>` seçimini yalnız tek dosyada ver. ASS/SRT/mov_text/webvtt metin girdileri ASS olarak çıkarılır. Görüntü tabanlı altyazı OCR gerektirir.
- `verify_integrity.py --dir medya/ --output kontrol.json` beş noktada decode örnekler. Torrentin tam indiğini veya dosyanın bütünüyle sağlam olduğunu tek başına kanıtlamaz. İndirme tamamlanması için istemci durumu/hash denetimi gerekir.
- `mux_mkv.py --video film.mkv --ass film.tr.ass --context is/bolum01/context.json --output film.tr.mkv` mevcut parçaları korur, Türkçe altyazıyı tek varsayılan ve yapımın özgün sesini varsayılan yapar. Öncelik sırası: açık `--audio-lang`, anime için tek Japonca parça, yalnız `verified|single_stream` durum ve somut kanıt taşıyan bağlam dili, parçanın `original` bayrağı, tek mevcut ses. `unknown` durumundaki dil beyanı kullanılmaz. Birden çok ses kalır ve özgün dil belirlenemezse araç durur. Paketli Source Sans 3 Regular/Bold varsayılan eklenir; araç dosya adına değil OpenType içindeki gerçek aile/stil metadata'sına bakar. Özel fontlarda beklenen aile `--font-family` ile bağlanabilir. Çift girdi (dual-input) mimarisi kullanılır: AV1 video akışında temporal unit/show_frame=0 keyframe bayraklarının kaybolmaması ve siyah ekran oluşmaması için video akışı `-fflags +noparse+nofillin` ile eşlenir (`-map 0:v`); Opus vb. ses akışlarının zaman damgalarının (PTS) dondurulmaması ve ses kaybı yaşanmaması için ses, orijinal altyazı ve ekler normal ayrıştırıcılı ikinci girdiden (`-map 1:a -map 1:s? -map 1:t?`) eşlenir. Kaynak MKV'deki bütün attachment'lar korunur ve stream envanteriyle doğrulanır. Harici ASS gibi seyrek paketleri doğru serpiştirmek için `-max_interleave_delta 0` kullanılır. Özgün ses ve görüntü sıkıştırılmış yükleri SHA-256 ile karşılaştırılır; geç başlayan altyazının kap süresini uzatması medya bozulması sayılmaz.
- `verify_render_qa.py --video film.mkv --ass film.tr.ass --output goruntu/` gerçek FFmpeg/libass PNG örnekleri üretir. `--times 10.4 50.2`, `--fonts <dizin>` desteklenir. Araç her örnekte input-side seek ve özgün zaman damgalarıyla yalnız hedef çevresini çözer. Aynı seri/release/profil/typeset düzeninde tam görsel temel ilk işlenen bölümde en fazla dört amaçlı örnekle kurulur. Sonraki bölümlerde aynı imza ve risksiz teknik rapor varsa erken/orta/geç altyazı akışı görüntüsüz oynatıcı/metin sorgusuyla denetlenir; yalnız yeni stil/font, karmaşık tabela/karaoke, kesim birleşimi, glif/fallback uyarısı veya kullanıcı hatasında hedefli PNG açılır. Devralınmış temel güncel bölümün görüntüsünün incelendiği iddiası değildir. Film ve tekil yapım kendi temelini gerektirir. Hedef oynatıcı ve HDR renkleri ayrıca kontrol edilmedikçe doğrulanmış sayılmaz.
- `ab_compare.py --pipeline yeni.ass --baseline eski.ass --output kor.json --key gizli-esleme.json --seed 42` zaman kesişimine göre tekil eşler ve her çiftte kaynak sırasını rastgele gizler. İnceleyene yalnız `kor.json` verilir. Kimliği sonra aç. Sahne eşlemesinin doğruluğunu kontrol et; farklı satır bölünmesi eşleşmeyen replikler oluşturabilir.
- `analyze_audit.py --jobs-dir isler/` gerçek teknik raporları toplar; anlamsal kalite puanı üretmez.

## İçerik kesimi

Otomatik hassas sahne tespiti iddia edilmez. Kullanıcının açık talimatını politika kaydına, görüntü/ses/senaryodan gerçekten incelenen zaman aralıklarını `cuts` listesine yaz. Başlangıç şeması `resources/cut_plan_template.json` içindedir:

```json
{
  "policy": {
    "authorized": true,
    "requested_by": "user",
    "instruction": "Kullanıcının açık içerik filtreleme talimatı.",
    "source_reference": "Talimatın tarihi veya görev kaydı."
  },
  "cuts": [
    {
      "start": 12.5,
      "end": 15.2,
      "category": "öpüşme-sahnesi",
      "cut_reason": "Kullanıcının açık filtreleme kapsamına giriyor.",
      "evidence": "12,1–15,4 sn görüntü ve ses incelendi; istenen sahne bu aralıkta.",
      "reviewed_by": "ajan/model adı",
      "context_note": "Kaynak sahneye dayalı kısa bağlam."
    }
  ]
}
```

Önce `content_filter_pipeline.py --video film.mkv --cuts cuts.json` ile planı incele. Motor kesimin başlangıcını önceki, sonunu sonraki doğrulanmış anahtar kareye genişletir; fazladan kesilecek süreyi raporlar. Yakın kareye daraltıp istenmeyen içeriği bırakmaz. Sınırlar belirgin hikâye kaybı oluşturuyorsa planı yeniden değerlendir; kayıtlı yetki kapsamı dışında kesim kararı alma.

Uygulama: `content_filter_pipeline.py --video film.mkv --cuts cuts.json --subtitle film.tr.ass --job is/bolum01 --apply --output-video film.clean.mkv --output-ass film.clean.tr.ass`.

`--job` ve yetkili `policy` zarfı zorunludur; doğrudan video kesme yardımcısı üretimde kapalıdır. Kesimden sonra şu bilgiler hem `job/content_filter/cut-<hash>.json` içine hem de `~/Downloads/torrent/alyazılar/<eser>/content-filter--<hash>/` değişmez paketine yazılır: politika, talep edilen saniyeler, anahtar kareye göre uygulanan saniyeler, fazladan çıkarılan süre, tutulan parçalar, `category`, `cut_reason`, `evidence`, `reviewed_by`, `context_note`, kaynak/çıktı video ve altyazı hash'leri, süre/decode kontrolleri. Kanıt arşivi kurulamazsa hazırlanmış çıktı dosyaları yayımlanmış bırakılmaz. Merkezi arşiv büyük MKV'yi kopyalamaz. Sonradan finalize edilen altyazı paketi işteki bu kesim kayıtlarını da içerir.

- Negatif/ters/sonsuz aralıklar reddedilir; sırasız ve çakışan kesimler notlarıyla birlikte birleştirilir.
- Altyazı her tutulan parçayla kesiştirilir; kesimin iki yanında kalan metin korunur. Zaman kaydırma tek birleşmiş haritadan hesaplanır. Kesimin böldüğü süreye bağlı ASS efektleri önce ayrı düzenlenmelidir.
- Video/ses/font parçaları açıkça eşlenir. Gömülü metin altyazıları da aynı haritayla yeniden zamanlanıp ASS olarak eklenir; satırın kesim sonrasına taşan paket süresi korunmaz. Görüntü tabanlı gömülü altyazı varsa sessizce kaybetmek yerine işlem durur; metin alternatifi veya açık çıkarma kararı gerekir. Eski bölüm işaretleri yanlış zamanları taşımamak için kaldırılır; raporda belirtilir. Yeniden bölümleme ayrı işlemdir.
- Önce video yeniden kodlanmadan, bütün kaynak doğrulanmış anahtar karelerde bir kez bölünür; concat süreleri planlanan tutulan aralıklara sabitlenir. H.264/H.265 açık GOP veya B-kare yeniden sıralaması bir parçanın ya da birleştirilmiş tabanın görüntü zaman aralığını 0,1 sn dışına çıkarırsa video aynı codec'in kayıpsız kipinde yeniden kodlanır (`libx264 crf=0` veya `libx265 lossless=1`); kesilmiş ses paketleri kopyalanır. Kullanılan yol ve tetikleyen sapma rapora yazılır. Son görüntü zaman aralığı yine 0,1 sn sınırını aşarsa çıktı yayımlanmaz. Kayıpsız yeniden kodlama bit-akışı kimliğini korumaz ve HDR/Dolby Vision metadata sadakatini kanıtlamaz.
- Kesim raporundaki birleşimleri görüntü/sesle kontrol et. `returncode=0` olan FFmpeg stderr uyarıları raporda saklanır fakat tek başına decode hatası sayılmaz; gerçek hata kodu işlemi durdurur. Sınırlı teknik kontrolden sonra durum `cut_needs_playback_review` olur. Kısa PNG örnekleri ses senkronunun yerine geçmez. HDR/Dolby Vision metadata sadakati ayrıca incelenmedikçe garanti edilmez.

FFmpeg stream-copy aramada hedefin öncesindeki paketleri tutabilir: https://ffmpeg.org/ffmpeg.html#Main-options . Bu nedenle keyframe hizalaması, süre kontrolü ve oynatma incelemesi birlikte kullanılır.

## 2.3.1 bütünlük sınırları

Kaynak dosya ve rapor hedefleri ayrı, kullanılmamış yollar olmalıdır. Bütünlük, çıkarma ve toplama komutları mevcut raporu da ezmez. Başarılı decode stderr uyarıları ayrı kaydedilir; bunların varlığı tek başına hata kodu değildir. Görüntü zaman aralığı ve ses/görüntü yükleri ayrıca kontrol edilir.

Attachment parçaları zaman çizelgesi üzerinde bölünmez: son remux sırasında özgün MKV'den bir kez eşlenir. Açık GOP fallback'i hem parça sapmasını hem birleştirilmiş tabanın sapmasını değerlendirir. Kayıpsız video kodlama öncesi/sonrası ses yük hash'leri ve son altyazı remux'u öncesi/sonrası bütün ses/görüntü yük hash'leri kaydedilir. Video bit-akışı kimliği ve HDR sadakati iddia edilmez.

Üretim kesimi yalnız `sanitize_movie` / `--apply` akışından yapılır. `render_cut_plan` ve `lossless_cut_video` doğrudan çıktı yayımlamaz. `_render_cut_plan` dahili uygulamadır; Python modülü aynı dosya izinlerine sahip saldırgana karşı bir güvenlik sandbox'ı değildir. Hazırlanmış iş yalnız iki dosya adı ile değil, kaynak kopyası/hash'i, profil ve bağlam doğrulamasıyla denetlenir.

Kesim arşivi tamamlanmadan yerel kanıt/çıktı yayımlanmaz. Final altyazı arşivi tamamlanmadan final ASS/QA yayımlanmaz. Olağan yakalanan hatalarda yeni dosyalar geri alınır; bu, güç kesintisine karşı dosya sistemi çapında ACID veya WORM garantisi değildir. Kaynak/kanıt dosyalarını değiştirebilen kişi hash manifestini de yeniden yazabilir; imzalı köken güvencesi ayrıca gerekir.

Ortak kurulum doğrulanmış Source Sans 3 Regular/Bold font ikililerini içerir. `resources/fonts/README.md` dosya hash'lerini ve gerekirse özgün 2.3.0 paketinden ağsız geri yükleme komutunu kaydeder. Paketli dosya adları ve iç metadata ayrıca doğrulanır; sessiz font değişimi yapılmaz.
