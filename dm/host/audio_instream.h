// The host's microphone for nn::audio input streams (Switch 2 SDKs, InputStreamType): a capture that produces silent frames in real time at the stream's rate, as the
// console's built-in microphone would produce frames in a quiet room. The game reads them with ReadInputStream; what it does not read within the stream's capacity is lost
// (the oldest first, as a capture ring the system keeps writing). Pure (no HLE dependency) so dm/host/tests/t_audio_instream.c tests it; hle_audio.c keys one per guest
// InputStreamType and serializes the calls. A real microphone (AAudio on Android) would replace only is_read's zero fill.
#pragma once
#include <stdint.h>
#include <string.h>

enum { IS_CLOSED = 0, IS_STOPPED = 1, IS_STARTED = 2 };       // nn::audio::InputStreamState: GetInputStreamState answers 0 for a type that never opened (sdk+0x1f6020)
typedef struct { int32_t format, channels, rate; } is_format;   // nn::audio::StreamFormat, 12 bytes (the SDK's InputStreamImpl keeps it at +0x114, GetFormat sdk+0x1f6fb0)
typedef struct {
    int state;                  // IS_*
    is_format fmt;
    int capacity;               // frames the stream holds (OpenInputStream's last argument; Zelda: Ocarina of Time asks 4800, 100 ms at 48 kHz)
    float gain;                 // SetInputStreamGain's value, read back by GetInputStreamGain (a silent capture has nothing to scale)
    uint64_t t0;                // host time (ns) the stream last started; frames are produced from here while it is started
    uint64_t base;              // frames produced before t0 (earlier started spans)
    uint64_t taken;             // frames read, purged or lost
    uint64_t lost;              // frames lost because they were not read within the capacity
    const is_format *fmt_ref;   // (hle_audio.c, set after is_open) the copy of fmt that GetInputStreamFormat returns: in the game's work buffer, which outlives the close
} instream;

// bytes per sample of nn::audio::SampleFormat 1..5 (PcmInt8, PcmInt16, PcmInt24, PcmInt32, PcmFloat; IsVirtualInputDeviceStreamFormatSupported takes only these, sdk+0x1f5e10); 0 otherwise
static inline int is_sample_bytes(int32_t f) { return f == 1 ? 1 : f == 2 ? 2 : f == 3 ? 3 : f == 4 || f == 5 ? 4 : 0; }
static inline int is_format_ok(const is_format *f) { return f && is_sample_bytes(f->format) && f->channels >= 1 && f->channels <= 8 && f->rate > 0 && f->rate <= 192000; }
// frames in ns nanoseconds at rate (split so that a long run cannot overflow)
static inline uint64_t is_frames(uint64_t ns, int32_t rate) { return ns / 1000000000u * (uint64_t)rate + ns % 1000000000u * (uint64_t)rate / 1000000000u; }
static inline uint64_t is_produced(const instream *s, uint64_t now) { return s->base + (s->state == IS_STARTED && now > s->t0 ? is_frames(now - s->t0, s->fmt.rate) : 0); }

// frames captured and not yet read (GetInputStreamFilledFrameCount); frames beyond the capacity are lost, the oldest first
static inline int is_filled(instream *s, uint64_t now) {
    if (s->state == IS_CLOSED) return 0;
    uint64_t p = is_produced(s, now), cap = (uint64_t)s->capacity;
    if (p - s->taken > cap) { s->lost += p - s->taken - cap; s->taken = p - cap; }
    return (int)(p - s->taken);
}
static inline int is_capacity(const instream *s) { return s->state == IS_CLOSED ? 0 : s->capacity; }
static inline int is_free(instream *s, uint64_t now) { return is_capacity(s) - is_filled(s, now); }
// 0, or -1 when the format or the capacity cannot be served (the stream stays closed)
static inline int is_open(instream *s, const is_format *f, int frames) {
    memset(s, 0, sizeof *s);
    if (!is_format_ok(f) || frames <= 0) return -1;
    s->state = IS_STOPPED; s->fmt = *f; s->capacity = frames; s->gain = 1.0f;
    return 0;
}
static inline void is_close(instream *s) { s->state = IS_CLOSED; }
// 0, or -1 on a closed stream; starting a started stream changes nothing
static inline int is_start(instream *s, uint64_t now) {
    if (s->state == IS_CLOSED) return -1;
    if (s->state == IS_STOPPED) { s->t0 = now; s->state = IS_STARTED; }
    return 0;
}
// the capture stops; what it captured stays readable until a purge
static inline void is_stop(instream *s, uint64_t now) {
    if (s->state != IS_STARTED) return;
    is_filled(s, now); s->base = is_produced(s, now); s->state = IS_STOPPED;
}
// drops what was captured and not read
static inline void is_purge(instream *s, uint64_t now) { if (s->state != IS_CLOSED) { is_filled(s, now); s->taken = is_produced(s, now); } }
// at most frames frames of what was captured, written to buf (silence); the frame count read
static inline int is_read(instream *s, uint64_t now, void *buf, int frames) {
    if (!buf || frames <= 0) return 0;
    int n = is_filled(s, now); if (n > frames) n = frames;
    if (n <= 0) return 0;
    memset(buf, 0, (size_t)n * (size_t)s->fmt.channels * (size_t)is_sample_bytes(s->fmt.format));
    s->taken += (uint64_t)n;
    return n;
}
