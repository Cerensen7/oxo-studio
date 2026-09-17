#!/usr/bin/env python
"""
OXO Studio - aday eleyici.

Uretilen adaylari referans lo-fi profiline gore olcup siralar.
Referans degerleri kullanicinin begendigi parcalardan olculdu.
Puan kotu olan adaylari isaretler; son karar kulaga aittir.
"""
import json, sys, warnings
from pathlib import Path
from collections import Counter
import numpy as np, librosa
warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
ADAY_DIR = BASE / "output" / "adaylar"

# Referans parcalardan olculen hedefler (README'deki tabloya bakiniz)
HEDEF = {
    "merkez":  (380, 800,  546),   # spektral merkez Hz  (alt, ust, ideal)
    "olay_sn": (1.5, 5.5,  3.59),  # saniyedeki olay
    "gezinme": (0.09, 0.30, 0.168),# tonnetz hareketi
    "ugultu":  (-99, 5.0,  -10),   # 20-60 Hz gurultu tabani dB
    "hisirti": (-99, -30,  -50),   # 8-16 kHz gurultu tabani dB
    "tepe_db": (-99, -0.5, -1.5),  # kirpilma emniyeti
}

MAJ = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
MIN = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])


def olc(yol: Path) -> dict:
    y, sr = librosa.load(str(yol), sr=22050, mono=True)
    S = np.abs(librosa.stft(y))
    ch = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=1024)

    N = 4096
    k = y[:len(y)//N*N].reshape(-1, N)
    rms = np.sqrt((k**2).mean(axis=1))
    sessiz = k[np.argsort(rms)[:max(1, len(rms)//20)]]
    sp = np.abs(np.fft.rfft(sessiz*np.hanning(N), axis=1)).mean(axis=0)
    f = np.fft.rfftfreq(N, 1/sr)
    bant = lambda a,z: float(20*np.log10(sp[(f>=a)&(f<z)].mean()+1e-12))

    return {
        "merkez":  float(librosa.feature.spectral_centroid(S=S, sr=sr).mean()),
        "olay_sn": len(librosa.onset.onset_detect(y=y, sr=sr, units="time"))/(len(y)/sr),
        "gezinme": float(np.mean(np.std(librosa.feature.tonnetz(chroma=ch), axis=1))),
        "ugultu":  bant(20, 60),
        "hisirti": bant(8000, min(16000, sr//2-1)),
        "tepe_db": float(20*np.log10(np.abs(y).max()+1e-9)),
        "sure":    len(y)/sr,
    }


def puanla(m: dict):
    """0-100 puan ve uyarilar. Hedef araligin disi agir cezalandirilir."""
    puan, uyarilar = 100.0, []
    etiket = {"merkez":"ton rengi", "olay_sn":"yogunluk", "gezinme":"armonik hareket",
              "ugultu":"uğultu", "hisirti":"hışırtı", "tepe_db":"tepe seviye"}
    for ad, (alt, ust, ideal) in HEDEF.items():
        v = m[ad]
        if v < alt or v > ust:
            puan -= 25
            uyarilar.append(f"{etiket[ad]} aralık dışı ({v:.1f})")
        else:
            # ideale uzaklik hafif ceza
            genislik = max(ust-ideal, ideal-alt) or 1
            puan -= min(12, abs(v-ideal)/genislik*12)
    return max(0, round(puan, 1)), uyarilar


def main():
    dosyalar = sorted(ADAY_DIR.glob("*.flac")) + sorted(ADAY_DIR.glob("*.wav"))
    if not dosyalar:
        sys.exit(f"HATA: {ADAY_DIR} bos. Once uret15.py calistir.")

    sonuc = []
    for d in dosyalar:
        m = olc(d)
        p, u = puanla(m)
        sonuc.append({"dosya": d.name, "puan": p, "uyarilar": u, **{k: round(v,3) for k,v in m.items()}})

    sonuc.sort(key=lambda r: -r["puan"])
    (BASE/"output"/"eleme_raporu.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=2))

    print(f"{'#':>3} {'dosya':<20}{'puan':>6}{'merkez':>8}{'olay':>7}{'gezinme':>9}{'hisirti':>9}  uyarilar")
    print("-"*100)
    for i, r in enumerate(sonuc, 1):
        u = ", ".join(r["uyarilar"])[:38]
        print(f"{i:>3} {r['dosya']:<20}{r['puan']:>6.1f}{r['merkez']:>8.0f}"
              f"{r['olay_sn']:>7.2f}{r['gezinme']:>9.3f}{r['hisirti']:>9.1f}  {u}")
    print()
    temiz = [r for r in sonuc if not r["uyarilar"]]
    print(f"Uyarisiz aday: {len(temiz)} / {len(sonuc)}")
    if temiz:
        print("En iyi 7:", ", ".join(r["dosya"] for r in temiz[:7]))


if __name__ == "__main__":
    main()
