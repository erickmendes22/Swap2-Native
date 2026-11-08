"""Generate the original, quiet launcher tap (PCM16 mono, no external services)."""
from pathlib import Path
import math
import struct
import wave

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "android/app/src/main/res/raw/s2_tap.wav"
out.parent.mkdir(parents=True, exist_ok=True)
rate, seconds = 24000, 0.075
samples = []
for i in range(round(rate * seconds)):
    t = i / rate
    envelope = math.sin(math.pi * t / seconds) ** 2 * math.exp(-t * 45)
    tone = math.sin(2 * math.pi * 920 * t) + 0.25 * math.sin(2 * math.pi * 1380 * t)
    samples.append(round(0.35 * 32767 * envelope * tone))
with wave.open(str(out), "wb") as wav:
    wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
print(f"Generated {out.relative_to(ROOT)} ({seconds * 1000:.0f} ms)")
