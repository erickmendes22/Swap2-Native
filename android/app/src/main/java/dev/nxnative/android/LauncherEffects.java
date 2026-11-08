package dev.nxnative.android;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.SoundPool;
import android.os.SystemClock;
import android.util.Log;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

import java.util.Locale;

/**
 * Launcher-only feedback: the page entrance and Console revision 6's interface sounds (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md "ElevenLabs audio revision 3",
 * docs/SWAP2-NATIVE-CONSOLE-v4.md "Audio delivery and routing", with the policy of docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 5). The nine cues are the
 * selected ElevenLabs v3 recordings (res/raw/s2_*.wav, copied unchanged from assets/artwork/swap2-native/console-v4/audio-v3-elevenlabs: mono 48 kHz 16-bit PCM),
 * each with its gain from that folder's delivery.json. One action gets one semantic cue (Cue). They play through one SoundPool of three streams that exists only
 * while a launcher screen is in the foreground (resume / pause: MainActivity, PrepareActivity), never in the game's process, with no audio focus and no loop. A
 * cue is played only once its own sample has loaded (an unloaded cue is skipped, never queued for later), and a pool's late load callbacks are ignored once it is
 * released. Gain = the Interface volume (Settings › Audio, 0..100 %, 35 % by default) × the cue's gain.
 * <p>
 * Route: USAGE_GAME (the media stream), chosen over USAGE_ASSISTANCE_SONIFICATION: the system stream that sonification takes is tied to the ring / system volume,
 * which many phones mute together with Android's touch sounds or keep on the speaker, so an explicitly enabled launcher sound could stay silent with nothing on
 * screen to say why. The media stream is the one the launcher's volume keys adjust while it is in the foreground (resume: setVolumeControlStream) and the one
 * the game itself plays on, so the volume the user sees and changes is the one these cues follow; state() reports that stream's level and whether it ends on a
 * Bluetooth device. The device's volumes and settings are only read, never changed.
 * <p>
 * Policy: the Interface sounds switch and the Interface volume govern the cues. Silent: that switch off, the volume at 0, the phone not in normal ringer mode
 * (silent or vibrate), Do not disturb on, the media stream at zero or muted, and, only when the user turns on Follow Android's touch sounds (off by default),
 * the system's touch sounds off. Android's touch sounds setting alone no longer silences them. state() names the one reason (State), which Settings › Audio shows
 * and the log ("[audio] …", tag nxnative, no device names or identifiers) records when it changes; each sample's load result and a play the system answers with no
 * stream are logged too. Focus cues are throttled to one per 120 ms (motion.json audio.focus_throttle_ms).
 */
final class LauncherEffects {
    private LauncherEffects() {}

    /** The cues, their v3 recordings and delivery.json gains (focus 0.3, the rest 0.5) */
    enum Cue {
        FOCUS(R.raw.s2_focus, 0.3f),            // a selection the user changed (a cover, a settings category)
        CONFIRM(R.raw.s2_confirm, 0.5f),        // an accepted button, switch or choice, pause / resume included
        BACK(R.raw.s2_back, 0.5f),              // back to the previous screen inside a page (a settings category to its list)
        PANEL_OPEN(R.raw.s2_panel_open, 0.5f),  // a settings page, a game's settings or its Manage sheet opens
        PANEL_CLOSE(R.raw.s2_panel_close, 0.5f),// a settings page closes back to the library
        READY(R.raw.s2_ready, 0.5f),            // an observed preparation becoming ready to play, once per job
        ERROR(R.raw.s2_error, 0.5f),            // an action refused with a visible message
        LAUNCH(R.raw.s2_launch, 0.5f),          // Play accepted, once, before the game starts
        BOOT(R.raw.s2_boot, 0.5f);              // the opening (BrandIntro), when it is already loaded

        final int raw;
        final float gain;

        Cue(int raw, float gain) { this.raw = raw; this.gain = gain; }

        /** Its recording's name (res/raw), for the log */
        String sample() { return "s2_" + name().toLowerCase(Locale.ROOT); }
    }

