# Paketli fontlar

Ortak skill kurulumu aşağıdaki doğrulanmış fontları içerir:

- `SourceSans3-Regular.otf`: `08df266400933d3178d081a45f94a08814c3e55b4b7dd2e0ff69cb1329f13ab6`
- `SourceSans3-Bold.otf`: `7776ddb9f3eb58683e59f28d558d8896b768c2d0c80799fb3f1c56c54dfd98c9`

`mux_mkv.py` dosya adına güvenmez; OpenType aile ve stil metadata'sını da doğrular. Fontlardan biri kaybolur veya değişirse, kullanıcının özgün ve SHA-256 değeri doğrulanan 2.3.0 paketinden ağ kullanmadan geri yüklenebilir:

```sh
python3 scripts/install_original_fonts.py --original-zip /path/to/media-subtitle-pipeline-v2.3.0-astra-pro-final.zip
```

Yükleyici farklı mevcut bir fontu ezmez.
