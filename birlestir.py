#!/usr/bin/env python3
"""
Uretilen lo-fi parcalari crossfade ile birlestirip uzun bir arka plan
mix'i cikarir. Dev WAV ara dosyasi olusturmaz, dogrudan MP3'e yazar.
"""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PARCA_DIR = BASE / "output" / "parcalar"
CIKTI_DIR = BASE / "output"


def sure_al(yol: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(yol)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def sirala(parcalar, sureler, hedef_sn, xfade, rng):
    """Hedef sureyi dolduracak kadar parca dizer; ayni parcayi arka arkaya koymaz."""
    dizi = []
    toplam = 0.0
    havuz = []
    son = None
    while toplam < hedef_sn:
        if not havuz:
            havuz = parcalar[:]
            rng.shuffle(havuz)
            if son is not None and len(havuz) > 1 and havuz[0] == son:
                havuz[0], havuz[1] = havuz[1], havuz[0]
        p = havuz.pop(0)
        dizi.append(p)
        toplam += sureler[p] if not dizi[:-1] else sureler[p] - xfade
        son = p
    return dizi, toplam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saat", type=float, default=3.0, help="hedef mix suresi (saat)")
    ap.add_argument("--xfade", type=float, default=6.0, help="crossfade suresi (saniye)")
    ap.add_argument("--cikti", type=str, default=None, help="cikti dosya adi")
    ap.add_argument("--bitrate", type=str, default="256k")
    ap.add_argument("--lufs", type=float, default=-16.0, help="hedef ses seviyesi (LUFS)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    parcalar = sorted(PARCA_DIR.glob("*.wav"))
    if not parcalar:
        sys.exit(f"HATA: {PARCA_DIR} icinde wav yok. Once uret.py calistir.")

    sureler = {p: sure_al(p) for p in parcalar}
    en_kisa = min(sureler.values())
    if args.xfade >= en_kisa / 2:
        sys.exit(f"HATA: crossfade ({args.xfade}s) en kisa parcaya ({en_kisa:.0f}s) gore fazla.")

    rng = random.Random(args.seed)
    hedef_sn = args.saat * 3600
    dizi, tahmini = sirala(parcalar, sureler, hedef_sn, args.xfade, rng)

    print(f"[*] {len(parcalar)} benzersiz parca, {len(dizi)} segment dizildi")
    print(f"[*] Tahmini sure: {tahmini/3600:.2f} saat  (crossfade {args.xfade}s)")

    cikti = CIKTI_DIR / (args.cikti or f"lofi_mix_{args.saat:g}saat.mp3")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-stats"]
    for p in dizi:
        cmd += ["-i", str(p)]

    # acrossfade zinciri: [0]+[1] -> [a1], [a1]+[2] -> [a2], ...
    adimlar = []
    onceki = "[0:a]"
    for i in range(1, len(dizi)):
        etiket = f"[a{i}]"
        adimlar.append(
            f"{onceki}[{i}:a]acrossfade=d={args.xfade}:c1=tri:c2=tri{etiket}"
        )
        onceki = etiket
    # tek parca varsa zincir bos kalir
    son = onceki if adimlar else "[0:a]"
    adimlar.append(f"{son}loudnorm=I={args.lufs}:TP=-1.5:LRA=11[out]")
    cmd += ["-filter_complex", ";".join(adimlar), "-map", "[out]",
            "-c:a", "libmp3lame", "-b:a", args.bitrate, "-ar", "44100", str(cikti)]

    print(f"[*] ffmpeg calisiyor -> {cikti.name}")
    subprocess.run(cmd, check=True)

    gercek = sure_al(cikti)
    print(f"\n[+] Bitti: {cikti}")
    print(f"    Sure: {gercek/3600:.2f} saat   Boyut: {cikti.stat().st_size/1e6:.0f} MB")

    (CIKTI_DIR / "mix_sirasi.json").write_text(json.dumps(
        {"cikti": cikti.name, "xfade": args.xfade,
         "sira": [p.name for p in dizi]}, indent=2))


if __name__ == "__main__":
    main()
