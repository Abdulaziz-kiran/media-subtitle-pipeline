# Antigravity / Codex + Antigravity işçi profili

Bu belge model adını her prompta tekrar tekrar gömmek yerine rol bazlı iki çalışma katmanını kullanır. Kaynak ayar `resources/orchestration_profile.json` dosyasıdır.

## Antigravity doğrudan kullanım

Mevcut kişisel çalışma profilinde ana koordinatör genellikle **Gemini 3.8 Flash Medium** seçilir. Bu durumda:

- `Model: "inherit"` → orta eforlu işçi katmanı,
- `Model: "flash"` → yüksek eforlu Flash işçi katmanı

olarak kullanılır.

Rol eşlemesi:

| Rol | Model seçici |
|---|---|
| Hazırlık/operasyon | `inherit` |
| Sezon bağlamı | `flash` |
| Çevirmen | `inherit` |
| Reviewer | `flash` |
| Repair | `inherit` |
| Adjudicator | `flash` |

Bu eşleme, platformun bugünkü davranışını kullanan operasyon profilidir; gerçek çalışma modeli/eforu telemetri yoksa kriptografik olarak doğrulanmış sayılmaz.

Ana koordinatör başka bir model/eforla çalıştırılıyorsa `inherit` artık aynı anlama gelmeyebilir. Bu durumda kullanıcı veya orkestratör çalışma başında profili açıkça uyarlamalıdır; skill sessizce farklı kalite katmanı varsaymaz.

## Codex orkestratör + Antigravity işçileri

Codex ana koordinatörünün modeli/eforu kullanıcı seçer. Altyazı işçileri yine `agy`/Antigravity üzerinden Gemini 3.8 Flash ailesiyle çalıştırılabilir. Hedef eforlar:

- preparation: low,
- season_context: high,
- translator: medium,
- reviewer: high,
- repair: medium,
- adjudicator: high.

Codex, alt işçiye tam sohbet geçmişini aktarmamalı; yalnız rol, dosya yolu, atanmış kapsam ve gerekli komutları vermelidir.

## Örnek sezon bağlam çağrısı

Season Context ajanına tam sezon kaynak paketini ver:

```text
Rol: Season Context
Model katmanı: flash
Girdi: <season>/season_reading_pack.json
Görev: references/sezon-baglami.md sözleşmesine göre bütün sezonu bir kez analiz et ve <season>/season_context.json yaz.
Sonra scripts/season_context.py validate --context <season_context.json> çalıştır.
Serbest metin sezon özeti döndürme; koordinatöre yalnız doğrulama sonucu/hash dön.
```

## Örnek bölüm çevirmeni

```text
Rol: Translator S01E07
Model katmanı: inherit
İş klasörü: <work>/S01E07
Görev:
1. context.json, varsa series_context.json ve profile.json oku.
2. Yalnız atanmış requests/batch-*.json batch'lerini sırayla çevir.
3. ID/hash sözleşmesini koru; kaynak metinden fuzzy eşleştirme yapma.
4. receipt --stage translation çalıştır.
5. Koordinatöre replik/log değil yalnız kısa makbuz dön.
```

## Örnek reviewer

```text
Rol: Reviewer S01E07
Model katmanı: flash
İş klasörü: <work>/S01E07
Görev:
1. Kaynak ve birleşmiş adayı satır satır karşılaştır.
2. Anlam, olumsuzluk, kişi/iyelik, hitap, terim, ton, ima, eksik/ek bilgi ve biçim hatalarını ara.
3. Sorun varsa issues.json yaz; çeviriyi topluca yeniden yazma.
4. Sorun yoksa review.json + review receipt üret.
```

## Repair

```text
Rol: Repair S01E07
Model katmanı: inherit
Görev: reviewer issues.json içinde işaretlenen satırları gerekli yakın bağlamla düzelt; işaretlenmemiş satırlara stil rötuşu yapma. Adayı yeniden kur ve reviewer'a geri ver.
```
