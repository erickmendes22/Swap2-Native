package dev.nxnative.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.BatteryManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.PowerManager;
import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The on-device job (ONDEVICE.md "The service and the screen"): a foreground service of type dataSync in its own process (:pack), started by the launcher's
 * "Prepare game". It runs the job's steps in order on one worker thread with a partial wake lock, posts an ongoing notification with the step's progress and a
 * Pause action, and goes on when the app is swiped away. Every change goes to job.json, so a killed process loses at most the step in hand (the translation not even
 * that): START_STICKY brings the service back and it resumes a job that was running; the launcher's Resume does the same after a reboot or a force stop.
 * <ul>
 * <li>Pause (the notification or the launcher): the tool is interrupted (the translation stops after the shader in hand), the job is written paused, the service
 *     stops and leaves a notification with Resume.</li>
 * <li>Battery below 20 % and not charging, or thermal status SEVERE or worse: the tool is interrupted, the job waits (paused, wake lock released) and goes on by
 *     itself when charging / cooled (thermal MODERATE or better).</li>
 * <li>Android 14+'s 6 hours a day for dataSync services (onTimeout): paused like Pause, reason "timeout"; the launcher's Resume, once the app is open, goes on.</li>
 * </ul>
 * The launcher binds with a Messenger (MSG_REGISTER with replyTo) and gets MSG_STATE messages, data "job" = job.json's text, as the job changes.
 */
public final class PackService extends Service {
    static final String ACTION_START = "dev.nxnative.android.pack.START", ACTION_PAUSE = "dev.nxnative.android.pack.PAUSE";
    static final String EXTRA_JOB = "job";
    /** ACTION_PAUSE's sender, for the logs (a job paused with reason "user"): notification, launcher or adb; missing = an intent from elsewhere */
    static final String EXTRA_FROM = "from";
    /** On the notification's MainActivity intent: open the preparation screen (Ondevice.fromIntent) */
    static final String EXTRA_OPEN_SCREEN = "open_prepare_screen";
    static final int MSG_REGISTER = 1, MSG_UNREGISTER = 2, MSG_STATE = 3;
    private static final String TAG = "nxpack", CHANNEL = "pack";
    private static final int NOTE = 1;
    /** Starts of one step the process may not live through before the job fails (Job.start) */
    private static final int MAX_STARTS = 2;
    private static final Pattern PROGRESS = Pattern.compile("^progress:? (\\d+)(?: |/)(\\d+)(?: (\\S+))?");

