package dev.nxnative.android;

import android.app.ActivityManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Environment;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * The one-time move of the Switch2 folder into its new layout (Switch2Layout: Games/, Work/&lt;id&gt;, Mods/), at the launcher's start once All files access is
 * on, off the main thread, once per process until a run leaves nothing pending ("switch2_layout" in the launcher's preferences). Then the saved paths that
 * named a moved folder are repointed: the game list (each card's game and pack folder), the picked folders (pack_&lt;id&gt;, save_&lt;id&gt;), the library
 * folder, the remembered job and its "added" mark, and every job.json (dump, work, pack, shader_cache, adopted). Not while a game runs (its process, :game,
 * reads the dump by path) or a Prepare worker is alive (:pack, also while its job is paused): the next start does it. Packs in the app's own storage stay where they are.
 */
final class Switch2Migration {
    private static final String TAG = "nxlayout";
    static final String DONE = "switch2_layout";
    private static final AtomicBoolean started = new AtomicBoolean();

    private Switch2Migration() {}

    /** Starts the move once per process when it may run; refresh runs on the main thread when something moved or was repointed */
    static void start(MainActivity a, Runnable refresh) {
        if (!Environment.isExternalStorageManager()) return;
        boolean moved = Prefs.of(a).getBoolean(DONE, false);   // the move ran: only the saved paths are checked again (a rename the storage service reported as failed and finished later)
        if (busy(a)) return;   // a game or a Prepare worker reads its dump and work folder by path: a later start moves them
        if (!started.compareAndSet(false, true)) return;
        Context c = a.getApplicationContext();
        new Thread(() -> {
            boolean changed = false, done = false;
            try {
                File root = Switch2Layout.root();
                if (!root.isDirectory()) { done = true; return; }   // a new install: nothing to move (the folders are made as they are needed)
                Switch2Layout.Report rep = moved ? new Switch2Layout.Report() : Switch2Layout.migrate(root, f -> {
                    try { return Pack.titleIdOf(f); } catch (IOException | RuntimeException e) { return null; }   // as Add game identifies a game
                });
                Map<String, String> renames = Switch2Layout.renames(root);
                int prefs = repointPrefs(c, renames), jobs = Switch2Layout.repointJobs(root, renames);
                if (prefs > 0 || jobs > 0) Switch2Layout.log(root, "repointed", root, root, prefs + " saved paths, " + jobs + " job files");
                changed = rep.moved > 0 || prefs > 0 || jobs > 0;
                done = !rep.pending();
                Log.i(TAG, "Switch2 layout: " + rep + "; repointed " + prefs + " saved paths, " + jobs + " job files");
            } catch (IOException | RuntimeException e) {
                Log.w(TAG, "Switch2 layout: " + e);
            } finally {
                if (done) Prefs.of(c).edit().putBoolean(DONE, true).commit();
                else started.set(false);   // something waits (a running job): the next start tries again; a failed rename is not retried (Switch2Layout.Report.pending)
                if (changed) a.runOnUiThread(() -> { if (!a.isDestroyed()) refresh.run(); });
            }
        }, "nx-switch2-layout").start();
    }

    /**
     * Whether the game's process (:game) runs, or the Prepare service's (:pack) is alive above cached: its worker keeps the job's dump and work paths in
     * memory, also while job.json says "paused" (PackService.waitWhileAuto: battery, heat) or "pending" (before work() marks it running), so neither its
     * folders nor its job.json may move under it. A cached :pack process has no worker (the service stopped)
     */
    private static boolean busy(Context c) {
        ActivityManager am = (ActivityManager) c.getSystemService(Context.ACTIVITY_SERVICE);
        List<ActivityManager.RunningAppProcessInfo> ps = am == null ? null : am.getRunningAppProcesses();
        if (ps != null) for (ActivityManager.RunningAppProcessInfo p : ps) {
            if (p.processName == null) continue;
            if (p.processName.endsWith(":game")) return true;
            if (p.processName.endsWith(":pack") && p.importance < ActivityManager.RunningAppProcessInfo.IMPORTANCE_CACHED) return true;
        }
        return false;
    }

    /** Repoints the saved paths of the moves; → how many values changed */
    static int repointPrefs(Context c, Map<String, String> renames) {
        if (renames.isEmpty()) return 0;
        int n = 0;
        synchronized (Game.class) {   // FrontendLaunch saves the list under this lock too
            SharedPreferences g = Prefs.open(c, "games");
            String list = g.getString("list", null);
            if (list != null) {
                String t = Switch2Layout.repointJson(list, renames);
                if (!t.equals(list)) { g.edit().putString("list", t).commit(); n++; }
            }
        }
        for (String name : new String[] {"launcher", "library", "ondevice"}) n += repointValues(Prefs.open(c, name), renames);
        return n;
    }

    /** Each string value that is a moved path or a path inside one (picked folders, the library folder, the remembered job, "added": &lt;job file&gt;@&lt;time&gt;) */
    private static int repointValues(SharedPreferences p, Map<String, String> renames) {
        SharedPreferences.Editor e = p.edit();
        int n = 0;
        for (Map.Entry<String, ?> v : p.getAll().entrySet()) {
            if (!(v.getValue() instanceof String) || !((String) v.getValue()).startsWith("/")) continue;
            String s = (String) v.getValue(), t = Switch2Layout.repoint(s, renames);
            if (!t.equals(s)) { e.putString(v.getKey(), t); n++; }
        }
        if (n > 0) e.commit();
        return n;
    }
}
