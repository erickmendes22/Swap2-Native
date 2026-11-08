package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.Context;
import android.os.SystemClock;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Settings › Storage (MainActivity.buildSettings): the app's data in total (and Android's own count, which the phone's settings show as the app's user data),
 * by category and by game (AppStorageReport.scan, off the main thread with a progress line), each with what it is and, where it is safe, what deletes it.
 * Every deletion is confirmed with what is lost; the current save only after a second, separate confirmation, and never from a batch. Older shader libraries
 * go only from the app's own packs whose current library is in place (a pack on shared storage may be the other app variant's); pipeline caches, temporary storage, captures and the cache only while no game runs; backups are pruned
 * to the newest KEEP_BACKUPS. Each measurement also rewrites the report file in the Switch2 folder.
 */
final class StorageUi {
    private StorageUi() {}

    private static AppStorageReport.Scan last;
    private static long lastAt;

    /** The pane: the last measurement when it is under a minute old, else a new one */
    static void pane(MainActivity a, LinearLayout p) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(p, box, 16);
        if (last != null && SystemClock.elapsedRealtime() - lastAt < 60_000) show(a, box, last);
        else measure(a, box);
    }

    private static int dp(Context c, int v) { return Ui.dp(c, v); }

    private static String size(Context c, long b) { return AppStorageReport.size(c, b); }

    /** Measures again into box: a progress panel (files and bytes so far), then the breakdown */
    static void measure(MainActivity a, LinearLayout box) {
        box.removeAllViews();
        LinearLayout panel = Ui.add(box, Ui.panel(a), 0);
        panel.setPadding(dp(a, 18), dp(a, 16), dp(a, 18), dp(a, 16));
        panel.addView(Ui.text(a, a.getString(R.string.s2_storage_measuring_title), 16, R.color.bn_text, 600));
        ProgressBar bar = Ui.progress(a);
        bar.setIndeterminate(true);
        Ui.add(panel, bar, 10);
        TextView line = Ui.add(panel, Ui.small(a, a.getString(R.string.s2_storage_measuring, "0", size(a, 0))), 8);
        AppStorageReport.Progress pr = new AppStorageReport.Progress();
        boolean[] done = {false};
        Runnable tick = new Runnable() {
            @Override public void run() {
                if (done[0]) return;
                line.setText(a.getString(R.string.s2_storage_measuring, String.format(Locale.getDefault(), "%,d", pr.files), size(a, pr.bytes)));
                box.postDelayed(this, 300);
            }
        };
        box.postDelayed(tick, 300);
        Context app = a.getApplicationContext();
        new Thread(() -> {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            AppStorageReport.Scan s = AppStorageReport.scan(app, pr);
            File report = AppStorageReport.writeReport(app, s, AppStorageReport.startClean());
            a.runOnUiThread(() -> {
                done[0] = true;
                last = s;
                lastAt = SystemClock.elapsedRealtime();
                reportWritten = report != null;
                if (!a.isDestroyed()) show(a, box, s);
            });
        }, "nx-storage-scan").start();
    }

    private static boolean reportWritten;

    private static void show(MainActivity a, LinearLayout box, AppStorageReport.Scan s) {
        box.removeAllViews();
        LinearLayout sum = Ui.add(box, Ui.panel(a), 0);
        sum.setPadding(dp(a, 18), dp(a, 16), dp(a, 18), dp(a, 16));
        sum.addView(Ui.text(a, a.getString(R.string.s2_storage_total, size(a, s.total)), 20, R.color.bn_text, 700));
        StringBuilder t = new StringBuilder();
        if (s.androidData >= 0) t.append(a.getString(R.string.s2_storage_android, size(a, s.androidData - s.androidCache), size(a, s.androidCache)));
        if (s.free >= 0) t.append(t.length() > 0 ? "\n" : "").append(a.getString(R.string.s2_storage_free, size(a, s.free)));
        long bk = s.outside[AppStorageReport.Cat.BACKUPS.ordinal()];
        if (bk > 0) t.append("\n").append(a.getString(R.string.s2_storage_outside, size(a, bk)));
        if (s.gameProcess) t.append("\n").append(a.getString(R.string.s2_storage_running_any));
        if (s.packProcess) t.append("\n").append(a.getString(R.string.s2_storage_prep_running));
        Ui.add(sum, Ui.small(a, t), 6);

        LinearLayout acts = Ui.add(box, Ui.panel(a), 12);
        long left = s.leftovers();
        acts.addView(new Ui.Setting(a, R.drawable.s2_ic_warning, a.getString(R.string.s2_storage_clean), v -> clean(a, box))
                .value(a.getString(R.string.s2_storage_clean_note) + (left > 0 ? " · " + size(a, left) : "")).chevron(a).view);
        acts.addView(new Ui.Setting(a, R.drawable.s2_ic_refresh, a.getString(R.string.s2_storage_rescan), v -> measure(a, box)).chevron(a).view);

        Ui.add(box, Ui.section(a, a.getString(R.string.s2_storage_by_category)), 24);
        LinearLayout cats = Ui.add(box, Ui.listCard(a), 8);
        for (AppStorageReport.Cat k : AppStorageReport.sorted(s.bytes, s.outside)) {
            long in = s.bytes[k.ordinal()], out = s.outside[k.ordinal()];
            if (in == 0 && out == 0) continue;
            cats.addView(new Ui.Setting(a, k.icon, a.getString(k.title), v -> category(a, box, s, k)).value(amount(a, in, out)).chevron(a).view);
        }

        if (!s.games.isEmpty()) {
            Ui.add(box, Ui.section(a, a.getString(R.string.s2_storage_by_game)), 24);
            LinearLayout games = Ui.add(box, Ui.listCard(a), 8);
            for (AppStorageReport.GameUse u : s.games.values()) {
                if (u.inApp() == 0 && u.outsideTotal() == 0 && u.card == null) continue;
                String v = a.getString(R.string.s2_storage_game_value, size(a, u.inApp()));
                if (!u.backups.isEmpty()) v += " · " + a.getResources().getQuantityString(R.plurals.s2_storage_backups_count, u.backups.size(), u.backups.size());
                if (u.card == null) v += " · " + a.getString(R.string.s2_storage_no_card);
                games.addView(new Ui.Setting(a, R.drawable.s2_ic_gamepad, u.name, x -> game(a, box, s, u)).value(v).chevron(a).view);
            }
        }
        File rf = AppStorageReport.reportFile();
        TextView note = Ui.small(a, reportWritten ? a.getString(R.string.s2_storage_report_note, rf.getPath()) : a.getString(R.string.s2_storage_report_none, rf.getPath()));
        note.setTextIsSelectable(true);
        Ui.add(box, note, 12);
    }

    private static String amount(Context c, long in, long out) {
        if (out == 0) return size(c, in);
        return (in > 0 ? size(c, in) + " + " : "") + size(c, out) + " " + c.getString(R.string.s2_storage_outside_short);
    }

    // ---- Dialogs ----

    private static TextView lines(MainActivity a, List<String> l) {
        TextView t = Ui.small(a, String.join("\n", l));
        t.setTextIsSelectable(true);
        return t;
    }

    /** A category: what it is, its size (per game when it has games), and its action */
    private static void category(MainActivity a, LinearLayout box, AppStorageReport.Scan s, AppStorageReport.Cat k) {
        LinearLayout c = new LinearLayout(a);
        c.setOrientation(LinearLayout.VERTICAL);
        c.addView(Ui.body(a, a.getString(k.about)));
        List<String> l = new ArrayList<>();
        l.add(a.getString(R.string.s2_storage_size, amount(a, s.bytes[k.ordinal()], s.outside[k.ordinal()])));
        for (AppStorageReport.GameUse u : s.games.values()) {
            long in = u.bytes[k.ordinal()], out = u.outside[k.ordinal()];
            if (in > 0 || out > 0) l.add(u.name + ": " + amount(a, in, out));
        }
        Ui.add(c, lines(a, l), 10);
        AlertDialog[] d = new AlertDialog[1];
        String all = a.getString(R.string.s2_storage_all_games);
        long n = s.bytes[k.ordinal()];
        switch (k) {
            case SHADERS_OLD: {
                long ok = AppStorageReport.oldLibsDeletable(s, null);
                if (ok < n) Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_old_libs_keep)), 10);
                if (s.outside[k.ordinal()] > 0) Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_old_libs_shared)), 10);
                if (ok > 0) action(a, c, a.getString(R.string.s2_storage_del_old_libs, size(a, ok)), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_old_libs_msg, size(a, ok), all), a.getString(R.string.s2_storage_delete),
                        () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            }
            case PIPELINES:
                action(a, c, a.getString(R.string.s2_storage_del_pipelines, size(a, n)), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_pipelines_msg, size(a, n), all), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case GAME_TEMP:
                action(a, c, a.getString(R.string.s2_storage_del_temp, size(a, n)), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_temp_msg, size(a, n), all), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case LOGS:
                action(a, c, a.getString(R.string.s2_storage_del_logs), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_logs_msg, size(a, n)), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case CAPTURES:
                action(a, c, a.getString(R.string.s2_storage_del_captures), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_captures_msg, size(a, n)), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case CACHE:
                action(a, c, a.getString(R.string.s2_storage_del_cache), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_cache_msg, size(a, n)), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case PREPARE_SCAN:
                action(a, c, a.getString(R.string.s2_storage_del_prepare), Ui.Kind.TONAL, () -> confirm(a, a.getString(k.title),
                        a.getString(R.string.s2_storage_del_prepare_msg, size(a, n)), a.getString(R.string.s2_storage_delete), () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, k, null))));
                break;
            case LEFTOVERS:
                action(a, c, a.getString(R.string.s2_storage_clean), Ui.Kind.TONAL, () -> { d[0].dismiss(); clean(a, box); });
                break;
            case PACK_CODE: case SAVES: case BACKUPS:
                Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_per_game)), 10);
                break;
            default:
                break;
        }
        d[0] = Ui.sheet(a, a.getString(k.title), c).setPositiveButton(R.string.s2_storage_close, null).show();
    }

    /** A game: its share by category, where its pack, save and backups are, and what can go */
    private static void game(MainActivity a, LinearLayout box, AppStorageReport.Scan s, AppStorageReport.GameUse u) {
        LinearLayout c = new LinearLayout(a);
        c.setOrientation(LinearLayout.VERTICAL);
        List<String> l = new ArrayList<>();
        l.add(u.id + (u.card == null ? " · " + a.getString(R.string.s2_storage_no_card) : ""));
        l.add(a.getString(R.string.s2_storage_game_value, size(a, u.inApp())));
        for (AppStorageReport.Cat k : AppStorageReport.sorted(u.bytes, u.outside)) {
            long in = u.bytes[k.ordinal()], out = u.outside[k.ordinal()];
            if (in > 0 || out > 0) l.add(a.getString(k.title) + ": " + amount(a, in, out));
        }
        Ui.add(c, lines(a, l), 0);
        List<String> w = new ArrayList<>();
        w.add(a.getString(R.string.s2_storage_where_pack, String.valueOf(u.pack)) + (u.libOk ? "" : " (" + a.getString(R.string.s2_storage_lib_missing) + ")"));
        w.add(a.getString(R.string.s2_storage_where_save, String.valueOf(u.save)));
        if (u.backupsDir != null) w.add(a.getString(R.string.s2_storage_where_backups, u.backupsDir.getPath(),
                a.getResources().getQuantityString(R.plurals.s2_storage_backups_count, u.backups.size(), u.backups.size())));
        Ui.add(c, lines(a, w), 10);
        if (u.running) Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_running_any)), 10);

        AlertDialog[] d = new AlertDialog[1];
        long old = AppStorageReport.oldLibsDeletable(s, u.id), oldIn = u.bytes[AppStorageReport.Cat.SHADERS_OLD.ordinal()];
        if (oldIn > old) Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_old_libs_keep)), 10);
        if (u.outside[AppStorageReport.Cat.SHADERS_OLD.ordinal()] > 0) Ui.add(c, Ui.small(a, a.getString(R.string.s2_storage_old_libs_shared)), 10);
        if (old > 0) action(a, c, a.getString(R.string.s2_storage_del_old_libs, size(a, old)), Ui.Kind.TONAL, () -> confirm(a, u.name,
                a.getString(R.string.s2_storage_del_old_libs_msg, size(a, old), u.name), a.getString(R.string.s2_storage_delete),
                () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, AppStorageReport.Cat.SHADERS_OLD, u.id))));
        long pl = u.bytes[AppStorageReport.Cat.PIPELINES.ordinal()];
        if (pl > 0) action(a, c, a.getString(R.string.s2_storage_del_pipelines, size(a, pl)), Ui.Kind.TONAL, () -> confirm(a, u.name,
                a.getString(R.string.s2_storage_del_pipelines_msg, size(a, pl), u.name), a.getString(R.string.s2_storage_delete),
                () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, AppStorageReport.Cat.PIPELINES, u.id))));
        long tp = u.bytes[AppStorageReport.Cat.GAME_TEMP.ordinal()];
        if (tp > 0) action(a, c, a.getString(R.string.s2_storage_del_temp, size(a, tp)), Ui.Kind.TONAL, () -> confirm(a, u.name,
                a.getString(R.string.s2_storage_del_temp_msg, size(a, tp), u.name), a.getString(R.string.s2_storage_delete),
                () -> run(a, box, d[0], () -> AppStorageReport.delete(a, s, AppStorageReport.Cat.GAME_TEMP, u.id))));
        long lo = u.bytes[AppStorageReport.Cat.LEFTOVERS.ordinal()] + u.outside[AppStorageReport.Cat.LEFTOVERS.ordinal()];
        if (lo > 0) action(a, c, a.getString(R.string.s2_storage_del_leftovers, size(a, lo)), Ui.Kind.TONAL, () -> confirm(a, u.name,
                a.getString(R.string.s2_storage_del_leftovers_msg, size(a, lo), u.name), a.getString(R.string.s2_storage_delete),
                () -> run(a, box, d[0], () -> AppStorageReport.clean(a, u.id).freed)));
        int nb = u.backups.size(), keep = AppStorageReport.KEEP_BACKUPS;
        if (nb > keep) {
            long gone = 0;
            for (int i = keep; i < nb; i++) gone += u.backups.get(i).bytes;   // each backup's manifest has its size: no walk on the main thread
            long g = gone;
            action(a, c, a.getString(R.string.s2_storage_prune_backups, keep), Ui.Kind.TONAL, () -> confirm(a, u.name,
                    a.getString(R.string.s2_storage_prune_backups_msg, nb - keep, u.name, size(a, g), u.backupsDir.getPath(), keep), a.getString(R.string.s2_storage_delete),
                    () -> run(a, box, d[0], () -> AppStorageReport.pruneBackups(u, keep))));
        }
        if (AppStorageReport.packDeletable(s, u)) {
            long pk = u.bytes[AppStorageReport.Cat.PACK_CODE.ordinal()] + u.bytes[AppStorageReport.Cat.SHADERS_CURRENT.ordinal()] + u.bytes[AppStorageReport.Cat.SHADERS_OLD.ordinal()];
            action(a, c, a.getString(R.string.s2_storage_del_pack, size(a, pk)), Ui.Kind.DANGER, () -> confirm(a, u.name,
                    a.getString(R.string.s2_storage_del_pack_msg, u.name, size(a, pk), u.pack.getPath()), a.getString(R.string.s2_storage_delete),
                    () -> run(a, box, d[0], () -> AppStorageReport.deletePack(a, s, u))));
        }
        long sv = u.bytes[AppStorageReport.Cat.SAVES.ordinal()];
        if (u.saveInApp && sv > 0) action(a, c, a.getString(R.string.s2_storage_del_save), Ui.Kind.DANGER, () -> confirm(a, u.name,
                a.getString(R.string.s2_storage_del_save_msg1, u.name, size(a, sv), u.save.getPath()), a.getString(R.string.s2_storage_continue),
                // the second, separate confirmation: only its yes deletes
                () -> confirm(a, a.getString(R.string.s2_storage_del_save_title), a.getString(R.string.s2_storage_del_save_msg2, u.name), a.getString(R.string.s2_storage_del_save_yes),
                        () -> run(a, box, d[0], () -> AppStorageReport.deleteSave(a, u)))));
        d[0] = Ui.sheet(a, u.name, c).setPositiveButton(R.string.s2_storage_close, null).show();
    }

    private static void action(MainActivity a, LinearLayout c, String label, Ui.Kind k, Runnable r) {
        Ui.add(c, Ui.button(a, label, k, v -> r.run()), 12, Ui.wrap());
    }

    /** Asks before something is deleted: the yes button in the danger color, Cancel the default */
    private static void confirm(MainActivity a, String title, String msg, String yes, Runnable r) {
        AlertDialog d = new AlertDialog.Builder(a).setTitle(title).setMessage(msg).setPositiveButton(yes, (x, w) -> r.run())
                .setNegativeButton(android.R.string.cancel, null).create();
        d.setOnShowListener(x -> {
            Button b = d.getButton(AlertDialog.BUTTON_POSITIVE);
            if (b != null) b.setTextColor(Ui.col(a, R.color.bn_danger));
            Button n = d.getButton(AlertDialog.BUTTON_NEGATIVE);
            if (n != null) n.requestFocus();
        });
        d.show();
    }

    interface Work { long run() throws IOException; }

    /** Runs a deletion on a thread behind a wait dialog, says what it freed (or why it did not), then measures again */
    private static void run(MainActivity a, LinearLayout box, AlertDialog parent, Work w) {
        if (parent != null) parent.dismiss();
        AlertDialog wait = new AlertDialog.Builder(a).setMessage(R.string.s2_storage_working).setCancelable(false).show();
        Context app = a.getApplicationContext();
        new Thread(() -> {
            String msg;
            try {
                long n = w.run();
                msg = n > 0 ? app.getString(R.string.s2_storage_deleted, size(app, n)) : app.getString(R.string.s2_storage_cleaned_none);
            } catch (AppStorageReport.Blocked b) {
                msg = app.getString(b.text);
            } catch (IOException | RuntimeException e) {
                msg = app.getString(R.string.s2_storage_delete_failed, String.valueOf(e.getMessage()));
            }
            String m = msg;
            a.runOnUiThread(() -> {
                try { wait.dismiss(); } catch (RuntimeException e) { /* the window went */ }
                if (a.isDestroyed()) return;
                last = null;
                new AlertDialog.Builder(a).setMessage(m).setPositiveButton(android.R.string.ok, null).show();
                measure(a, box);
            });
        }, "nx-storage-delete").start();
    }

    /** Clean up leftovers: the launcher start's automatic cleanup, now */
    private static void clean(MainActivity a, LinearLayout box) {
        run(a, box, null, () -> AppStorageReport.clean(a.getApplicationContext(), null).freed);
    }
}
