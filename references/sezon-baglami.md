# Sezon bağlamı: tek okuma, bölüm başına güvenli görünüm

Bu belge, film/dizi/anime çevirisinde sezonun tamamını bir kez okuyan **Sezon Bağlam Ajanı**nın görev sözleşmesidir. Amaç özet çıkarmak değil; sonraki çevirmen ve reviewer ajanlarının doğru, tutarlı ve spoiler sızdırmayan kararlar verebilmesi için kaynak-temelli çalışma hafızası üretmektir.

## Temel ayrım

İki farklı bağlam türü vardır ve birbirine karıştırılmaz:

1. **`season_context.json`**: Sezonun bütün kaynak altyazıları bir kez okunarak, çeviri başlamadan önce üretilen ve kaynak analizi olarak sabitlenen bağlamdır. Gelecek bölümleri bilir; bu nedenle çevirmenlere doğrudan verilmez.
2. **`series_context.json`**: Final + bağımsız review sonrasında onaylanan Türkçe terim, hitap, ses ve benzeri çeviri kararlarının hash-zincirli defteridir. Bölüm bölüm gelişir.

Sezon bağlamı kaynak gerçeğini; seri bağlamı onaylanmış Türkçe kararları temsil eder.

## Sezon Bağlam Ajanının girdisi

Ajan, `season_context.py prepare-pack` ile üretilmiş `season_reading_pack.json` dosyasını okur. Bu paket tam ASS biçim gürültüsü yerine her olay için şu bilgileri taşır:

- bölüm kimliği,
- kaynak satır kimliği,
- başlangıç/bitiş zamanı,
- diyalog/tabela/karaoke türü,
- varsa ASS `Name`/speaker alanı,
- stil adı,
- görünür kaynak metin,
- bölüm kaynak SHA-256 değeri.

Ajan medya veya dış kaynak kullanacaksa bunu ayrıca açıkça dayanaklandırır; kaynakta bulunmayan bilgiyi tahmin ederek kesin gerçek gibi yazmaz.

## Tek görev

Ajan bütün sezonu **bir kez** okur ve tek bir `season_context.json` üretir. Dosyanın birden çok bölüm/alan içermesi ikinci ajan gerektirmez. Ayrı ikinci bağlam ajanı yalnız şu durumlarda açılır:

- kaynak sezon tek bağlam penceresine veya platform çalışma sınırına sığmıyorsa,
- ilk bağlam ajanı belirli bir bölüm/aralık için çözülemeyen belirsizlik bildiriyorsa,
- kullanıcı açıkça bağımsız ikinci bağlam doğrulaması istiyorsa.

İkinci ajan normal durumda bütün sezonu tekrar okumaz; yalnız problemli kapsamı ve gerekli kanıtı inceler.

## Üretilecek alanlar

### `characters`

Yalnız çeviriyi etkileyen karakter bilgileri:

- kanonik ad,
- alias/lakap,
- çevirmenin karakter kimliğini güvenle görebileceği ilk bölüm (`visible_from`),
- çeviriye doğrudan yarayan kısa yönlendirme,
- kaynak satır kanıtları.

Biyografi, görünüş veya çeviriyi etkilemeyen lore doldurulmaz.

### `relationships`

İlişkiler **yönlüdür**: `A → B` ile `B → A` aynı kayıt değildir. Her kayıtta:

- ilişki açıklaması,
- kaynakta kullanılan hitap biçimleri,
- Türkçe açısından uygulanacak yönlendirme,
- geçerli olduğu bölüm aralığı,
- kaynak kanıtı bulunur.

İlişki veya hitap sezon içinde değişiyorsa yeni geçerlilik aralığıyla ayrı kayıt açılır. `valid_from` hikâyede ilişkinin gerçekte başladığı an değil, bu bilginin çevirmen için güvenle uygulanabildiği en erken bölüm olarak kullanılır; gizli ilişkiyi erken açıklama.

### `voices`

Karakter sesini edebî yorum olarak değil, doğrudan çeviri davranışı olarak tarif eder. Örnek: kısa ve doğrudan cümle, resmî kayıt, yoğun argo, eksiltili konuşma, duyguyu kaynakta yoksa açıklamama. Her kayıt geçerlilik aralığı ve kanıt taşır. Geçerlilik aralığı çevirmenin güvenle kullanabileceği dönemdir; gelecekte açığa çıkacak karakter bilgisini geçmiş bölüme geri sızdırma.

### `glossary`

Tekrarlanan özel ad, kurum, rütbe, büyü/yetenek, kurgusal kavram ve benzeri terimleri tutar. Her kayıt:

- kaynak biçim,
- tercih edilen Türkçe,
- aliaslar,
- kısa not,
- `locked|preferred|tentative` durumu,
- geçerlilik aralığı,
- kanıt taşır.