    private final List<Messenger> clients = new CopyOnWriteArrayList<>();
    private final Messenger messenger = new Messenger(new Handler(Looper.getMainLooper(), this::handle));
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Object lock = new Object();
    private NotificationManager nm;
    private PowerManager pm;
    private PowerManager.WakeLock wake;
    private PackEngine engine;
    private volatile Job job;
    private volatile Thread worker;
    private volatile String stopReason;   // user, timeout: the job pauses and the service stops
    private volatile String autoReason;   // battery, thermal: the job waits and goes on by itself
    private volatile boolean inTool;
    private volatile String stepCode;     // the code of step()'s failure (GameFlow: step, dump), set with its text
    private volatile IOException saveError;   // job.json could not be written (a full disk): the launcher says so; the job in memory stays the truth
    private int batteryPct = 100, thermal;
    private boolean charging = true;
    private long lastNote, lastSave, lastSend;
    private final PowerManager.OnThermalStatusChangedListener thermalListener = s -> { thermal = s; policy(); };
    private final BroadcastReceiver batteryReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) { battery(i); policy(); }
    };

    @Override public void onCreate() {
        super.onCreate();
        nm = getSystemService(NotificationManager.class);
        pm = getSystemService(PowerManager.class);
        NotificationChannel ch = new NotificationChannel(CHANNEL, getString(R.string.s2_note_channel), NotificationManager.IMPORTANCE_LOW);
        ch.setDescription(getString(R.string.s2_note_channel_note));
        nm.createNotificationChannel(ch);
        wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "nxnative:pack");
        wake.setReferenceCounted(false);
        engine = PackEngine.create(this);
        battery(registerReceiver(batteryReceiver, new IntentFilter(Intent.ACTION_BATTERY_CHANGED), Context.RECEIVER_NOT_EXPORTED));
        thermal = pm.getCurrentThermalStatus();
        pm.addThermalStatusListener(getMainExecutor(), thermalListener);
        policy();
    }

    @Override public void onDestroy() {
        unregisterReceiver(batteryReceiver);
        pm.removeThermalStatusListener(thermalListener);
        if (wake.isHeld()) wake.release();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent i) { return messenger.getBinder(); }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_PAUSE.equals(action)) {
            String from = intent.getStringExtra(EXTRA_FROM);
            boolean running = worker != null && worker.isAlive();
            logPause(job, (from != null ? from : "an intent without \"from\"") + (running ? "" : ", nothing running"));
            if (running) requestStop("user");
            else if (worker == null) stopSelf(startId);   // a stale notification: nothing runs here
            return START_STICKY;
        }
        String path = intent == null ? null : intent.getStringExtra(EXTRA_JOB);
        File f = path != null ? new File(path) : Job.remembered(this);
        Job j = null;
        boolean bad = false;
        try {
            if (f != null) j = Job.read(f);
        } catch (IOException e) {
            // never a silent stop: logcat at error level, the launcher told (bound now, or when it registers), and a notification that stays (below)
            Log.e(TAG, "job " + f + " cannot be read: " + e.getMessage());
            if (intent != null && f.isFile()) { unreadable(f, e); bad = true; }
        }
        // A sticky restart (no intent: the process was killed) resumes only a job that was running; a start resumes one that is not done
        boolean go = j != null && (intent == null ? "running".equals(j.state()) : !"done".equals(j.state()) || j.apkChanged());
        if (!go && (worker == null || !worker.isAlive())) {
            // startForegroundService must be answered by startForeground even when there is nothing to do
            if (intent != null) startForeground(j);
            stopForeground(STOP_FOREGROUND_REMOVE);
            // a Start or Retry (the notification's, the launcher's) on a job.json that cannot be read: said in a notification that outlives the service, which
            // stops now (the launcher binds after its start, so a message to it alone is usually lost)
            if (bad) nm.notify(NOTE, unreadableNote());
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (worker != null && worker.isAlive()) {
            startForeground(job);
            return START_STICKY;
        }
        job = j;
        if (!startForeground(j)) {
            // Android refused a foreground service here (a start from the background): the job stays as it is, the launcher's Resume starts it
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        stopReason = null;
        // the user's Start / Resume / Retry: earlier deaths in a step count no more (only sticky restarts add up, and the launcher's recovery of a killed job,
        // Ondevice.recover, which is one too)
        if (intent != null && !"recover".equals(intent.getStringExtra(EXTRA_FROM))) j.endedAll();
        Job.remember(this, j.file);
        worker = new Thread(this::work, "nxpack-job");
        worker.start();
        return START_STICKY;
    }

    /** Android 14+'s daily dataSync limit (6 h): pause cleanly and stop within the seconds Android gives (else it ends the app) */
    @Override public void onTimeout(int startId, int fgsType) {
        Log.w(TAG, "onTimeout: the daily dataSync limit is reached; pausing");
        Job j = job;
        if (j != null) {
            j.state("paused", "timeout", null);
            save(j, true);
        }
        requestStop("timeout");
        stopForeground(STOP_FOREGROUND_DETACH);
        if (j != null) nm.notify(NOTE, note(j));
        stopSelf();
    }

    private boolean startForeground(Job j) {
        try {
            startForeground(NOTE, note(j), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            return true;
        } catch (RuntimeException e) {   // ForegroundServiceStartNotAllowedException, or the type's time limit used up
            Log.w(TAG, "startForeground refused: " + e);
            if (j != null && !"done".equals(j.state())) {
                j.state("paused", "refused", null);
                save(j, true);
            }
            return false;
        }
    }

    /** A pause the user asked for, in logcat (nxpack) and in the current step's log (ondevice/logs/<step>.log): who asked and when */
    private void logPause(Job j, String from) {
        String line = "[pack] " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()) + " pause asked (from " + from + ")";
        Log.i(TAG, line);
        if (j == null) return;
        int i = j.current();
        if (i < 0) return;
        File logs = new File(j.dir(), "logs");
        try {
            logs.mkdirs();
            Files.write(new File(logs, Job.STEPS[i] + ".log").toPath(), (line + "\n").getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (IOException e) {
            Log.w(TAG, "pause log: " + e);
        }
    }

    private void requestStop(String reason) {
        stopReason = reason;
        engine.interrupt();
        synchronized (lock) { lock.notifyAll(); }
        Thread w = worker;
        // a tool that does not stop within 20 s goes with the process: every step is restartable, and the job says paused
        main.postDelayed(() -> {
            if (w != null && w.isAlive() && worker == w) {
                Log.w(TAG, "the tool did not stop within 20 s: ending the process");
                Job j = job;
                if (j != null) {
                    j.state("paused", reason, null);
                    save(j, true);
                    stopForeground(STOP_FOREGROUND_DETACH);
                    nm.notify(NOTE, note(j));
                }
                Process.killProcess(Process.myPid());
            }
        }, 20_000);
    }

    // ---- Battery and heat ----

    private void battery(Intent i) {
        if (i == null) return;
        int level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        if (level >= 0 && scale > 0) batteryPct = level * 100 / scale;
        charging = i.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
    }

    /** The automatic pause: below 20 % on battery, or SEVERE heat (until MODERATE or better) */
    private void policy() {
        String r = null;
        if (batteryPct < 20 && !charging) r = "battery";
        else if (thermal >= PowerManager.THERMAL_STATUS_SEVERE || ("thermal".equals(autoReason) && thermal > PowerManager.THERMAL_STATUS_MODERATE)) r = "thermal";
        String was = autoReason;
        autoReason = r;
        if (r != null && was == null) {
            Log.i(TAG, "pausing: " + r + " (battery " + batteryPct + " %" + (charging ? ", charging" : "") + ", thermal " + thermal + ")");
            if (inTool) engine.interrupt();
        }
        if (r == null && was != null) {
            Log.i(TAG, "going on: battery " + batteryPct + " %" + (charging ? ", charging" : "") + ", thermal " + thermal);
            synchronized (lock) { lock.notifyAll(); }
        }
    }

    // ---- The job ----

    /**
     * Deletes the split's kept scan results (Job.splitScan, in the app's own storage) of every game but this job's, as the job starts: one job runs at a time,
     * so no other game's split can resume from them before a job of that game starts again (after Forget, or a job whose folder went: a few hundred MB).
     * Decided from the job that runs, read from its job.json, never from the remembered path: shared storage that is briefly unreadable deletes nothing.
     */
    private void dropOtherSplitScans(Job j) {
        String keep = j.titleId();
        if (keep.isEmpty()) return;
        File[] games = j.splitScan(this).getParentFile().listFiles();
        if (games != null) for (File g : games) if (!g.getName().equals(keep)) {
            Log.i(TAG, "deleting the kept split results of another game: " + g);
            Job.deleteTree(g);
        }
    }

    private void work() {
        Job j = job;
        wake.acquire(7 * 3600_000L);
        try {
            dropOtherSplitScans(j);
            if (j.apkChanged()) {
                List<String> hot = OcarinaShaderDelta.keys(j);
                // A complete same-ABI library (or an audited additive ABI
                // extension) already runs on this APK. Preserve it and all
                // progress when the completed job's only change is the APK:
                // otherwise a version-string change incorrectly starts
                // 42,339 translations again.
                File previous = Pack.libraryOf(j.pack());
                if (previous == null) previous = Pack.playableLibrary(j.pack(), j.titleId());
                Profile profile = Profile.of(j.titleId());
                ShaderLibs.Header header = previous != null ? ShaderLibs.header(previous) : null;
                if ("done".equals(j.state()) && hot.isEmpty()
                        && header != null && profile != null
                        && header.fits(previous.length())
                        && profile.shaderInputs.equals(header.inputs)) {
                    Log.i(TAG, "shader update: previous complete " + header.entries
                            + "-shader library is ABI-compatible; keeping it unchanged after APK update"
                            + " (no unnecessary split or translation)");
                    j.acceptPlayableShaderVersion();
                    save(j, true);
                    return;
                }
                j.resetChainSteps();
                if (!hot.isEmpty()) {
                    j.expectedShaders(hot.size());
                    Log.i(TAG, "Ocarina incremental update: compiling exactly " + hot.size()
                            + " reviewed shader keys into a small overlay; full base preserved");
                } else {
                    Log.i(TAG, "shader update: retaining already translated per-key results; "
                            + "vk_android_build.py verifies every cached result's toolchain, "
                            + "ABI/profile and SPIR-V identity before reusing it");
                    // Never wipe xlate/ or lib/ merely because APK metadata
                    // changed. They are checkpoints, and the translator's
                    // result_head() independently rejects stale entries.
                }
            }
            j.state("running", null, null);
            save(j, true);
            int i;
            while ((i = j.next()) >= 0) {
                if (!waitWhileAuto(j)) break;
                String s = Job.STEPS[i];
                // The pack already holds this APK's library of the game (Import shaders…, android/SHADERS.md "Shader zips"): nothing to split or translate; the pack
                // step takes it where it is. A new job, one resumed or retried after an import, and one whose chain steps an APK update reset all come here
                // The pack step too: a job stopped at it (or between the shaders and it) still names its own ondevice/lib, whose library pack_android.py would copy over
                // the imported one. A library the pack step refused before (Job.importRefused) is not taken again
                boolean inPack = new File(j.pack(), "shaders").equals(j.shaderCache());
                if ((s.equals("split") || s.equals("shaders") || s.equals("pack") && !inPack) && !engine.simulated() && ShaderZip.ready(j.pack(), j.titleId())
                        && !j.refusedImport(Pack.libraryOf(j.pack()))
                        && OcarinaShaderDelta.keys(j).isEmpty()) {
                    Log.i(TAG, s + ": the pack " + j.pack() + " holds this app's shader library (v-" + BuildConfig.NX_DMSH_VK_CHAIN + "): "
                            + (s.equals("pack") ? "the pack step takes it there" : "skipped, nothing is translated"));
                    j.shadersInPack();
                    save(j, true);
                    if (!s.equals("pack")) continue;
                }
                // Everything that can fail before the tool runs (the logs folder, the free space, the tools' unpack) is checked before the step is marked running:
                // a failure there is the job's, with its code, and the step stays pending (a full disk left "rewrite running" with no log line, 2026-11-08)
                if (!preflight(j, s)) {
                    save(j, true);
                    break;
                }
                j.stepState(s, "running");
                int starts = j.start(s);
                save(j, true);
                if (starts > MAX_STARTS) {   // twice ended by Android inside this step (START_STICKY brought it back): stop instead of looping
                    j.ended(s);
                    j.stepState(s, "pending");
                    j.fail(GameFlow.KILLED, -1, -1, Job.STEP_TEXT[i].toLowerCase(Locale.ROOT) + " was stopped by Android " + (starts - 1) + " times before it finished, most likely "
                            + "for memory (it needs up to " + (s.equals("rewrite") ? "2.7" : "1.5") + " GB). Close other apps, then tap Retry");
                    save(j, true);
                    break;
                }
                String fail;
                stepCode = GameFlow.STEP;
                try {
                    fail = step(j, i);
                } catch (Throwable t) {   // the step does not stay running: the outer catch records the failure
                    j.ended(s);
                    j.stepState(s, "pending");
                    throw t;
                }
                j.ended(s);
                if (stopReason != null) { j.stepState(s, "pending"); break; }
                // interrupted by the policy (which may have cleared since): wait if it still holds, then run the step again
                if (fail != null && (autoReason != null || fail.equals("interrupted"))) { j.stepState(s, "pending"); continue; }
                boolean refusedImport = false;
                if (fail != null && s.equals("pack") && j.shadersImported() && fail.contains("no current shader library")) {
                    refusedImport = true;
                    // the imported library is not current for the phone's profile (other shader tables): Retry translates on the phone instead of failing again
                    j.importRefused(Pack.libraryOf(j.pack()));
                    fail = "the imported shaders were made from other shader tables than this app's profile, so the pack step did not take them. Import a shaders zip "
                            + "exported with this app's version, or tap Retry to translate the shaders on the phone (" + fail + ")";
                }
                if (fail != null) {
                    j.stepState(s, "pending");
                    j.fail(refusedImport ? GameFlow.IMPORTED_SHADERS : GameFlow.noSpace(fail) ? GameFlow.NOSPACE : stepCode, DumpCheck.freeOf(j.work()), -1, fail);
                    save(j, true);
                    break;
                }
                j.stepState(s, "done");
                save(j, true);
                if (s.equals("split")) Job.deleteTree(j.splitScan(this));   // recorded done: the scan results are no longer needed
            }
            if (j.next() < 0) {
                j.state("done", null, null);
                // the split and the translation results are not needed once the library is in the pack
                Job.deleteTree(new File(j.dir(), "split"));
                Job.deleteTree(j.splitScan(this));
                Job.deleteTree(new File(j.dir(), "xlate"));
                Job.deleteTree(new File(j.dir(), "lib"));
            } else if (stopReason != null) j.state("paused", stopReason, null);
            save(j, true);
        } catch (Exception e) {
            Log.e(TAG, "job", e);
            // never a step left running: the card would take the job for one in progress (Job.read repairs older files the same way)
            j.clearRunningSteps();
            String code = GameFlow.failCode(e);
            long free = e instanceof PackEngine.NoSpace ? ((PackEngine.NoSpace) e).free : DumpCheck.freeOf(j.work());
            long need = e instanceof PackEngine.NoSpace ? ((PackEngine.NoSpace) e).need : -1;
            j.fail(code, free, need, String.valueOf(e));
            save(j, true);
        } finally {
            if (wake.isHeld()) wake.release();
            main.post(this::finished);
        }
    }

    private void finished() {
        Job j = job;
        worker = null;
        publish(j, true);
        stopForeground(STOP_FOREGROUND_DETACH);
        if (j != null) nm.notify(NOTE, note(j));
        stopSelf();
    }

    /**
     * What step s needs before it is marked running: its logs folder and a first line in its log (a full disk fails here, with a line in logcat), the test
     * overrides (ondevice/env.txt), the free space the step needs (DumpCheck.stepNeed), and the tools unpacked and started (PackEngine.prepare: NoSpace,
     * ToolsFailed). false: the job is failed with its code, and the step stays pending
     */
    private boolean preflight(Job j, String s) {
        File logs = new File(j.dir(), "logs");
        long need = DumpCheck.stepNeed(s, j.codeOnly());
        // A reviewed incremental hot shader update only creates a tiny overlay,
        // not another 1+ GiB full library. The split step keeps its own limit.
        if (("shaders".equals(s) || "pack".equals(s)) && !OcarinaShaderDelta.keys(j).isEmpty())
            need = Math.min(need, 256L << 20);
        // A completed on-device shader library may now be installed by a
        // hard link or atomic rename, without the old second 1.2+ GB copy.
        // If the destination is on another filesystem, the packer itself
        // checks the ACTUAL destination space before its streamed fallback.
        if ("pack".equals(s)) {
            File owned = new File(j.dir(), "lib");
            File cached = new File(j.shaderCache(), "v-" + BuildConfig.NX_DMSH_VK_CHAIN + "/dmsh_vk.lib");
            File recovered = new File(j.pack(), "shaders/v-" + BuildConfig.NX_DMSH_VK_CHAIN + "/dmsh_vk.lib");
            try {
                if (owned.getCanonicalFile().equals(j.shaderCache().getCanonicalFile())
                        && (cached.isFile() || recovered.isFile()))
                    need = Math.min(need, 256L << 20);
            } catch (IOException ignored) { /* use old conservative allowance */ }
        }
        try {
            if (!logs.isDirectory() && !logs.mkdirs()) throw new IOException("cannot make " + logs);
            applyEnvFile(j, null);
            long free = DumpCheck.freeOf(j.work());
            String line = "== " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()) + " " + Prefs.buildTag(this) + ": " + s + " starts ("
                    + (free >= 0 ? GameFlow.gb(free) : "?") + " free, the step needs " + GameFlow.gb(need) + ")\n";
            Files.write(new File(logs, s + ".log").toPath(), line.getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
            if (free >= 0 && !GameFlow.fits(free, need)) {
                Log.e(TAG, s + ": " + GameFlow.gb(free) + " free, the step needs " + GameFlow.gb(need));
                j.fail(GameFlow.NOSPACE, free, need, s + ": " + GameFlow.gb(free) + " free in " + j.work() + ", the step needs " + GameFlow.gb(need));
                return false;
            }
            if (!s.equals("identify")) engine.prepare();
            return true;
        } catch (PackEngine.NoSpace e) {
            Log.e(TAG, s + ": " + e.getMessage());
            j.fail(GameFlow.NOSPACE, e.free, e.need, e.getMessage());
        } catch (IOException | RuntimeException | UnsatisfiedLinkError e) {
            Log.e(TAG, s + ": the step cannot start", e);
            long free = DumpCheck.freeOf(j.work());
            String code = GameFlow.noSpace(String.valueOf(e.getMessage())) || free >= 0 && free < (64L << 20) ? GameFlow.NOSPACE
                    : e instanceof PackEngine.ToolsFailed ? GameFlow.TOOLS : GameFlow.IO;
            j.fail(code, code.equals(GameFlow.TOOLS) ? DumpCheck.freeOf(getFilesDir()) : free, code.equals(GameFlow.NOSPACE) ? need : -1, String.valueOf(e));
        }
        return false;
    }

    /** Tests: ondevice/env.txt, KEY=VALUE lines, overrides the tools' environment (and the fake engine's NX_FAKE_FAIL); each line into the step's log when one is given */
    private void applyEnvFile(Job j, File log) throws IOException {
        File envFile = new File(j.dir(), "env.txt");
        if (envFile.isFile()) for (String l : Files.readAllLines(envFile.toPath(), StandardCharsets.UTF_8)) {
            int eq = l.indexOf('=');
            if (eq > 0 && !l.startsWith("#")) {
                PackEngine.setenv(l.substring(0, eq).trim(), l.substring(eq + 1).trim());
                if (log != null) Files.write(log.toPath(), ("[env.txt] " + l.trim() + "\n").getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.APPEND);
            }
        }
    }

    /** A job.json the service cannot read: the bound launcher is told (MSG_STATE with "error"), so the card says so */
    private void unreadable(File f, IOException e) {
        Message m = Message.obtain(null, MSG_STATE);
        Bundle b = new Bundle();
        b.putString("file", f.getPath());
        b.putString("error", GameFlow.UNREADABLE);
        b.putString("detail", String.valueOf(e.getMessage()));
        m.setData(b);
        pendingUnreadable = b;   // a launcher that registers later (it binds after its start) is told too, once
        for (Messenger c : clients) {
            try { c.send(Message.obtain(m)); pendingUnreadable = null; } catch (RemoteException x) { clients.remove(c); }
        }
    }

    /** The last unreadable job.json no launcher was told of yet (unreadable) */
    private Bundle pendingUnreadable;

    /** A job.json that cannot be read, as a notification that stays after the service stops; its tap opens the launcher */
    private Notification unreadableNote() {
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        String why = getString(R.string.s2_why_unreadable);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.s2_symbol).setOnlyAlertOnce(true).setAutoCancel(true)
                .setContentTitle(getString(R.string.s2_note_failed, getString(R.string.s2_note_a_game))).setContentText(why)
                .setStyle(new Notification.BigTextStyle().bigText(why))
                .setContentIntent(PendingIntent.getActivity(this, 3, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)).build();
    }

    /** Waits while the policy pauses the job; false when the job is to stop */
    private boolean waitWhileAuto(Job j) throws InterruptedException {
        if (autoReason == null) return stopReason == null;
        j.state("paused", autoReason, null);
        save(j, true);
        if (wake.isHeld()) wake.release();
        synchronized (lock) {
            while (autoReason != null && stopReason == null) lock.wait(30_000);
        }
        if (stopReason != null) return false;
        wake.acquire(7 * 3600_000L);
        j.state("running", null, null);
        save(j, true);
        return true;
    }

    /** Runs step i; null when it is done, else why it failed */
    private String step(Job j, int i) throws IOException {
        String s = Job.STEPS[i];
        if (s.equals("identify")) {
            DumpCheck.Result r = DumpCheck.check(j.dump(), 0);   // the space: the preflight of each step
            stepCode = GameFlow.DUMP;
            if (!r.ok()) { if (DumpCheck.NOSPACE.equals(r.code) || DumpCheck.UNWRITABLE.equals(r.code)) stepCode = GameFlow.IO; return r.error; }
            if (!r.titleId.equals(j.titleId()) || r.version != j.version()) return "the dump changed: it is now " + r.titleId + " " + r.version;
            stepCode = GameFlow.STEP;
            j.stepProgress(s, 1, 1, "identify");
            return null;
        }
        File od = j.dir(), dump = j.dump(), pack = j.pack();
        String v = String.valueOf(j.version());
        // The update's RomFS and main: folders of the dump, or (a .nup) <file>.nup:update/<version>/romfs and …/exefs/main (base/… for version 0), which the
        // tools take where they take the folders (android/NUP.md "Naming a package"); the dump itself goes to pack_android.py as it is, folder or .nup
        String upRomfs = DumpCheck.versionPath(dump, j.version(), "romfs"), upMain = DumpCheck.versionPath(dump, j.version(), "exefs/main");
        File split = new File(od, "split"), splitTmp = new File(od, "split.tmp"), splitScan = j.splitScan(this), xlate = new File(od, "xlate"), lib = new File(od, "lib");
        String tool;
        String[] argv;
        // Scoped incremental mode requires an explicit reviewed key manifest
        // AND the older same-ABI complete library in the game's pack.
        // With neither, the old full/manifest-delta update remains unchanged.
        List<String> hotKeys = OcarinaShaderDelta.keys(j);
        // The tools' arguments: the in-process forms (pack_android.py --in-process: the rewriter in the same Python; shader_split.py with J=1 below: no process pool;
        // vk_android_build.py with the translator and the validator as libraries, XLATE / SPIRV_VAL below; the app's process must not fork, ONDEVICE.md "No subprocesses").
        // The split is resumable by RomFS file: its scan results are kept in the app's own storage (Job.splitScan, DM_SPLIT_RESUME, shader_split.py ScanCache) and a rerun scans only the files
        // that have none; it writes its outputs into split.tmp/ at its end, which then becomes split/.
        // The shaders step is resumable by shader: each result is a file in xlate/ (DMSH_VK_RESULTS) and a rerun skips the shaders that have one; it writes the
        // library (lib/v-<DMSH_VK_CHAIN>/) from the results at its end. The pack step copies the library into the pack (--shader-cache)
        switch (s) {
            case "rewrite":
                tool = "scripts/pack_android.py";
                argv = new String[] {dump.getPath(), "--version", v, "--out", pack.getPath(), "--code-only", "-j", "1", "--in-process"};
                break;
            case "split":
                Job.deleteTree(splitTmp);   // only outputs a stopped run may have half written: the split writes them all at its end; what it kept is in Job.splitScan
                splitTmp.mkdirs();
                tool = "dm/gfx/tools/shader_split.py";
                argv = new String[] {upRomfs, upMain, new File(splitTmp, "pkg").getPath(),
                        new File(splitTmp, "shader_map.tsv").getPath(), new File(splitTmp, "shader_facts.tsv").getPath(), new File(splitTmp, "shader_pairs.tsv").getPath(),
                        new File(splitTmp, "pso_pairs.tsv").getPath()};
                break;
            case "shaders": {
                boolean capturedOnly = !hotKeys.isEmpty() &&
                        hotKeys.stream().allMatch(k ->
                                new File(od.getParentFile(), "nvn_shdump/" + k + ".code").isFile() &&
                                new File(od.getParentFile(), "nvn_shdump/" + k + ".ctl").isFile()) &&
                        !new File(split, "pkg").isDirectory();
                if (!new File(split, "pkg").isDirectory() && !capturedOnly) {
                    // Normal shader preparation must still split the game's
                    // approved static shader map before translation.
                    j.stepState("split", "pending");
                    return "interrupted";
                }
                if (!capturedOnly) {
                    String bad = splitMatchesProfile(j, split);
                    if (bad != null) return bad;
                }
                // For captured-only repair, vk_android_build.py generates the
                // tiny verified .bin package itself. Never re-scan or
                // invalidate the already playable static 42k-shader library.
                File sourcePkg = capturedOnly ? new File(od, "capture-pkg") : new File(split, "pkg");
                if (capturedOnly) Files.createDirectories(sourcePkg.toPath());
                tool = "dm/gfx/tools/vk_android_build.py";
                if (!hotKeys.isEmpty()) {
                    argv = new String[4 + hotKeys.size()];
                    argv[0] = "--target";
                    argv[1] = "vulkan";
                    argv[2] = sourcePkg.getPath();
                    argv[3] = new File(pack, "shaders/hot").getPath();
                    for (int k = 0; k < hotKeys.size(); k++) argv[k + 4] = hotKeys.get(k);
                } else {
                    argv = new String[] {"--target", "vulkan", new File(split, "pkg").getPath(), lib.getPath()};
                }
                break;
            }
            case "pack": {
                tool = "scripts/pack_android.py";
                // Only the job-owned completed library may be moved. An
                // imported/user-supplied shader cache must remain untouched.
                boolean ownedCache = j.shaderCache().getCanonicalFile()
                        .equals(new File(j.dir(), "lib").getCanonicalFile());
                argv = !hotKeys.isEmpty()
                    ? new String[] {dump.getPath(), "--version", v, "--out", pack.getPath(),
                        "--keep-code", "--hot-keys", String.join(",", hotKeys),
                        "-j", "1", "--in-process"}
                    : ownedCache
                    ? new String[] {dump.getPath(), "--version", v, "--out", pack.getPath(),
                        "--shader-cache", j.shaderCache().getPath(), "--keep-code",
                        "--move-shader-cache", "-j", "1", "--in-process"}
                    : new String[] {dump.getPath(), "--version", v, "--out", pack.getPath(),
                        "--shader-cache", j.shaderCache().getPath(), "--keep-code", "-j", "1", "--in-process"};
                break;
            }
            default:
                return "unknown step " + s;
        }
        File logs = new File(od, "logs");
        logs.mkdirs();
        File log = new File(logs, s + ".log");
        String head = "== " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()) + " " + Prefs.buildTag(this) + ", engine " + BuildConfig.NX_PACK_ENGINE + ": "
                + tool + " " + String.join(" ", argv) + "\n";
        Files.write(log.toPath(), head.getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        if (s.equals("shaders")) {   // a failed shader's kept result would fail every Retry the same way: those shaders are translated again (ShaderResults)
            List<ShaderResults.Failed> again = ShaderResults.dropFailed(xlate);
            StringBuilder b = new StringBuilder();
            for (ShaderResults.Failed f : again) b.append("[retry] translating again, it failed before: ").append(f).append('\n');
            if (b.length() > 0) Files.write(log.toPath(), b.toString().getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.APPEND);
        }
        int workers = Math.max(1, Runtime.getRuntime().availableProcessors() - 2);
        PackEngine.setenv("DM_GAME", j.titleId());
        // V10: translating shaders runs in a separate step, NOT through
        // pack_android.py. Enable the GMEM pool-1 fast path there as well.
        // Reset for every step, so a later game never inherits the option.
        PackEngine.setenv("DMSH_GMEM_FAST1", "shaders".equals(s) && "0400486024DEC000".equals(j.titleId()) ? "1" : "0");
        // iOS V22 raw segment reuse, and 8192-region Vulkan map; only the
        // shader-translation step sees these, never the old runtime library.
        boolean ocarinaShaders = "shaders".equals(s) && "0400486024DEC000".equals(j.titleId());
        PackEngine.setenv("DMSH_GMEM_LAST1", ocarinaShaders ? "1" : "0");
        PackEngine.setenv("DMSH_GMEM_MAP_8192", ocarinaShaders ? "1" : "0");
        // The translator is still explicitly limited to hotKeys. A captured
        // source must be verified before it is ever given a shader key.
        PackEngine.setenv("DMSH_VK_CAPTURE_DIR",
                ocarinaShaders ? new File(od.getParentFile(), "nvn_shdump").getPath() : "");
        File userProfiles = Profile.userDir();   // a game whose profile is not built into the APK: the tools find it there (dm/games/game.py DM_GAMES_DIR)
        if (userProfiles.isDirectory()) PackEngine.setenv("DM_GAMES_DIR", userProfiles.getPath());
        // The mods folder (<Switch2>/Mods/<title ID>/<mod>/exefs/<build ID>.ips|.pchtxt; an older mods/ while it is there: ExefsMods.root): the rewrite applies a module's exefs patches before rewriting it, and its key names
        // them (pack_android.py --mods, PackCheck.mods); a folder that is not there means no mods
        PackEngine.setenv("DM_MODS_DIR", PackCheck.modsRoot().getPath());
        PackEngine.setenv("DM_REWRITE_J", "1");
        PackEngine.setenv("NX_PACK_JOBS", String.valueOf(workers));
        PackEngine.setenv("J", s.equals("split") ? "1" : String.valueOf(workers));   // the split's J is its process pool: 1 = in this process
        PackEngine.setenv("DM_SPLIT_RESUME", splitScan.getPath());   // the split's kept scan results (only shader_split.py reads it)
        // Shaders the game bound that no table had, saved by the host as they were met (GameActivity sets DM_NVN_SHDUMP to this folder; dm/gfx/vk_android/vka_shader.c):
        // the split takes them into the map (shader_split.py nvn_dumps), so the next Prepare translates them. Zelda: Ocarina of Time's opening video binds 11 compute shaders
        // that are in no file the split reads
        PackEngine.setenv("DM_NVN_SHDUMP_DIR", new File(od.getParentFile(), "nvn_shdump").getPath());
        PackEngine.setenv("DM_PACKER_COMMIT", BuildConfig.NX_COMMIT);   // pack.tsv's packer: no repository on the phone to ask
        PackEngine.setenv("NX_PACK_WORK", od.getPath());
        PackEngine.setenv("NX_PACK_VERSION", v);
        PackEngine.setenv("TMPDIR", getCacheDir().getPath());
        // vk_android_build.py: the per-shader results (kept until the job is done: a rerun resumes from them), the translator and SPIRV-Tools from the APK's lib/
        // (bare names: the linker finds them in the APK, as System.loadLibrary does; ctypes loads them in this process)
        PackEngine.setenv("DMSH_VK_RESULTS", xlate.getPath());
        // the delta update: entries of the pack's older libraries that the profile's manifest has unchanged are kept, only the rest translated (android/SHADERS.md#delta-updates)
        PackEngine.setenv("DMSH_VK_DELTA_FROM", new File(pack, "shaders").getPath());
        PackEngine.setenv("XLATE", "libdmsh_xlate.so");
        PackEngine.setenv("SPIRV_VAL", "libSPIRV-Tools-shared.so");
        PackEngine.setenv("DMSH_VK_REQUIRE_ALL", "1");   // a library without every shader is a failed step, never a finished one
        PackEngine.setenv("DMSH_VK_XLATE_J", "1");       // one translator call at a time (one thread was faster on the phone); the env file below can change it
        // Tests: ondevice/env.txt, KEY=VALUE lines, overrides any of the above for the tools (e.g. DMSH_VK_XLATE_J=6 to compare the translator's threads)
        applyEnvFile(j, log);
        // the split resumed from kept scan results runs faster than a whole one: only a whole split teaches the phone's split rate
        String[] kept = splitScan.list();
        Tail tail = new Tail(j, s, log, !s.equals("split") || kept == null || kept.length == 0);
        long t0 = SystemClock.elapsedRealtime();
        tail.start();
        int code;
        inTool = true;
        try {
            if (autoReason != null || stopReason != null) return "interrupted";
            code = engine.run(tool, argv, log.getPath());
        } finally {
            inTool = false;
            tail.finish();
        }
        Log.i(TAG, s + ": exit " + code);
        tail.learn(code == 0 ? (SystemClock.elapsedRealtime() - t0) / 1000.0 : -1);
        if (code == PackEngine.INTERRUPTED) return "interrupted";
        if (code != 0) return s + " stopped with code " + code + (tail.lastRed != null ? ": " + tail.lastRed : "") + " (log: " + log + ")";
        if (s.equals("split")) {
            // A completed scan can still omit an unreadable archive. Do not publish that partial split or blame the user's dump.
            String incomplete = incompleteSplit(log);
            if (incomplete != null) return incomplete;
            Job.syncTree(splitTmp);   // on the disk before the rename, so a reboot after the step is recorded done cannot leave cut tables in split/
            Job.deleteTree(split);
            Files.move(splitTmp.toPath(), split.toPath(), StandardCopyOption.ATOMIC_MOVE);
            // the scan results go only once job.json records the split done (work()): a kill before that resumes from them instead of scanning everything again
        }
        long t = j.stepTotal(i);
        j.stepProgress(s, t > 0 ? t : 1, t > 0 ? t : 1, "");
        return null;
    }

    private static String incompleteSplit(File log) throws IOException {
        String failure = null;
        try (java.io.BufferedReader reader = Files.newBufferedReader(log.toPath(), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                // A log is appended on Retry; only the latest attempt determines its result.
                if (line.startsWith("== ")) failure = null;
                if (line.startsWith("[RED] ") && (line.contains("its shaders are left out") || line.contains("file(s) could not be read"))) {
                    if (failure == null || line.contains("MemoryError")) failure = line.substring(6);
                }
            }
        }
        if (failure == null) return null;
        return "Shader extraction could not read every archive: " + failure + ". Retry after updating the app; see " + log;
    }

    /**
     * null when the split found the shaders the app's profile lists (its shader_map.tsv byte for byte, as a Mac split of the same dump does), else what to do.
     * vk_android_build.py builds the keys of the profile's map from the split's package: another map means a dump with other shaders (modified, or incomplete).
     */
    private String splitMatchesProfile(Job j, File split) {
        if (engine.simulated()) return null;
        File have = new File(split, "shader_map.tsv");
        try {
            File want = new File(PackNative.repo(), "dm/games/" + j.titleId() + "/shader_map.tsv");
            if (java.util.Arrays.equals(Files.readAllBytes(want.toPath()), Files.readAllBytes(have.toPath()))) return null;
        } catch (IOException | RuntimeException | UnsatisfiedLinkError e) {
            return "cannot compare the dump's shaders with the app's list: " + e.getMessage();
        }
        Job.deleteTree(split);   // a Retry splits again, from the start
        Job.deleteTree(j.splitScan(this));
        j.stepState("split", "pending");
        stepCode = GameFlow.DUMP;
        return "the dump's shaders are not the ones this app knows for " + j.name() + " (" + Profile.versionName(j.version()) + ", " + have.getName()
                + " differs). The dump may be incomplete or modified: dump the game again, then Retry";
    }

    /** Reads the step's log as it grows: progress lines into the job, the last [RED] line for a failure's message */
    private final class Tail extends Thread {
        private final Job j;
        private final String step;
        private final File log;
        private volatile boolean done;
        private long pos;
        private final StringBuilder partial = new StringBuilder();
        volatile String lastRed;
        // the step's rate (PrepareTime.Meter): into job.json for the time left, and into the phone's rates (Job.learn) from what was kept before this run
        private final PrepareTime.Meter meter = new PrepareTime.Meter();
        // the run can teach the step's rate: a split resumed from kept results cannot, nor a rewrite that kept a module as it was (pack_android.py "unchanged, kept":
        // a Retry after a stop, a mods change to one module), which ends in a fraction of a whole one's time
        private volatile boolean whole;
        private final String key;      // its rate's name in the phone's rates, null for the identify step
        private final float base;
        private long lastLearn = SystemClock.elapsedRealtime();

        Tail(Job j, String step, File log, boolean whole) {
            super("nxpack-tail");
            this.j = j;
            this.step = step;
            this.log = log;
            this.whole = whole;
            key = step.equals("shaders") ? Job.RATE_SHADER : step.equals("split") ? Job.RATE_SPLIT : step.equals("rewrite") ? Job.rateRewrite(j.titleId()) : step.equals("pack") ? Job.RATE_PACK : null;
            base = key == null ? 0 : Job.learned(PackService.this, key);
            pos = log.length();
        }

        /**
         * The phone's rate from this run: the shaders' and the split's from the meter once it covers 2 minutes (the split's per shader of the game's map: it reads the
         * whole RomFS whatever the delta), the rewrite's and the pack step's from the seconds a whole run took (seconds: the step ended well; -1: it did not)
         */
        void learn(double seconds) {
            if (key == null || !whole) return;
            if (step.equals("shaders") || step.equals("split")) {
                if (meter.measuredSeconds() < 120) return;
                double v = meter.mean();
                if (step.equals("split")) {
                    Profile p = Profile.of(j.titleId());
                    long units = j.stepTotal(Job.SHADERS - 1);   // the split's count: RomFS entries
                    if (p == null || p.shaderTotal <= 0 || units <= 1) return;
                    v = v * units / p.shaderTotal;
                }
                Job.learn(PackService.this, key, base, v);
            } else if (seconds > 0) Job.learn(PackService.this, key, base, seconds);
        }

        @Override public void run() {
            while (!done) {
                read();
                SystemClock.sleep(300);
            }
            read();
        }

        void finish() {
            done = true;
            try {
                join(2000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        private void read() {
            try (RandomAccessFile f = new RandomAccessFile(log, "r")) {
                long len = f.length();
                if (len <= pos) return;
                f.seek(pos);
                byte[] b = new byte[(int) Math.min(len - pos, 1 << 20)];
                f.readFully(b);
                pos += b.length;
                partial.append(new String(b, StandardCharsets.UTF_8));
            } catch (IOException e) {
                return;
            }
            int nl;
            boolean changed = false;
            while ((nl = partial.indexOf("\n")) >= 0) {
                String line = partial.substring(0, nl).trim();
                partial.delete(0, nl + 1);
                Matcher m = PROGRESS.matcher(line);
                if (m.find()) {
                    long done = Long.parseLong(m.group(1));
                    j.stepProgress(step, done, Long.parseLong(m.group(2)), m.group(3));
                    // the shaders step's count is the translation's ("translate"); its library and check stages are no part of the rate
                    if (!step.equals("shaders") || m.group(3) == null || m.group(3).equals("translate")) {
                        long now = SystemClock.elapsedRealtime();
                        meter.feed(now, done);
                        if (meter.rate() > 0) j.stepRate(step, meter.rate());
                        if (now - lastLearn >= 600_000) { lastLearn = now; learn(-1); }   // a long step teaches the phone's rate as it goes
                    }
                    changed = true;
                } else if (line.startsWith("[RED] ")) lastRed = line.substring(6);
                else if (step.equals("rewrite") && line.endsWith(": unchanged, kept")) whole = false;
            }
            if (changed) save(j, false);
        }
    }

    // ---- State out: job.json, the notification, the launcher ----

    /** Writes job.json (at most every 2 s unless forced) and tells the notification and the launcher */
    private void save(Job j, boolean force) {
        long now = SystemClock.elapsedRealtime();
        synchronized (this) {
            if (force || now - lastSave >= 2000) {
                lastSave = now;
                try {
                    j.save();
                    saveError = null;
                } catch (IOException e) {
                    Log.e(TAG, "job.json: " + e);
                    saveError = e;   // the launcher says the progress cannot be written (most likely a full disk); the job in memory goes on
                }
            }
        }
        main.post(() -> publish(j, force));
    }

    private void publish(Job j, boolean force) {
        if (j == null) return;
        long now = SystemClock.elapsedRealtime();
        if (force || now - lastSend >= 250) {
            lastSend = now;
            Message m = Message.obtain(null, MSG_STATE);
            Bundle b = new Bundle();
            b.putString("job", j.json());
            b.putString("file", j.file.getPath());
            b.putBoolean("alive", worker != null);
            IOException se = saveError;
            if (se != null) b.putString("saveError", String.valueOf(se.getMessage()));
            m.setData(b);
            for (Messenger c : clients) {
                try {
                    c.send(Message.obtain(m));
                } catch (RemoteException e) {
                    clients.remove(c);
                }
            }
        }
        if (worker != null && (force || now - lastNote >= 1000)) {
            lastNote = now;
            nm.notify(NOTE, note(j));
        }
    }

    private boolean handle(Message m) {
        switch (m.what) {
            case MSG_REGISTER:
                if (m.replyTo != null) {
                    clients.add(m.replyTo);
                    if (job != null) publish(job, true);
                    else if (pendingUnreadable != null) {
                        Message u = Message.obtain(null, MSG_STATE);
                        u.setData(pendingUnreadable);
                        pendingUnreadable = null;
                        try { m.replyTo.send(u); } catch (RemoteException x) { clients.remove(m.replyTo); }
                    }
                }
                return true;
            case MSG_UNREGISTER:
                clients.remove(m.replyTo);
                return true;
            default:
                return false;
        }
    }

    private Notification note(Job j) {
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(EXTRA_OPEN_SCREEN, true);   // the tap opens the preparation screen (Ondevice.fromIntent), not only the library
        Notification.Builder b = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.s2_symbol).setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_PROGRESS).setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
                .setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        String name = j == null ? getString(R.string.s2_note_a_game) : j.name();
        String sim = engine.simulated() ? " (simulated)" : "";
        if (j == null) return b.setContentTitle(getString(R.string.s2_note_preparing, name) + sim).setContentText(getString(R.string.s2_st_starting)).build();
        String state = j.state();
        int pct = (int) Math.round(j.overall() * 100);
        int i = j.current();
        if (state.equals("done")) return b.setContentTitle(getString(R.string.s2_note_ready, name) + sim).setContentText(getString(R.string.s2_note_ready_text)).setAutoCancel(true).build();
        boolean running = state.equals("running") && worker != null;
        boolean waiting = state.equals("paused") && worker != null;   // the policy's pause: it goes on by itself
        b.setContentTitle(getString(running ? R.string.s2_note_preparing : waiting ? R.string.s2_note_waiting : state.equals("failed") ? R.string.s2_note_failed
                : R.string.s2_note_paused, name) + sim);
        String sub = getString(R.string.s2_note_step, i + 1, Job.STEPS.length, pct);
        long left = running || waiting ? j.remaining(Job.rates(this, j.titleId()), System.currentTimeMillis()) : -1;
        if (left > 0) sub += " · " + getString(R.string.s2_time_left, PrepareTime.approx(left));
        Intent pause = new Intent(this, PackService.class).setAction(ACTION_PAUSE).putExtra(EXTRA_FROM, "notification");
        Notification.Action pauseAction = new Notification.Action.Builder(null, getString(R.string.s2_prep_pause),
                PendingIntent.getService(this, 1, pause, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)).build();
        if (waiting) {
            String why = Job.reasonText(this, j.reason());
            return b.setContentText(why).setStyle(new Notification.BigTextStyle().bigText(j.stepText(this) + " · " + pct + " %\n" + why))
                    .setSubText(sub).setOngoing(true).addAction(pauseAction).build();
        }
        if (running) {
            long d = j.stepDone(i), t = j.stepTotal(i);
            if (t > 1) b.setProgress((int) Math.min(t, Integer.MAX_VALUE), (int) Math.min(d, t), false);
            else b.setProgress(100, pct, false);
            b.setContentText(j.stepText(this)).setSubText(sub).setOngoing(true).addAction(pauseAction);
        } else {
            String why = j.statusText(this, false);
            b.setContentText(j.stepText(this) + " · " + pct + " %").setStyle(new Notification.BigTextStyle().bigText(j.stepText(this) + " · " + pct + " %\n" + why)).setOngoing(false);
            Intent resume = new Intent(this, PackService.class).setAction(ACTION_START).putExtra(EXTRA_JOB, j.file.getPath());
            b.addAction(new Notification.Action.Builder(null, getString(state.equals("failed") ? R.string.s2_prep_retry : R.string.s2_prep_resume),
                    PendingIntent.getForegroundService(this, 2, resume, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)).build());
        }
        return b.build();
    }
}