    /**
     * Why the interface sounds play or not right now (state()): the one answer Settings › Audio shows and the log names. plays: a cue would be played (OK, or OK
     * on a Bluetooth device); every other value is the first reason it is silent, in the order state() checks them
     */
    enum State {
        OK(R.string.s2_audio_state_ok, true),
        BLUETOOTH(R.string.s2_audio_state_bluetooth, true),        // plays, on a Bluetooth device (its own volume and delay)
        OFF(R.string.s2_audio_state_off, false),                    // the Interface sounds switch
        VOLUME_ZERO(R.string.s2_audio_state_volume_zero, false),    // the Interface volume at 0 %
        SILENT(R.string.s2_audio_state_silent, false),              // ringer mode silent or vibrate
        DND(R.string.s2_audio_state_dnd, false),                    // Do not disturb
        TOUCH_SOUNDS(R.string.s2_audio_state_touch, false),         // Follow Android's touch sounds on, and they are off
        CHANNEL_MUTED(R.string.s2_audio_state_channel, false),      // the media stream at zero or muted
        INACTIVE(R.string.s2_audio_state_inactive, false),          // no launcher screen in the foreground: no pool
        LOADING(R.string.s2_audio_state_loading, false),            // the cue's sample not loaded yet
        LOAD_FAILED(R.string.s2_audio_state_failed, false),         // its sample failed to load
        PLAY_FAILED(R.string.s2_audio_state_play_failed, false);    // the system answered the play with no stream

        final int text;
        final boolean plays;

        State(int text, boolean plays) { this.text = text; this.plays = plays; }

        /** Its sentence for the screen, with the media stream's level where it names it */
        String describe(Context c) { return c.getString(text, mediaPercent(c)); }
    }