Sezonu baştan görmek terimin ilerideki anlamını doğru seçmeye yardımcı olabilir; ancak erken bölümde hikâye bilgisini açıklayan not çevirmen görünümüne sızdırılmaz.

### `recurring_elements`

Tekrarlayan espri, catchphrase, callback, motif, lakap ve kelime oyunlarını tutar. Çevirmenin aynı unsurun önceki kullanımlarını tutarlı sürdürmesini sağlar. Bölüm görünümüne yalnız o bölüm veya daha önceki gerçekleşmeler aktarılır.

### `episode_notes`

Her bölüm için yalnız çeviriyi etkileyen kısa bölüm bilgisi tutulur:

- ilişki/ton değişimi,
- önceki bölüme callback,
- riskli satır aralığı,
- o bölüme özgü çeviri talimatı,
- şarkı/karaoke notu.

Plot özeti yazmak amaç değildir. Çeviri kararını değiştirmeyen olay kaydedilmez.

### `guardrails`

Sezonu baştan okumanın spoiler avantajını güvenli biçimde kullanır. Ajan erken bölümde daha sonra açıklanan bir şeyi biliyorsa çevirmeni gelecekle bilgilendirmek yerine **koruma talimatı** yazar. Örnekler:

- belirsiz özneyi belirsiz bırak,
- kimliği erken açıklama,
- kaynakta cinsiyet belirsizse Türkçede ek bilgi ekleme,
- şakayı ilerideki açıklamayı ele vermeyecek biçimde koru.

Guardrail bölüm + satır kimliğine bağlıdır ve kaynak kanıtı taşır.

### `uncertainties`

Ajanın güvenilir biçimde çözemediği gerçek sorunlar burada tutulur. Her kayıtta soru, bölüm/satır kapsamı, çevirmenin güvenli davranış talimatı ve varsa sonradan doğrulanan çözüm bulunur. Sahte sayısal güven puanı kullanılmaz.

### `content_filter_candidates`

Kullanıcının kalıcı içerik filtresi açıksa Sezon Bağlam Ajanı, sezonu zaten okurken **yalnız metinden fark edilebilen** muhtemel öpüşme/cinsel yakınlık/romantik-cinsel yatak sahnelerini aday olarak işaretler. Her aday bölüm, satır kimlikleri, kategori, kısa gerekçe ve kaynak kanıtı taşır. Bu liste **kesim kararı değildir** ve boş olması bölümün temiz olduğunu kanıtlamaz; konuşmasız sahneler altyazıda görünmeyebilir.

Bu adaylar çevirmen bağlamına aktarılmaz. `derive-filter-review` komutu yalnız hedef bölümün adaylarını ve etkin filtre profilini ayrı, küçük bir inceleme paketi olarak üretir. İçerik İnceleme Ajanı bütün bölüm görüntüsünü ayrıca tarar, adayları görsel/ses bağlamında doğrular ve ancak bundan sonra kesim planı yazar.

## Kanıt kuralı

Önemli bağlam iddiaları `episode_id + source_sha256 + line_indices` ile bağlanır. Bağlam dosyası kutsal gerçek değil, doğrulanabilir çalışma hafızasıdır.

## Bölüm görünümü

`season_context.json` çevirmen tarafından doğrudan okunmaz. Şu komut spoiler-güvenli bölüm görünümü üretir:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py derive-episode \
  --context <season_context.json> --episode-id S01E07 --output <E07/context.json>
```

Araç yalnız o bölümde geçerli karakter, ilişki, ses, terim, geçmiş recurring öğeler, bölüm notları, guardrail ve belirsizlikleri aktarır. Gelecek bölüm occurrence'ları veya henüz geçerli olmayan ilişki/ses kayıtları aktarılmaz.

İçerik filtresi için ayrı küçük devir paketi:

```sh
uv run --project <skill_dir> python <skill_dir>/scripts/season_context.py derive-filter-review \
  --context <season_context.json> --episode-id S01E07 --output <E07/content-filter-review.json>
```

Bu paket sezonun diğer bağlamını taşımadan yalnız metin adaylarını, etkin filtre profilini ve bölüm kaynak hash'ini verir.

## Bağlam ajanının yapmayacağı işler

- altyazı çevirmez,
- ASS biçimlendirmesi düzeltmez,
- plot özeti/ansiklopedi üretmez,
- kaynakta olmayan karakter ilişkisi uydurmaz,
- bütün sezon bilgisini doğrudan bölüm çevirmenine vermez,
- `series_context.json` dosyasını doğrudan değiştirmez,
- kendi belirsizliğini kesin gerçek gibi yazmaz.
