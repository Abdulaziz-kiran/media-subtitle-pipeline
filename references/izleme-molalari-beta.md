# İzleme molaları — beta.1

Varsayılan kullanıcı tercihi `resources/preferences.json` içindeki `auto_viewing_breaks:true` alanıdır. Orkestratör bunu yalnız video mevcut olduğunda okur; altyazı görsel QA'sını açmaz. `run_pipeline.py analyze-viewing-breaks --job <iş>`, aynı kaynak video, altyazı hash'i ve analiz parametreleri için işteki aday analizini doğrulayarak yeniden kullanır; eşleşen dosya yoksa bir kez üretir. Video yoksa sonuç `no_media`/`not_assessed` kalır. Adayların görüntü, ses ve yakın diyalog incelemesinden sonra güvenli durak yoksa `reviewed_no_suitable` sonucu; source/subtitle hash'leri, analiz parametreleri, aday analiz dosyası hash'i, gerçek inceleme nedeni ve inceleyeni taşır. Teknik keyframe/silence hatası bu sonuçla karıştırılmaz.

Bu isteğe bağlı özellik, uzun film veya yaklaşık 20 dakikalık anime bölümünü birden fazla oturumda izlemek için uygun durak adayları çıkarır ve onaylanan noktaları yeni bir MKV'ye bölüm işareti olarak ekler. Kaynak video değişmez. Video yeniden kodlanmaz; bütün stream ve attachment envanteri ile ses/görüntü yük hash'leri doğrulanır.

Bu beta **Astra Pro 2.3.1 denetimine dahil değildir**. Araç sessizlik, altyazı boşluğu, hedef süreye yakınlık ve doğrulanmış video anahtar karelerini ölçer. Bunlar hikâyenin uygun yerde durduğunu kanıtlamaz. Ajan adayın çevresindeki görüntüyü, sesi ve diyaloğu incelemeden `review_status:"reviewed"` veya `story_safe:true` yazmaz.

## Aday çıkarma

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/viewing_breaks_beta.py analyze \
  --video film.mkv --subtitle film.en.ass --output film.break-candidates.json
```

Varsayılan bölüm sayısı 30 dakikaya kadar olan içerikte ikidir. Daha uzun içerikte yaklaşık 45 dakikalık izleme oturumları hedeflenir. `--parts 2` ile sayı açıkça verilebilir. Her hedef çevresinde en çok beş anahtar kare adayı puanlanır; `--top-candidates` 1–10 aralığında değiştirilebilir.

Aktif ajan her aday için en az şunları inceler:

- Adaydan önceki ve sonraki diyalogların anlamı; cümlenin veya küçük olayın yarıda kalmaması.
- Görsel plan değişimi, kararma, mekân/zaman geçişi veya doğal sahne kapanışı.
- Sesin gerçekten durulması; yalnız düşük ses ölçümünü hikâye sonu saymama.
- Spoiler içermeyen genel bölüm başlığı. Varsayılan `İzleme Bölümü N` güvenlidir.
- Anime için eyecatch, reklam arası veya OP/ED çevresi; 20 dakikalık bölümde bile zorla tam orta noktayı seçmeme.

`film.break-candidates.json` içindeki `review_template` ayrı bir plan dosyasına kopyalanır. Seçilen her nokta şu yapıyı kullanır:

```json
{
  "beta_feature": "viewing_breaks",
  "beta_version": "viewing-breaks-beta.1",
  "source_sha256": "aday raporundaki gerçek hash",
  "review_status": "reviewed",
  "reviewed_by": "inceleyen ajan veya insan",
  "review_summary": "Bütün seçili noktaların görüntü, ses ve yakın diyalog bağlamı incelendi.",
  "breaks": [
    {
      "requested_time": 2680.0,
      "applied_time": 2678.4,
      "story_safe": true,
      "evidence": "Önceki küçük olay bitti; kararma ve sessizlikten sonra yeni mekân açılıyor.",
      "next_title": "İzleme Bölümü 2"
    }
  ]
}
```

`applied_time`, aday raporundaki doğrulanmış anahtar karelerden biri olmalıdır. Bölümler çok kısa kalıyorsa araç planı reddeder. `requested_time` ajanın tercih ettiği anlatı anını, `applied_time` ise videoya uygulanabilen gerçek sınırı korur.

## MKV bölüm işaretlerini ekleme

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/viewing_breaks_beta.py apply \
  --video film.mkv --plan film.break-plan.json --output film.oturumlar.mkv
```

Araç yeni MKV'ye `İzleme Bölümü 1`, `İzleme Bölümü 2` gibi bölümler ekler. Kaynakta zaten chapter varsa varsayılan olarak durur. Kaynağı değiştirmeyen yeni kopyada bunları bilerek değiştirmek için `--replace-existing-chapters` verilir; özgün chapter sayısı raporda saklanır.

Çıktının yanında `film.oturumlar.mkv.viewing-breaks.json` oluşur. Durum, hedef oynatıcıda gerçekten açılana kadar `beta_chapters_need_playback_review` kalır. Bu rapor seçilen saniyeleri, inceleme kanıtını, kaynak/çıktı hash'lerini, chapter sınırlarını ve stream/payload koruma kontrollerini içerir.

Bir altyazı işiyle birlikte yürütülüyorsa `--job is/bolum01` ver. Rapor `job/viewing_breaks/` içine de yazılır; sonraki final altyazı arşivine girer ve `resume-from-archive` ile yeni işe taşınır. Büyük MKV yine merkezi altyazı arşivine kopyalanmaz.

İlk beta gerçek video dosyasını ayrı parça dosyalarına kesmez; tek, kayıpsız stream-copy MKV içinde bölüm işaretleri üretir. Ayrı fiziksel dosya üretimi; mevcut chapter'ları taşıma, altyazı sınırları ve oynatıcı uyumu birlikte sınandıktan sonra sonraki beta adayıdır.
