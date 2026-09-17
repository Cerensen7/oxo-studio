#!/usr/bin/env python
"""
ACE-Step ile cozy lo-fi enstrumantal parca uretir.
Apple Silicon (MPS) icin float16'ya zorlanir; aksi halde pipeline
fp32'ye dusup 16 GB RAM'i doldurur.
"""
import os

# pipeline importundan ONCE ayarlanmali (pipeline_ace_step.py:133)
os.environ.setdefault("ACE_PIPELINE_DTYPE", "float16")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import argparse
import json
import random
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODEL_DIR = BASE / "model"
CIKTI_DIR = BASE / "output" / "parcalar"
KAYIT = BASE / "output" / "uretim_kaydi.json"

# Ortak iskelet: her parca ayni sonik dunyada kalsin diye sabit,
# varyasyon tag'leri ustune binsin diye kisa tutuldu.
TEMEL = (
    "lo-fi hip hop, chillhop, instrumental, no vocals, "
    "warm vinyl crackle, soft dusty drums, mellow sub bass, "
    "cozy, calm, relaxing, analog tape warmth, low pass filtered"
)

VARYASYONLAR = [
    "jazzy rhodes electric piano, laid back swing, 72 bpm",
    "soft nylon string guitar, gentle brushes, 68 bpm",
    "dreamy felt piano, sparse chords, 65 bpm",
    "muted trumpet, late night jazz club, 70 bpm",
    "warm analog synth pad, slow bloom, 66 bpm",
    "vibraphone melody, rainy window mood, 69 bpm",
    "dusty sampled piano loop, boom bap drums, 74 bpm",
    "soft flute, autumn afternoon, 71 bpm",
    "mellow electric guitar, reverb tails, 67 bpm",
    "lofi wurlitzer, coffee shop ambience, 73 bpm",
    "gentle harp arpeggio, floating, 64 bpm",
    "smooth saxophone, midnight city, 70 bpm",
    "toy piano, nostalgic music box, 66 bpm",
    "warm upright bass walking, jazzy drums, 75 bpm",
    "ambient pad with tape hiss, almost beatless, 62 bpm",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adet", type=int, default=15, help="uretilecek parca sayisi")
    ap.add_argument("--sure", type=float, default=240.0, help="parca suresi (saniye)")
    ap.add_argument("--adim", type=int, default=60, help="difuzyon adim sayisi")
    ap.add_argument("--baslangic", type=int, default=1, help="dosya numaralandirma baslangici")
    ap.add_argument("--seed", type=int, default=None, help="tekrarlanabilirlik icin ana seed")
    args = ap.parse_args()

    CIKTI_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    from acestep.pipeline_ace_step import ACEStepPipeline

    print(f"[*] Model dizini: {MODEL_DIR}")
    print("[*] Ilk calistirmada ~8.3 GB agirlik indirilecek, sabir.")
    pipe = ACEStepPipeline(
        checkpoint_dir=str(MODEL_DIR),
        dtype="float16",
        torch_compile=False,
        cpu_offload=False,
        overlapped_decode=False,
    )

    import torch
    print(f"[*] Cihaz: {pipe.device}  dtype: {pipe.dtype}")
    if pipe.device.type != "mps":
        print("[!] UYARI: MPS kullanilmiyor, uretim CPU'da cok yavas olacak.")

    rng = random.Random(args.seed)
    kayitlar = []
    if KAYIT.exists():
        kayitlar = json.loads(KAYIT.read_text())

    for i in range(args.adet):
        idx = args.baslangic + i
        varyasyon = VARYASYONLAR[(idx - 1) % len(VARYASYONLAR)]
        prompt = f"{TEMEL}, {varyasyon}"
        seed = rng.randint(1, 2**31 - 1)
        hedef = CIKTI_DIR / f"lofi_{idx:03d}.wav"

        if hedef.exists():
            print(f"[=] {hedef.name} zaten var, atlaniyor")
            continue

        print(f"\n[{i+1}/{args.adet}] {hedef.name}  seed={seed}")
        print(f"    {varyasyon}")
        t0 = time.time()
        pipe(
            format="wav",
            audio_duration=args.sure,
            prompt=prompt,
            lyrics="[instrumental]",
            infer_step=args.adim,
            guidance_scale=15.0,
            scheduler_type="euler",
            cfg_type="apg",
            omega_scale=10.0,
            manual_seeds=[seed],
            guidance_interval=0.5,
            guidance_interval_decay=0.0,
            min_guidance_scale=3.0,
            use_erg_tag=True,
            use_erg_lyric=False,
            use_erg_diffusion=True,
            save_path=str(hedef),
            batch_size=1,
        )
        gecen = time.time() - t0
        print(f"    bitti: {gecen/60:.1f} dk  ({gecen/args.sure:.2f}x gercek zaman)")

        kayitlar.append({
            "dosya": hedef.name,
            "prompt": prompt,
            "seed": seed,
            "sure_sn": args.sure,
            "adim": args.adim,
            "uretim_sn": round(gecen, 1),
        })
        KAYIT.write_text(json.dumps(kayitlar, ensure_ascii=False, indent=2))

    print(f"\n[+] Bitti. Parcalar: {CIKTI_DIR}")


if __name__ == "__main__":
    main()
