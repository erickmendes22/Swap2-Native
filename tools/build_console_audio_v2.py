"""Build the original, short and dry Console UI sound revision (no network/API)."""
from pathlib import Path
import json
import math
import wave
import numpy as np

RATE = 48000
OUT = Path(__file__).resolve().parents[1] / 'assets/artwork/swap2-native/console-v4/audio-v2'

def tone(hz, seconds, decay=0.035):
    t = np.arange(round(seconds * RATE)) / RATE
    envelope = (1 - np.exp(-t / .002)) * np.exp(-t / decay)
    signal = np.sin(2 * np.pi * hz * t) + .035 * np.sin(4 * np.pi * hz * t)
    result = signal * envelope
    n = min(192, len(result) // 4)
    result[-n:] *= np.linspace(1, 0, n)
    return result

def compose(seconds, notes):
    result = np.zeros(round(seconds * RATE))
    for start, frequency, duration, amplitude, decay in notes:
        signal = tone(frequency, duration, decay) * amplitude
        begin = round(start * RATE)
        stop = min(begin + len(signal), len(result))
        result[begin:stop] += signal[:stop - begin]
    result[0] = result[-1] = 0
    return result

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # One shared instrument and a limited register keep the cues in one sound family.
    cues = {
        'focus': (.045, [(0, 720, .04, 1, .006)]),
        'confirm': (.145, [(0, 540, .08, .8, .018), (.048, 720, .09, 1, .023)]),
        'back': (.110, [(0, 600, .055, .7, .014), (.036, 450, .07, .8, .019)]),
        'panel_open': (.095, [(0, 430, .06, .65, .016), (.028, 540, .06, .8, .016)]),
        'panel_close': (.085, [(0, 500, .05, .65, .014), (.025, 400, .055, .75, .015)]),
        'ready': (.330, [(0, 540, .13, .75, .035), (.08, 675, .14, .8, .04), (.16, 810, .16, .8, .045)]),
        'error': (.180, [(0, 300, .075, .7, .025), (.085, 280, .085, .7, .026)]),
        'launch': (.230, [(0, 450, .07, .7, .018), (.045, 600, .10, .7, .026), (.105, 750, .12, .8, .03)]),
        'boot': (.900, [(.08, 360, .04, .28, .008), (.30, 450, .04, .28, .008),
                        (.43, 540, .22, .65, .055), (.55, 720, .28, .65, .065)]),
    }
    manifest = {'version': 2, 'provider': 'Original deterministic synthesis',
                'supersedes': '../audio/delivery.json',
                'description': 'Short, dry, rounded sine transients. No reverb, noise, voices, loops or external recordings.',
                'audition_status': 'Revision after user feedback; subjective approval pending.', 'sounds': {}}
    for name, (seconds, notes) in cues.items():
        data = compose(seconds, notes)
        target_db = -18 if name == 'focus' else -12 if name in ('boot', 'ready', 'launch') else -15
        data *= 10 ** (target_db / 20) / np.max(np.abs(data))
        pcm = np.round(data * 32767).astype('<i2')
        path = OUT / f's2_{name}.wav'
        with wave.open(str(path), 'wb') as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(RATE)
            writer.writeframes(pcm.tobytes())
        manifest['sounds'][name] = {'file': path.name, 'duration_ms': round(seconds * 1000),
            'sample_rate': RATE, 'channels': 1, 'bits': 16, 'peak_dbfs': target_db,
            'rms_dbfs': round(20 * math.log10(float(np.sqrt(np.mean(data * data)))) , 2),
            'gain': .30 if name == 'focus' else .50, 'loop': False}
        print(f'{name}: {round(seconds * 1000)} ms, {target_db} dBFS')
    (OUT / 'delivery.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
