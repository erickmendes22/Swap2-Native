package dev.nxnative.android;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.RemoteException;
import android.os.SystemClock;

import java.io.File;
import java.io.IOException;

/**
 * The preparation screen (docs/SWAP2-NATIVE-PREPARE-FLOW.md): Jogar on a game that needs preparing opens it (Ondevice.play, once the job has started) and the
 * library's mini summary opens it again (Ondevice.openScreen). It shows the job there is (Job.remembered) through PrepareScreen, live: the service's messages
 * while it runs it (bound with flags 0: never started from here), else job.json every second. Its actions: pause and resume the job (the service), play
 * (only when the pack is ready: the screen finishes with RESULT_OK and EXTRA_PLAY, and MainActivity puts the game in the list and starts it,
 * Ondevice.activityResult), back (finishes; the job goes on in the background and the library shows its summary).
 */
public final class PrepareActivity extends Activity implements ServiceConnection, PrepareScreen.Actions {
    static final String EXTRA_PLAY = "play";
    static final String EXTRA_PREPARE_AGAIN = "prepare_again";
    /** The screen's Import shaders… (a job stopped at its shader steps): MainActivity opens the game's import (Ondevice.activityResult, ShaderUi) */
    static final String EXTRA_IMPORT_SHADERS = "import_shaders";
    /** Play's short job (Ondevice.fixCodeThenPlay): the screen plays the game by itself once the job is done (EXTRA_PLAY), and stays on a failure */
    static final String EXTRA_AUTOPLAY = "autoplay";

    private final Handler h = new Handler(Looper.getMainLooper());
    private final Messenger client = new Messenger(new Handler(Looper.getMainLooper(), this::onMessage));
    private PrepareScreen screen;
    private Messenger service;
    private boolean bound, resumed, jobAlive, saveFailed, autoPlay, played;
    private long resumedAt;
    private Job job;

    /** The launcher's theme choice (Settings › Theme, LauncherTheme) */
    @Override protected void attachBaseContext(android.content.Context base) {
        super.attachBaseContext(base);
        LauncherTheme.apply(this);
    }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        autoPlay = getIntent().getBooleanExtra(EXTRA_AUTOPLAY, false);
        screen = new PrepareScreen(this, this);
        setContentView(screen.view());
        load();
        render();
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        resumedAt = SystemClock.elapsedRealtime();
        LauncherEffects.resume(this);   // the interface sounds of its buttons while it is in front (the library's pool stopped with the library's pause)
        if (!bound) bound = bindService(new Intent(this, PackService.class), this, 0);
        tick();
    }

    @Override protected void onPause() {
        resumed = false;
        LauncherEffects.pause();
        h.removeCallbacksAndMessages(null);
        if (bound) {
            if (service != null) {
                Message m = Message.obtain(null, PackService.MSG_UNREGISTER);
                m.replyTo = client;
                try { service.send(m); } catch (RemoteException e) { /* gone */ }
            }
            unbindService(this);
            bound = false;
            service = null;
            jobAlive = false;
        }
        super.onPause();
    }

    /** Every second while shown: job.json when the service is not telling us */
    private void tick() {
        if (!resumed) return;
        if (service == null || !jobAlive) load();
        render();
        h.postDelayed(this::tick, 1000);
    }

    private void load() {
        File f = Job.remembered(this);
        if (f == null || !f.isFile()) return;
        try { job = Job.read(f); } catch (IOException e) { /* being renamed over: keep the last one */ }
    }

    @Override public void onServiceConnected(ComponentName n, IBinder b) {
        service = new Messenger(b);
        Message m = Message.obtain(null, PackService.MSG_REGISTER);
        m.replyTo = client;
        try { service.send(m); } catch (RemoteException e) { service = null; }
    }

    @Override public void onServiceDisconnected(ComponentName n) { service = null; jobAlive = false; render(); }

    private boolean onMessage(Message m) {
        if (m.what != PackService.MSG_STATE) return false;
        Bundle d = m.getData();
        Job j = Job.of(new File(d.getString("file", "")), d.getString("job", "{}"));
        if (j != null) job = j;
        jobAlive = d.getBoolean("alive");
        saveFailed = d.getString("saveError") != null;
        render();
        return true;
    }

    /** As Ondevice.Panel: the service runs the job now, or may (just resumed, the binding not answered yet) */
    private boolean alive() { return jobAlive || service == null && SystemClock.elapsedRealtime() - resumedAt < 2500 && job != null && ("running".equals(job.state()) || "pending".equals(job.state())); }

    private void render() {
        if (job == null) { finish(); return; }   // forgotten or deleted meanwhile: nothing to show
        PrepareState s = PrepareState.of(this, job, alive(), Ondevice.ready(job), saveFailed && jobAlive);
        screen.render(s, autoPlay, notificationsOff());
        if (autoPlay && s.canPlay && !played) { played = true; play(); }   // Play's short job is done: the game starts
    }

    /** The progress notification is off (Android 13+ asks; without it the job still runs) */
    private boolean notificationsOff() {
        return checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    @Override public void pause() {
        startService(new Intent(this, PackService.class).setAction(PackService.ACTION_PAUSE).putExtra(PackService.EXTRA_FROM, "launcher"));
    }

    @Override public void resume() {
        if (job == null || Ondevice.importBusy(this, job.titleId(), true)) return;   // not beside an export or import of the game's shaders or pack
        startForegroundService(new Intent(this, PackService.class).setAction(PackService.ACTION_START).putExtra(PackService.EXTRA_JOB, job.file.getPath()));
        if (!bound) bound = bindService(new Intent(this, PackService.class), this, 0);
        resumedAt = SystemClock.elapsedRealtime();
    }

    @Override public void prepareAgain() {
        if (job == null || !"0400486024DEC000".equals(job.titleId())
                || !Ondevice.ready(job) || alive()
                || Ondevice.importBusy(this, job.titleId(), true)) return;
        // Return to MainActivity before showing the new selective repair
        // confirmation; do not simply resume the stale failed job.json.
        setResult(RESULT_OK, new Intent().putExtra(EXTRA_PREPARE_AGAIN, true));
        finish();
    }

    @Override public void play() {
        if (job == null || !Ondevice.ready(job) || Ondevice.importBusy(this, job.titleId(), true)) return;
        setResult(RESULT_OK, new Intent().putExtra(EXTRA_PLAY, true));
        LauncherEffects.handOver();   // the library plays Launch (or a refusal's Error) from onActivityResult, before its own resume
        finish();
    }

    @Override public void back() { finish(); }

    /** The phone's storage settings (a job stopped for space): the user frees room there, then Try again */
    @Override public void freeSpace() {
        try { startActivity(new Intent(android.provider.Settings.ACTION_INTERNAL_STORAGE_SETTINGS)); }
        catch (RuntimeException e) { startActivity(new Intent(android.provider.Settings.ACTION_SETTINGS)); }
    }

    /** The phone's list of battery optimizations (a job Android stopped in the background): only a link, the app changes no setting */
    @Override public void battery() {
        try { startActivity(new Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
        catch (RuntimeException e) { startActivity(new Intent(android.provider.Settings.ACTION_SETTINGS)); }
    }

    @Override public void importShaders() {
        if (job == null) return;
        setResult(RESULT_OK, new Intent().putExtra(EXTRA_IMPORT_SHADERS, true));
        finish();
    }

    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() { back(); }
}
