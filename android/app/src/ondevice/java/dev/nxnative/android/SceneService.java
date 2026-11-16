package dev.nxnative.android;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.IBinder;
import android.os.ResultReceiver;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Makes the Scene resolution's 720p overlay (SceneOverlay) in the packer's process (:pack, where the embedded Python runs; the launcher's process never loads it):
 * dm/tools/gsys_dynres.py on the player's RomFS, a few seconds (the first run in the process also unpacks the packer). Started by the game's settings with
 * startService while the launcher is in front; one run at a time, and none while a Prepare step runs (PackNative.packTryRun: BUSY, the launcher says so). It writes
 * into scene_720p.tmp/, which becomes scene_720p/ with its stamp once the tool has checked its own output, and answers on the caller's ResultReceiver: 0 and
 * "message" the overlay's folder, else the exit code (PackNative.BUSY, or the tool's) and "message" why (SceneOverlay.why from its log).
 */
public final class SceneService extends Service {
    static final String EXTRA_SHADOW_PROFILE = "shadow_profile", EXTRA_FPS_PATCH = "fps_patch",
            EXTRA_FPS_MASK = "fps_patch_mask", EXTRA_EFFECT_PROBE = "effect_probe";
    static final String EXTRA_ID = "title_id", EXTRA_ROMFS = "romfs", EXTRA_SCALE = "scale", EXTRA_EXPECT = "expect", EXTRA_VERSION = "version",
            EXTRA_RECEIVER = "receiver", MESSAGE = "message";
    static final int BUSY = PackNative.BUSY;
    /** Another SceneService run is still making an overlay (one at a time: they share the tool and their folders); BUSY now means only a Prepare step */
    static final int RUNNING = 76;
    private static final java.util.concurrent.atomic.AtomicBoolean ACTIVE = new java.util.concurrent.atomic.AtomicBoolean();
    private static final String TAG = "nxscene", TOOL = "dm/tools/gsys_dynres.py";

    /** Starts a run (the launcher, in front); the answer comes on r */
    static void start(Context c, String titleId, String romfs, String scale, String expect, String version, ResultReceiver r) {
        c.startService(new Intent(c, SceneService.class).putExtra(EXTRA_ID, titleId).putExtra(EXTRA_ROMFS, romfs).putExtra(EXTRA_SCALE, scale)
                .putExtra(EXTRA_EXPECT, expect).putExtra(EXTRA_VERSION, version).putExtra(EXTRA_RECEIVER, r));
    }

    /** Make one merged BYML overlay from the active NUP; original scene palette stays untouched. */
    static void startShadow(Context c, String titleId, String romfs, int profile, String version, ResultReceiver r) {
        startShadow(c, titleId, romfs, profile, 0, version, r);
    }
    static void startShadow(Context c, String titleId, String romfs, int profile, int effect, String version, ResultReceiver r) {
        c.startService(new Intent(c, SceneService.class).putExtra(EXTRA_ID, titleId).putExtra(EXTRA_ROMFS, romfs)
                .putExtra(EXTRA_SHADOW_PROFILE, profile).putExtra(EXTRA_FPS_PATCH, effect)
                .putExtra(EXTRA_VERSION, version).putExtra(EXTRA_RECEIVER, r));
    }

    /** Single atomic RomFS patch containing all independently selected GPU work experiments. */
    static void startGraphics(Context c, String titleId, String romfs, int shadow, int mask,
                              String version, ResultReceiver r) {
        if (!ShadowOverlay.validMask(mask)) throw new IllegalArgumentException("conflicting FPS patches");
        c.startService(new Intent(c, SceneService.class).putExtra(EXTRA_ID, titleId)
                .putExtra(EXTRA_ROMFS, romfs).putExtra(EXTRA_SHADOW_PROFILE, shadow)
                .putExtra(EXTRA_FPS_MASK, mask).putExtra(EXTRA_VERSION, version)
                .putExtra(EXTRA_RECEIVER, r));
    }

