#!/usr/bin/env python3
"""Medya dosyalarında örnek noktalarda decode hatası arar; tam indirme/bütünlük kanıtı değildir.

Torrent istemcilerinin first/last-piece önceliklendirme tuzağını aşmak için
dosyanın %10, %30, %50, %70, %90 noktalarından 5'er saniyelik dilim decode eder.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from subtitle_core import write_json


def get_duration(filepath: str) -> float | None:
    """ffprobe ile dosyanın toplam süresini saniye olarak döndürür."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", filepath],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def check_ebml_header(filepath: str) -> bool:
    """Dosyanın ilk 4 baytının geçerli Matroska EBML header olup olmadığını kontrol eder."""
    with open(filepath, "rb") as f:
        return f.read(4) == b"\x1a\x45\xdf\xa3"


def multi_point_decode(filepath: str, sample_points: list[float] = None) -> dict:
    """Dosyanın birden fazla noktasından 5 saniyelik decode testi yapar."""
    duration = get_duration(filepath)
    results = {"file": os.path.basename(filepath), "duration": duration, "samples": [], "passed": False, "scope": "sampled_decode_only"}

    if duration is None or duration < 1:
        results["error"] = "Süre alınamadı veya dosya çok kısa"
        return results

    if sample_points is None:
        sample_points = [0.10, 0.30, 0.50, 0.70, 0.90]

    all_ok = True
    for pct in sample_points:
        t = duration * pct
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-ss", str(t), "-i", filepath, "-t", "5", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        ok = r.returncode == 0
        sample = {"time": round(t, 1), "percent": f"{pct*100:.0f}%", "ok": ok}
        if ok and r.stderr.strip():
            sample["warning"] = r.stderr.strip()[:2000]
        if not ok:
            sample["error"] = r.stderr.strip()[:200]
            all_ok = False
        results["samples"].append(sample)

    results["passed"] = all_ok
    return results


def main():
    parser = argparse.ArgumentParser(description="MKV dosya bütünlük doğrulayıcı")
    parser.add_argument("--dir", required=True, help="MKV dosyalarının bulunduğu üst dizin")
    parser.add_argument("--output", default=None, help="JSON rapor çıktı dosyası")
    args = parser.parse_args()
    if args.output and (Path(args.output).exists() or Path(args.output).is_symlink()):
        parser.error('Choose an unused report destination; source files are immutable')

    mkv_files = sorted(str(p) for p in __import__("pathlib").Path(args.dir).rglob("*") if p.is_file() and p.suffix.lower() in (".mkv", ".mp4", ".m4v", ".mov"))
    # Extras klasörlerini hariç tut
    mkv_files = [f for f in mkv_files if "/Extras/" not in f and "/extras/" not in f]

    if not mkv_files:
        print(f"❌ {args.dir} altında MKV dosyası bulunamadı.")
        sys.exit(1)

    print(f"🔍 {len(mkv_files)} MKV dosyası taranıyor...\n")
    results = []
    failed_count = 0

    for f in mkv_files:
        basename = os.path.basename(f)

        # EBML header kontrolü
        if f.lower().endswith(".mkv") and not check_ebml_header(f):
            print(f"  ❌ {basename} — EBML header geçersiz (dosya henüz indirilmemiş olabilir)")
            results.append({"file": basename, "passed": False, "error": "EBML header yok"})
            failed_count += 1
            continue

        # Çok noktalı decode testi
        r = multi_point_decode(f)
        results.append(r)

        if r["passed"]:
            print(f"  ✅ {basename} — Tüm noktalar başarılı ({r['duration']:.0f}s)")
        else:
            failed_count += 1
            failed_pcts = [s["percent"] for s in r["samples"] if not s["ok"]]
            print(f"  ❌ {basename} — Başarısız noktalar: {', '.join(failed_pcts)}")

    print(f"\n{'═'*60}")
    if failed_count == 0:
        print(f"✅ Tüm {len(mkv_files)} dosya örneklenen decode noktalarını geçti (tam dosya doğrulanmadı).")
    else:
        print(f"❌ {failed_count}/{len(mkv_files)} dosya başarısız — torrent indirmesini kontrol edin.")

    if args.output:
        write_json(args.output, results, overwrite=False)
        print(f"📄 Rapor: {args.output}")

    sys.exit(1 if failed_count else 0)

if __name__ == "__main__":
    main()
