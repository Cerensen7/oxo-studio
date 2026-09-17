#!/usr/bin/env python
"""
OXO Studio - ACE-Step 1.5 aday uretici.

Kusursuz parcaya tek seferde ulasilmiyor; cok aday uretip elemek gerekiyor.
Bu script adaylari uretir, temizlik zincirinden gecirir ve her birini
referans profiline gore olcup siralar.

acestep15/.venv ile calistirilir.
"""
import os, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE / "acestep15"
os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", str(BASE / "model15"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
sys.path.insert(0, str(REPO))

import argparse, json, random, subprocess, time

ADAY_DIR = BASE / "output" / "adaylar"
HAM_DIR = BASE / "output" / ".ham15"

# v1'den tasinan, olcumle dogrulanmis temizlik zinciri
TEMIZLIK = (
    "highpass=f=60:poles=2,highpass=f=60:poles=2,"
    "afftdn=nr=18:nf=-45:tn=1,"
    "lowpass=f=1500:poles=2,treble=g=-6:f=4000,"
    "alimiter=limit=0.95"
)

# v1 derslerinin hepsi burada: kisa, gurultu istemeyen, tek enstrumanli
TEMEL = "lo-fi hip hop, instrumental, clean studio recording, warm, mellow"

# v1'de olmayan imkan: istemedigimizi soyleyebiliyoruz
NEGATIF = (
    "noise, hiss, tape hiss, vinyl crackle, static, hum, "
    "dissonant, out of tune, wrong notes, atonal, "
    "harsh, bright, shrill, cluttered, busy, chaotic, "
    "vocals, singing, speech, distortion, clipping"
)

STILLER = [
    ("Rüyalı Piyano",     "soft felt piano",              "Am", 68),
    ("Jazzy Rhodes",      "gentle rhodes electric piano", "Dm", 70),
    ("Naylon Gitar",      "soft nylon string guitar",     "Em", 68),
    ("Vibrafon",          "warm vibraphone",              "Am", 66),
    ("Kahve Dükkânı",     "mellow wurlitzer",             "Gm", 72),
    ("Sordinli Trompet",  "muted trumpet, slow phrases",  "Dm", 70),
    ("Kontrbas & Fırça",  "upright bass, brushed drums",  "Am", 74),
]


def temizle(ham: Path, hedef: Path) -> bool:
    hedef.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(ham), "-af", TEMIZLIK,
         "-c:a", "flac", "-compression_level", "8", str(hedef)],
        capture_output=True, text=True, timeout=300)
    if r.returncode == 0 and hedef.exists():
        ham.unlink(missing_ok=True)
        return True
    print(f"  [!] temizlik basarisiz: {(r.stderr or '')[-160:]}")
    try: ham.replace(hedef.with_suffix(".wav"))
    except Exception: pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adet", type=int, default=7, help="stil basina aday sayisi")
    ap.add_argument("--sure", type=float, default=180.0)
    ap.add_argument("--adim", type=int, default=8, help="turbo icin 8 onerilir")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--stil", type=int, default=-1, help="-1 = tum stiller")
    args = ap.parse_args()

    ADAY_DIR.mkdir(parents=True, exist_ok=True)
    HAM_DIR.mkdir(parents=True, exist_ok=True)

    print("[*] Modeller yukleniyor (MLX / Apple Silicon)...")
    t0 = time.time()
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music

    dit = AceStepHandler()
    msg, ok = dit.initialize_service(
        project_root=str(REPO), config_path="acestep-v15-turbo",
        device="mps", use_mlx_dit=True)
    print(f"    DiT: {msg.splitlines()[0] if msg else ''} (ok={ok})")
    if not ok:
        sys.exit("DiT yuklenemedi")

    lm = LLMHandler()
    msg, ok = lm.initialize(
        checkpoint_dir=str(BASE / "model15"), lm_model_path="acestep-5Hz-lm-1.7B",
        backend="mlx", device="mps")
    print(f"    LM : {msg.splitlines()[0] if msg else ''} (ok={ok})")
    print(f"[*] Yukleme: {time.time()-t0:.0f} sn")

    stiller = STILLER if args.stil < 0 else [STILLER[args.stil % len(STILLER)]]
    kayit_yolu = BASE / "output" / "adaylar_kaydi.json"
    kayitlar = json.loads(kayit_yolu.read_text()) if kayit_yolu.exists() else []
    sayac = len(list(ADAY_DIR.glob("*.flac")))

    for ad, tag, ton, bpm in stiller:
        for n in range(args.adet):
            sayac += 1
            print(f"\n[{sayac}] {ad} · {ton} · {bpm} BPM")
            t = time.time()
            params = GenerationParams(
                caption=f"{TEMEL}, {tag}",
                lyrics="[Instrumental]",
                instrumental=True,
                keyscale=ton,
                bpm=bpm,
                timesignature="4",
                duration=args.sure,
                inference_steps=args.adim,
                shift=3.0,
                infer_method="ode",
                lm_negative_prompt=NEGATIF,
                use_cot_metas=True,
            )
            cfg = GenerationConfig(batch_size=args.batch, audio_format="flac",
                                   use_random_seed=True)
            try:
                sonuc = generate_music(dit, lm, params, cfg, save_dir=str(HAM_DIR))
            except Exception as e:
                print(f"  [!] uretim hatasi: {e}")
                continue
            if not getattr(sonuc, "success", False):
                print(f"  [!] basarisiz: {getattr(sonuc,'message','')}")
                continue

            gecen = time.time() - t
            for i, a in enumerate(sonuc.audios):
                ham = Path(a["path"])
                hedef = ADAY_DIR / f"aday_{sayac:03d}{chr(97+i) if args.batch>1 else ''}.flac"
                temizle(ham, hedef)
                kayitlar.append({
                    "dosya": hedef.name, "stil": ad, "ton": ton, "bpm": bpm,
                    "caption": f"{TEMEL}, {tag}", "adim": args.adim,
                    "sure_sn": args.sure, "uretim_sn": round(gecen/len(sonuc.audios), 1),
                })
                print(f"  -> {hedef.name}")
            kayit_yolu.write_text(json.dumps(kayitlar, ensure_ascii=False, indent=2))
            print(f"  sure: {gecen/60:.1f} dk ({len(sonuc.audios)} aday)")

    print(f"\n[+] Bitti. Adaylar: {ADAY_DIR}")


if __name__ == "__main__":
    main()