    /** Disassemble the two crash sites and inspect effect BYML fields from the selected NUP. */
    static void startEffectProbe(Context c, String titleId, String romfs, ResultReceiver r) {
        c.startService(new Intent(c, SceneService.class).putExtra(EXTRA_ID, titleId)
                .putExtra(EXTRA_ROMFS, romfs).putExtra(EXTRA_EFFECT_PROBE, true).putExtra(EXTRA_RECEIVER, r));
    }

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) { stopSelf(startId); return START_NOT_STICKY; }
        new Thread(() -> {
            ResultReceiver r = intent.getParcelableExtra(EXTRA_RECEIVER, ResultReceiver.class);
            int code;
            String msg;
            try {
                String[] got = intent.getBooleanExtra(EXTRA_EFFECT_PROBE, false)
                        ? runEffectProbe(intent.getStringExtra(EXTRA_ID), intent.getStringExtra(EXTRA_ROMFS))
                        : intent.hasExtra(EXTRA_SHADOW_PROFILE)
                        ? runShadow(intent.getStringExtra(EXTRA_ID), intent.getStringExtra(EXTRA_ROMFS),
                                intent.getIntExtra(EXTRA_SHADOW_PROFILE, 0),
                                intent.hasExtra(EXTRA_FPS_MASK)
                                        ? intent.getIntExtra(EXTRA_FPS_MASK, 0)
                                        : (intent.getIntExtra(EXTRA_FPS_PATCH, 0) > 0
                                                ? 1 << (intent.getIntExtra(EXTRA_FPS_PATCH, 0) - 1) : 0),
                                intent.getStringExtra(EXTRA_VERSION))
                        : run(intent.getStringExtra(EXTRA_ID), intent.getStringExtra(EXTRA_ROMFS), intent.getStringExtra(EXTRA_SCALE),
                                intent.getStringExtra(EXTRA_EXPECT), intent.getStringExtra(EXTRA_VERSION));
                code = Integer.parseInt(got[0]);
                msg = got[1];
            } catch (Throwable e) {   // never this process's end: a Prepare may share it
                Log.e(TAG, "scene overlay", e);
                code = 1;
                msg = String.valueOf(e);
            }
            Bundle b = new Bundle();
            b.putString(MESSAGE, msg);
            if (r != null) r.send(code, b);
            stopSelf(startId);
        }, "nx-scene").start();
        return START_NOT_STICKY;
    }

    private String[] runEffectProbe(String id, String romfs) throws IOException {
        if (!Prefs.OCARINA_TITLE.equals(id) || romfs == null)
            return new String[] {"2", "effect probe requires the selected Ocarina update"};
        if (!ACTIVE.compareAndSet(false, true))
            return new String[] {String.valueOf(RUNNING), "another RomFS operation is running"};
        try {
            File files = getExternalFilesDir(null);
            if (files == null) return new String[] {"1", "app files folder is unavailable"};
            File dir = new File(files, "diagnostics");
            if (!dir.isDirectory() && !dir.mkdirs())
                return new String[] {"1", "cannot create diagnostic folder"};
            File out = new File(dir, "ocarina-effects-v131072.txt");
            PackEngine engine = PackEngine.create(this);
            PackEngine.setenv("TMPDIR", getCacheDir().getPath());
            String tool = "dm/tools/oot_effect_crash_probe.py";
            String[] argv = {"--romfs", romfs};
            int code = engine.simulated() ? engine.run(tool, argv, out.getPath())
                    : PackNative.packTryRun(tool, argv, out.getPath());
            Log.i(TAG, tool + " exit " + code + " log " + out);
            if (code == BUSY) return new String[] {String.valueOf(BUSY), "preparation is running"};
            if (code != 0) {
                String detail = out.isFile() ? String.join("\n",
                        Files.readAllLines(out.toPath(), StandardCharsets.UTF_8)) : "no report";
                return new String[] {String.valueOf(code), detail.length() > 500 ? detail.substring(detail.length() - 500) : detail};
            }
            return new String[] {"0", out.getPath()};
        } finally { ACTIVE.set(false); }
    }

    /** {exit code, message}: RUNNING before any file work while another run is on (it owns scene_720p.tmp/ and the log) */
    private String[] run(String id, String romfs, String scale, String expect, String version) throws IOException {
        if (id == null || romfs == null || scale == null || version == null) return new String[] {"2", "incomplete request"};
        if (!ACTIVE.compareAndSet(false, true)) return new String[] {String.valueOf(RUNNING), "the 720p overlay is already being made"};
        try { return runOne(id, romfs, scale, expect, version); } finally { ACTIVE.set(false); }
    }

    /** Opt-in merged graphics BYML overlay, never applied to another game or unknown update. */
    private String[] runShadow(String id, String romfs, int profile, int mask, String version) throws IOException {
        if (!Prefs.OCARINA_TITLE.equals(id) || romfs == null || version == null ||
                profile < 0 || profile > 2 || !ShadowOverlay.validMask(mask) ||
                (profile == 0 && mask == 0))
            return new String[] {"2", "invalid Ocarina graphics patch request"};
        if (!ACTIVE.compareAndSet(false, true))
            return new String[] {String.valueOf(RUNNING), "another RomFS overlay is already being made"};
        try { return runOneShadow(id, romfs, profile, mask, version); }
        finally { ACTIVE.set(false); }
    }

    private String[] runOneShadow(String id, String romfs, int profile, int mask, String version) throws IOException {
        File files = getExternalFilesDir(null);
        if (files == null) return new String[] {"1", "the app's files folder is not available"};
        File out = ShadowOverlay.dirMask(files, id, profile, mask), tmp = new File(out.getPath() + ".tmp");
        File stamp = ShadowOverlay.stampMask(files, id, profile, mask);
        File log = new File(out.getParentFile(), "shadow_" + profile + "_fps_mask_" + mask + ".log");
        Job.deleteTree(tmp);
        if (!tmp.mkdirs()) return new String[] {"1", "cannot create " + tmp};
        String tool = "dm/tools/gsys_shadow.py";
        String[] argv = ShadowOverlay.argvMask(romfs, profile, mask, tmp);
        String head = "== " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date())
                + " " + Prefs.buildTag(this) + ": " + tool + " " + String.join(" ", argv) + "\n";
        Files.write(log.toPath(), head.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        PackEngine engine = PackEngine.create(this);
        PackEngine.setenv("TMPDIR", getCacheDir().getPath());
        int code = engine.simulated() ? engine.run(tool, argv, log.getPath())
                : PackNative.packTryRun(tool, argv, log.getPath());
        Log.i(TAG, tool + ": exit " + code + " (log " + log + ")");
        if (code == BUSY) {
            Job.deleteTree(tmp);
            return new String[] {String.valueOf(code), "a preparation is running"};
        }
        File result = new File(tmp, ShadowOverlay.MAIN);
        if (code != 0 || !result.isFile() || result.length() == 0) {
            Job.deleteTree(tmp);
            List<String> lines = Files.readAllLines(log.toPath(), StandardCharsets.UTF_8);
            String why = SceneOverlay.why(lines);
            return new String[] {String.valueOf(code == 0 ? 1 : code),
                    (why != null ? why : "exit " + code) + " (log: " + log + ")"};
        }
        stamp.delete();
        Job.deleteTree(out);
        if (!tmp.renameTo(out)) return new String[] {"1", "cannot rename " + tmp + " to " + out};
        Files.write(stamp.toPath(), ShadowOverlay.stampTextMask(profile, mask, version).getBytes(StandardCharsets.UTF_8));
        return new String[] {"0", out.getPath()};
    }

    private String[] runOne(String id, String romfs, String scale, String expect, String version) throws IOException {
        if (expect == null) expect = "";
        File files = getExternalFilesDir(null);
        if (files == null) return new String[] {"1", "the app's files folder is not available"};
        File out = SceneOverlay.dir(files, id), tmp = new File(out.getPath() + ".tmp"), stamp = SceneOverlay.stamp(files, id), log = SceneOverlay.log(files, id);
        Job.deleteTree(tmp);
        if (!tmp.mkdirs()) return new String[] {"1", "cannot create " + tmp};
        String[] argv = SceneOverlay.argv(romfs, scale, expect, tmp);
        String head = "== " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()) + " " + Prefs.buildTag(this) + ": " + TOOL + " " + String.join(" ", argv) + "\n";
        Files.write(log.toPath(), head.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        PackEngine e = PackEngine.create(this);
        PackEngine.setenv("TMPDIR", getCacheDir().getPath());
        int code = e.simulated() ? e.run(TOOL, argv, log.getPath()) : PackNative.packTryRun(TOOL, argv, log.getPath());
        Log.i(TAG, TOOL + ": exit " + code + " (log " + log + ")");
        if (code == BUSY) { Job.deleteTree(tmp); return new String[] {String.valueOf(code), "a preparation is running"}; }   // only a job step holds the lock now (ACTIVE)
        String[] made = tmp.list();
        if (code != 0 || made == null || made.length == 0) {
            Job.deleteTree(tmp);
            List<String> l = Files.readAllLines(log.toPath(), StandardCharsets.UTF_8);
            String why = SceneOverlay.why(l);
            return new String[] {String.valueOf(code == 0 ? 1 : code), (why != null ? why : "exit " + code) + " (log: " + log + ")"};
        }
        // the stamp goes first, so a folder without a matching stamp is never taken (SceneOverlay.current), then the new folder in place of the old
        stamp.delete();
        Job.deleteTree(out);
        if (!tmp.renameTo(out)) return new String[] {"1", "cannot rename " + tmp + " to " + out};
        Files.write(stamp.toPath(), SceneOverlay.stampText(scale, expect, version).getBytes(StandardCharsets.UTF_8));
        return new String[] {"0", out.getPath()};
    }
}
