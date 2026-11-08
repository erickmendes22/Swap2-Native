// The silent microphone of nn::audio input streams (audio_instream.h): states, frames produced in real time, the capacity and what is lost beyond it, stop, purge, read
// and its zero fill, with the calls The Legend of Zelda: Ocarina of Time makes (mono PCM16, 48 kHz, 4800 frames; reads of at most 256 frames, main+0x336d7d0).
#include <assert.h>
#include <stdio.h>
#include "audio_instream.h"

#define MS 1000000ull
int main(void) {
    instream s; uint16_t buf[512];
    is_format bad = {0, 1, 48000}, oot = {2, 1, 48000};
    assert(is_open(&s, &bad, 4800) == -1 && s.state == IS_CLOSED);
    assert(is_open(&s, &oot, 0) == -1 && s.state == IS_CLOSED);
    // closed: every answer is the never-opened one
    assert(is_filled(&s, 5 * MS) == 0 && is_capacity(&s) == 0 && is_free(&s, 0) == 0 && is_start(&s, 0) == -1 && is_read(&s, 10 * MS, buf, 256) == 0);
    is_purge(&s, 0); is_stop(&s, 0); assert(s.state == IS_CLOSED);

    assert(is_open(&s, &oot, 4800) == 0 && s.state == IS_STOPPED && s.gain == 1.0f);
    assert(is_capacity(&s) == 4800 && is_filled(&s, 1000 * MS) == 0 && is_free(&s, 1000 * MS) == 4800);   // stopped: nothing is captured
    uint64_t t = 1000 * MS;
    assert(is_start(&s, t) == 0 && s.state == IS_STARTED);
    assert(is_start(&s, t + 3 * MS) == 0);                                // a second start does not restart the clock
    assert(is_filled(&s, t + 5 * MS) == 240);                              // 5 ms at 48 kHz
    assert(is_filled(&s, t + 16666667) == 800);                           // one 60 fps frame
    memset(buf, 0xAB, sizeof buf);
    assert(is_read(&s, t + 16666667, buf, 256) == 256);
    for (int i = 0; i < 256; i++) assert(buf[i] == 0);
    assert(buf[256] == 0xABAB);                                           // only what was read is written (mono, 2 bytes a frame)
    assert(is_filled(&s, t + 16666667) == 544 && is_free(&s, t + 16666667) == 4800 - 544);
    // nothing read for a second: the capacity holds, the oldest frames are lost
    assert(is_filled(&s, t + 1016666667ull) == 4800 && s.lost == 48800 - 256 - 4800);
    assert(is_free(&s, t + 1016666667ull) == 0);
    // stop: what was captured stays readable, nothing more comes
    is_stop(&s, t + 1016666667ull); assert(s.state == IS_STOPPED);
    assert(is_filled(&s, t + 5000 * MS) == 4800);
    assert(is_read(&s, t + 5000 * MS, buf, 512) == 512 && is_filled(&s, t + 5000 * MS) == 4288);
    // purge drops it; a restart counts from the new start
    is_purge(&s, t + 5000 * MS); assert(is_filled(&s, t + 5000 * MS) == 0);
    t += 6000 * MS;
    assert(is_start(&s, t) == 0 && is_filled(&s, t) == 0 && is_filled(&s, t + 10 * MS) == 480);
    is_purge(&s, t + 10 * MS); assert(is_filled(&s, t + 10 * MS) == 0 && is_filled(&s, t + 15 * MS) == 240);   // a purge of a started stream keeps capturing
    // ten hours on: the frame count neither overflows nor drifts (a purge, then exactly one second of frames, capped at the capacity)
    uint64_t far = t + 36000000ull * MS;
    is_purge(&s, far); assert(is_filled(&s, far + 1000 * MS) == 4800);
    // stereo float: 8 bytes a frame
    is_format st = {5, 2, 48000}; float fb[64]; memset(fb, 0xFF, sizeof fb);
    assert(is_open(&s, &st, 960) == 0 && is_start(&s, 0) == 0 && is_read(&s, 1 * MS, fb, 32) == 32);   // 1 ms = 48 frames, 32 read
    for (int i = 0; i < 64; i++) assert(fb[i] == 0.0f);
    is_close(&s); assert(is_filled(&s, 2 * MS) == 0 && is_read(&s, 2 * MS, fb, 32) == 0 && is_capacity(&s) == 0);
    printf("t_audio_instream: ok\n");
    return 0;
}
