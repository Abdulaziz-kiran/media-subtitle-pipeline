# Skill Bakım Notları — Codex / Antigravity Ajan İçin

Bu dosya, media-subtitle-pipeline skill'ine yapılan bakım düzeltmeleri ve açık kalan maddelerini izler. Codex veya başka bir ajan bu skill üzerinde çalışmaya başladığında önce bu notları okumalıdır.

Dosyanın kendisi motor çıktısı veya arşiv parçası değildir; salt bir geliştirici notudur.

---

## Son Düzeltmeler (2026-09-11, Antigravity oturumu)

### 1. Render regresyon testi: libass renderer çözümlemesi eklendi

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

**Durum:** Yazılmadı. Uygulamalı bir seri çevirisi sırasında somut deneyim edinildikten sonra yazılması daha doğru.

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

---

## Motor Sürümü

Güncel: **2.3.1**. Yukarıdaki düzeltmeler motor sürümünü değiştirmez — bunlar test ve belge bakımıdır.