    static final int DEFAULT_VOLUME = 35;   // motion.json audio.default_master_volume
    private static final String VOLUME = "volume_v6", FOLLOW_TOUCH = "follow_touch_sounds";
    private static final long FOCUS_THROTTLE_MS = 120, BOOT_GRACE_MS = 250;
    private static final String TAG = "Swap2Native";
    /** The cues' route (see the class comment): the media stream, as a game's own sounds */
    private static final AudioAttributes ATTRS = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_GAME)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
    private static final int STREAM = AudioManager.STREAM_MUSIC;   // the stream USAGE_GAME plays on

    private static SoundPool pool;
    private static Context app;
    private static final int[] ids = new int[Cue.values().length];
    private static final boolean[] loaded = new boolean[Cue.values().length];
    private static final boolean[] failed = new boolean[Cue.values().length];
    private static long poolAt;          // when the pool was made (the log's load times)
    private static State logged;         // the last state the log named for a play (logged again only when it changes)
    private static long lastFocus, bootAsked = -1, launchAt = -1;
    private static int bootStream;
    private static final android.os.Handler MAIN = new android.os.Handler(android.os.Looper.getMainLooper());
    private static final long LAUNCH_MS = 450;   // s2_launch.wav's delivered length
    /** A pool the preparation screen handed to the library (handOver) until the library's resume takes it; released if nothing takes it (the library gone) */
    private static SoundPool handed;
    private static final long HANDOVER_MS = 2000;
    private static final Runnable UNCLAIMED = () -> { handed = null; pause(); };

    static boolean sounds(Context c) { return Prefs.open(c, "interface").getBoolean("sounds", true); }
    static boolean reduced(Context c) { return Prefs.open(c, "interface").getBoolean("reduced_motion", false); }
    static void preference(Context c, String key, boolean value) {
        Prefs.open(c, "interface").edit().putBoolean(key, value).apply();
    }

    /** Settings › Audio › Interface volume, 0..100 (35 until the user picks one) */
    static int volume(Context c) { return Math.max(0, Math.min(100, Prefs.open(c, "interface").getInt(VOLUME, DEFAULT_VOLUME))); }
    static void volume(Context c, int v) { Prefs.open(c, "interface").edit().putInt(VOLUME, Math.max(0, Math.min(100, v))).apply(); }

    /** Settings › Audio › Follow Android's touch sounds: off by default (the cues then ignore that system setting) */
    static boolean followTouch(Context c) { return Prefs.open(c, "interface").getBoolean(FOLLOW_TOUCH, false); }
    static void followTouch(Context c, boolean on) { preference(c, FOLLOW_TOUCH, on); }

    /** A launcher screen came to the foreground: the pool and its nine samples (loaded asynchronously, each usable once its own load completes) */
    static void resume(Context c) {
        MAIN.removeCallbacks(UNCLAIMED);
        handed = null;   // a handed pool is the library's now
        // The volume keys change the stream the cues play on while this screen is in front (this activity's own choice, not a device setting)
        if (c instanceof Activity) ((Activity) c).setVolumeControlStream(STREAM);
        if (pool != null) return;
        app = c.getApplicationContext();
        SoundPool p = new SoundPool.Builder().setMaxStreams(3).setAudioAttributes(ATTRS).build();
        pool = p;
        java.util.Arrays.fill(loaded, false);
        java.util.Arrays.fill(failed, false);
        bootStream = 0;
        logged = null;
        poolAt = SystemClock.uptimeMillis();
        AudioManager audio = c.getSystemService(AudioManager.class);
        if (audio != null) Log.i(TAG, "[audio] pool: usage game (media stream " + mediaPercent(c) + "%, " + (bluetooth(audio) ? "Bluetooth output" : "device output")
                + "), interface volume " + volume(c) + "%, sounds " + (sounds(c) ? "on" : "off") + (followTouch(c) ? ", following touch sounds" : ""));
        p.setOnLoadCompleteListener((sp, sample, status) -> {
            if (sp != pool) return;   // a released pool's late callback: never played
            for (Cue q : Cue.values()) {
                if (ids[q.ordinal()] != sample) continue;
                long ms = SystemClock.uptimeMillis() - poolAt;
                if (status != 0) {   // a sample that failed to load: never played, and the screen says so
                    failed[q.ordinal()] = true;
                    Log.w(TAG, "[audio] " + q.sample() + " failed to load (status " + status + ", " + ms + " ms)");
                    if (q == Cue.BOOT) bootAsked = -1;
                    continue;
                }
                loaded[q.ordinal()] = true;
                Log.i(TAG, "[audio] " + q.sample() + " loaded (" + ms + " ms)");
                if (q != Cue.BOOT || bootAsked < 0) continue;
                // The opening asked for its cue just before the sample was ready: played only if still near the start (never late over the library) and not yet
                long late = SystemClock.uptimeMillis() - bootAsked;
                bootAsked = -1;
                if (late <= BOOT_GRACE_MS) { if (bootStream == 0) play(app, Cue.BOOT); }
                else Log.i(TAG, "[audio] s2_boot skipped: loaded " + late + " ms after the opening asked (grace " + BOOT_GRACE_MS + " ms)");
            }
        });
        ids[Cue.BOOT.ordinal()] = p.load(c, Cue.BOOT.raw, 1);   // first: the opening asks for it while the pool is still loading
        for (Cue q : Cue.values()) if (q != Cue.BOOT) ids[q.ordinal()] = p.load(c, q.raw, 1);
    }

    /**
     * The launcher screen left the foreground: no cue plays any more and the pool goes, with every stream. Only the Launch cue, played just before the game's
     * activity was started, is let finish (its 450 ms, while the game's own process is still starting); then that pool is released too
     */
    static void pause() {
        if (handed != null && handed == pool) {   // the preparation screen closing for Play: its loaded pool stays for the library's onActivityResult
            MAIN.removeCallbacks(UNCLAIMED);
            MAIN.postDelayed(UNCLAIMED, HANDOVER_MS);
            return;
        }
        handed = null;
        java.util.Arrays.fill(loaded, false);
        java.util.Arrays.fill(failed, false);
        bootAsked = -1;
        bootStream = 0;
        SoundPool p = pool;
        pool = null;
        if (p == null) return;
        long left = launchAt < 0 ? 0 : LAUNCH_MS - (SystemClock.uptimeMillis() - launchAt);
        launchAt = -1;
        if (left <= 0) p.release();
        else MAIN.postDelayed(p::release, left);
    }

    /**
     * The preparation screen finishes with Play: the library starts the game from onActivityResult, which runs before its own onResume, so a pool released
     * with the preparation screen's pause would drop the Launch cue (or a refusal's Error cue). The loaded pool is handed over instead: the preparation screen's
     * pause keeps it, the library's resume takes it, and its pause releases it as usual (Launch let finish)
     */
    static void handOver() { if (pool != null) handed = pool; }

    /**
     * The first reason a cue may not play now, or null when it may: the user's switch and volume, normal ringer mode, no Do not disturb, Android's touch sounds
     * (only when the user follows them), the media stream not at zero, a launcher screen in the foreground, and the cue's sample loaded (cue null: every sample).
     * Reads the device's state only; cheap enough for every play (no route query)
     */
    private static State blocker(Context c, Cue cue) {
        if (!sounds(c)) return State.OFF;
        if (volume(c) == 0) return State.VOLUME_ZERO;
        AudioManager audio = c.getSystemService(AudioManager.class);
        if (audio == null || audio.getRingerMode() != AudioManager.RINGER_MODE_NORMAL) return State.SILENT;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null && nm.getCurrentInterruptionFilter() > NotificationManager.INTERRUPTION_FILTER_ALL) return State.DND;
        if (followTouch(c) && android.provider.Settings.System.getInt(c.getContentResolver(), android.provider.Settings.System.SOUND_EFFECTS_ENABLED, 1) == 0)
            return State.TOUCH_SOUNDS;
        if (audio.isStreamMute(STREAM) || audio.getStreamVolume(STREAM) == 0) return State.CHANNEL_MUTED;
        if (pool == null) return State.INACTIVE;
        if (cue != null) return failed[cue.ordinal()] ? State.LOAD_FAILED : loaded[cue.ordinal()] ? null : State.LOADING;
        for (boolean f : failed) if (f) return State.LOAD_FAILED;
        for (boolean l : loaded) if (!l) return State.LOADING;
        return null;
    }

    /** What the interface sounds do now, for the screen (Settings › Audio): the reason they are silent, else OK or OK on a Bluetooth device */
    static State state(Context c) {
        State b = blocker(c, null);
        if (b != null) return b;
        AudioManager audio = c.getSystemService(AudioManager.class);
        return audio != null && bluetooth(audio) ? State.BLUETOOTH : State.OK;
    }

    /** Whether interface sounds may play now (state() for the reason) */
    static boolean allowed(Context c) { return blocker(c, Cue.CONFIRM) == null; }

    /** The media stream's level, 0..100 % of its range (0 when unreadable) */
    static int mediaPercent(Context c) {
        AudioManager audio = c.getSystemService(AudioManager.class);
        if (audio == null) return 0;
        int max = audio.getStreamMaxVolume(STREAM), min = audio.getStreamMinVolume(STREAM);
        return max <= min ? 0 : Math.round(100f * (audio.getStreamVolume(STREAM) - min) / (max - min));
    }

    /** Whether the cues' route ends on a Bluetooth device (A2DP, LE audio, SCO or a hearing aid): only the device type is read, never its name or address */
    private static boolean bluetooth(AudioManager audio) {
        try {
            for (AudioDeviceInfo d : audio.getAudioDevicesForAttributes(ATTRS)) {
                switch (d.getType()) {
                    case AudioDeviceInfo.TYPE_BLUETOOTH_A2DP: case AudioDeviceInfo.TYPE_BLUETOOTH_SCO: case AudioDeviceInfo.TYPE_BLE_HEADSET:
                    case AudioDeviceInfo.TYPE_BLE_SPEAKER: case AudioDeviceInfo.TYPE_BLE_BROADCAST: case AudioDeviceInfo.TYPE_HEARING_AID:
                        return true;
                }
            }
        } catch (RuntimeException e) {   // a system that refuses the route query: reported as the device's own output
            Log.w(TAG, "[audio] output route unreadable: " + e.getClass().getSimpleName());
        }
        return false;
    }

    /** Logs why a cue was not played when that reason differs from the last one logged (so a run of focus moves logs it once), and a return to playing */
    private static void note(Cue cue, State s) {
        if (s == logged) return;
        logged = s;
        if (s == null) Log.i(TAG, "[audio] cues play again (" + cue.sample() + ")");
        else Log.i(TAG, "[audio] " + cue.sample() + " not played: " + s.name().toLowerCase(Locale.ROOT));
    }

    /** Plays one cue now, if its sample is loaded and sounds are allowed; otherwise nothing (never queued) */
    static void play(Context c, Cue cue) {
        if (c == null) return;
        State b = blocker(c, cue);
        if (b != null) { if (b != State.INACTIVE) note(cue, b); return; }   // no pool: the launcher is not in front, nothing to report
        if (cue == Cue.FOCUS) {
            long now = SystemClock.uptimeMillis();
            if (now - lastFocus < FOCUS_THROTTLE_MS) return;
            lastFocus = now;
        }
        start(c, cue);
    }

    /** The pool plays the cue at its gain; returns its stream, 0 (logged) when the system played nothing */
    private static int start(Context c, Cue cue) {
        SoundPool p = pool;
        if (p == null) return 0;
        float v = volume(c) / 100f * cue.gain;
        int stream = p.play(ids[cue.ordinal()], v, v, cue == Cue.BOOT ? 2 : 1, 0, 1f);
        if (stream == 0) {
            Log.w(TAG, "[audio] " + cue.sample() + " play returned no stream");
            logged = State.PLAY_FAILED;
        } else note(cue, null);
        if (cue == Cue.BOOT) bootStream = stream;
        if (cue == Cue.LAUNCH && stream != 0) launchAt = SystemClock.uptimeMillis();
        return stream;
    }

    /**
     * Settings › Audio › Test sound: the Confirm cue now through the same checks as every cue (never the focus throttle), and what happened: its state when it was
     * played (OK, Bluetooth), the reason it was not, or PLAY_FAILED when the system gave it no stream. Never changes a volume or setting
     */
    static State test(Context c) {
        State b = blocker(c, Cue.CONFIRM);
        if (b != null) {
            Log.i(TAG, "[audio] test sound not played: " + b.name().toLowerCase(Locale.ROOT));
            return b;
        }
        if (start(c, Cue.CONFIRM) == 0) return State.PLAY_FAILED;
        AudioManager audio = c.getSystemService(AudioManager.class);
        State s = audio != null && bluetooth(audio) ? State.BLUETOOTH : State.OK;   // another sample still loading does not make this one unheard
        Log.i(TAG, "[audio] test sound played (" + s.name().toLowerCase(Locale.ROOT) + ", media stream " + mediaPercent(c) + "%)");
        return s;
    }

    /**
     * The opening's cue at its start: now when loaded, else within 250 ms of the request when its load completes, else not at all; once per opening (a second
     * request while its stream plays, or after the grace, plays nothing)
     */
    static void boot(Context c) {
        if (bootStream != 0) return;
        if (pool != null && loaded[Cue.BOOT.ordinal()]) play(c, Cue.BOOT);
        else if (pool == null || !failed[Cue.BOOT.ordinal()]) bootAsked = SystemClock.uptimeMillis();
    }

    /** The opening was skipped or ended: its cue stops with it */
    static void stopBoot() {
        bootAsked = -1;
        if (pool != null && bootStream != 0) pool.stop(bootStream);
        bootStream = 0;
    }

    /** A button's listener with its one cue: Confirm */
    static View.OnClickListener click(View.OnClickListener action) { return click(Cue.CONFIRM, action); }

    /** A listener with its one semantic cue, played before the action (so an action that leaves the launcher still sounds once) */
    static View.OnClickListener click(Cue cue, View.OnClickListener action) {
        return action == null ? null : v -> { if (cue != null) play(v.getContext(), cue); action.onClick(v); };
    }

    /** A page's content enters: 180 ms fade with 8 dp travel (motion.json transitions; back: from above); none with reduced motion or animators off */
    static void enter(View view, boolean back) {
        view.animate().cancel();
        view.setAlpha(1f);
        view.setTranslationY(0f);
        if (reduced(view.getContext()) || !ValueAnimator.areAnimatorsEnabled()) return;
        view.setAlpha(0f);
        view.setTranslationY(Ui.dp(view.getContext(), back ? -8 : 8));
        view.animate().alpha(1f).translationY(0f).setDuration(180)
                .setInterpolator(new DecelerateInterpolator()).start();
    }
}
