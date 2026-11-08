"""Generate the authorized Swap2-Native UI sound pack. Never writes API credentials."""
import argparse
import json
import os
from pathlib import Path
import requests

PACK = Path(__file__).resolve().parents[1] / 'assets/artwork/swap2-native/console-v4'
COMMON = ('Original premium handheld console UI sound, clean soft electronic timbre, intimate dry sound, '
          'gentle rounded attack, no speech, no music, no hiss or background, no recognizable existing console motif. ')
SOUNDS = [
    ('boot', 1.5, 'Two subtle interlocking tactile clicks at 0.15 and 0.42 seconds followed by a short warm two-note ascending glass-synth signature, settled by 1.2 seconds. Confident, understated.'),
    ('focus', 0.5, 'ONE very short quiet rounded tick with a tiny wood-and-sine texture at the start. Audible content approximately 70 milliseconds, then silence. Suitable for repeated menu navigation.'),
    ('confirm', 0.5, 'ONE soft affirmative click followed immediately by a tiny rising clear electronic tone. Audible content 160 milliseconds, then silence.'),
    ('back', 0.5, 'ONE soft lower descending electronic tap, short and gentle. Audible content approximately 130 milliseconds, then silence.'),
    ('panel_open', 0.5, 'ONE tiny airy soft sliding swish resolving in a warm tick, audible content 200 milliseconds, then silence. Very restrained menu panel opening.'),
    ('panel_close', 0.5, 'ONE tiny reverse airy soft sliding swish ending quietly, audible content 180 milliseconds, then silence. Very restrained menu panel closing.'),
    ('ready', 0.8, 'A small warm affirmative three-note glass-synth completion chime, calm and satisfying, never triumphant. Sound ends within 600 milliseconds, followed by silence.'),
    ('error', 0.6, 'A quiet friendly two-pulse low electronic notice, rounded and non-alarming. No harsh buzzer. Audible content about 260 milliseconds, then silence.'),
    ('launch', 0.8, 'ONE soft tactile confirm click followed by a short upward airy digital flourish, no dramatic sweep. Audible content 450 milliseconds, then silence.'),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=[x[0] for x in SOUNDS])
    parser.add_argument('--spec', type=Path, help='JSON prompts; outputs go beside this file.')
    args = parser.parse_args()
    key = os.environ.get('ELEVEN_LABS_API_KEY') or os.environ.get('ELEVENLABS_API_KEY')
    if not key:
        raise SystemExit('ElevenLabs API key is not set in the environment.')
    spec = json.loads(args.spec.read_text(encoding='utf-8')) if args.spec else None
    out = args.spec.resolve().parent if args.spec else PACK / 'audio'
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'generation.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'provider': 'ElevenLabs', 'model': spec['model_id'] if spec else 'eleven_text_to_sound_v2',
        'endpoint': 'https://api.elevenlabs.io/v1/sound-generation', 'sounds': {}}
    entries = [(s['id'], s['duration_seconds'], s['text']) for s in spec['sounds']] if spec else SOUNDS
    for name, duration, detail in entries:
        if args.only and name != args.only:
            continue
        target = out / f's2_{name}.mp3'
        if target.exists() and name in manifest['sounds']:
            print(f'{name}: already generated', flush=True)
            continue
        payload = {'text': detail if spec else COMMON + detail, 'duration_seconds': duration,
                   'prompt_influence': spec['prompt_influence'] if spec else 0.65,
                   'model_id': manifest['model'], 'loop': False}
        try:
            response = requests.post(manifest['endpoint'], params={'output_format': 'mp3_44100_128'},
                headers={'xi-api-key': key, 'Content-Type': 'application/json'}, json=payload, timeout=90)
        except requests.RequestException:
            raise SystemExit(f'{name}: network request failed; no automatic retry or duplicate billing.')
        if response.status_code != 200:
            try:
                detail = response.json().get('detail', {})
                code = detail.get('status', 'unknown') if isinstance(detail, dict) else 'request_rejected'
            except ValueError:
                code = 'unknown'
            raise SystemExit(f'{name}: ElevenLabs HTTP {response.status_code}, status {code}.')
        if 'audio' not in response.headers.get('Content-Type', '') or len(response.content) < 100:
            raise SystemExit(f'{name}: response was not a usable audio file.')
        target.write_bytes(response.content)
        manifest['sounds'][name] = {'file': target.name, 'request': payload,
            'request_id': response.headers.get('request-id'), 'bytes': len(response.content)}
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        print(f'{name}: saved {len(response.content)} bytes', flush=True)

if __name__ == '__main__':
    main()
