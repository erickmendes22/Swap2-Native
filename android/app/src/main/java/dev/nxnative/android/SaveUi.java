package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.util.Log;
import android.widget.LinearLayout;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * A game's saves (its Options menu and its settings' Saves), over SaveStore and SaveZip: Back up save (a checked copy kept by the app), Restore a backup… (one of the
 * app's own backups, listed by date: never a folder), Import save from another emulator… (a .zip: SaveZip finds this game's save in it) and Export save… (the save
 * as a .zip that Import takes, for another phone or emulator). The save folder is the one the game's next start uses (Folders.save: the app's saves/&lt;id&gt;, the
 * old default beside the game until it is copied in, or the picked one); the backups go to &lt;Switch2&gt;/save-backups/&lt;id&gt;/ and the exported zips into the
 * Switch2 folder or a picked one, on shared storage, so they outlive an uninstall. Each refuses while a game runs (its process holds the save's lock): the host may
 * be writing the save. While one works, Play waits for it (busy). Nothing here deletes a backup.
 */
final class SaveUi {
    static final int PICK_IMPORT_ZIP = 30, PICK_EXPORT_DIR = 31;
    private static final String TAG = "Swap2Native";
    private static final Set<String> busy = new HashSet<>();
    private static Game importFor, exportFor;

    private SaveUi() {}

    /** Whether a save operation of this game is running (MainActivity.launch waits) */
    static synchronized boolean busy(String titleId) { return busy.contains(titleId); }

    private static synchronized boolean take(String titleId) { return busy.add(titleId); }

    private static synchronized void give(String titleId) { busy.remove(titleId); }

    /**
     * Whether the game of this save runs now: its process holds the save's lock (GameActivity takes &lt;save&gt;.lock before the save is used and keeps it while the
     * process lives, and the kernel lets it go when the process ends, also after a crash). A :game process left idle, or another game's, does not count
     */
    static boolean gameRunning(Context c, Game g) { return SaveStore.inUse(Folders.save(c, g)); }

    static String stamp() { return new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date()); }

    static File backups(Game g) { return Prefs.backupsDir(new File(g.gameDir), g.titleId); }

    private static boolean ready(MainActivity a, Game g) {
        if (a.needAccess()) return false;
        if (busy(g.titleId)) { a.error(a.getString(R.string.s2_save_err_working, g.name)); return false; }
        if (gameRunning(a, g)) { a.error(a.getString(R.string.s2_save_err_running, g.name)); return false; }
        return true;
    }

    /** Whether the save (main or device) holds a file */
    private static boolean hasSave(File save) {
        if (save == null) return false;
        for (File p : SaveStore.parts(save).values()) if (SaveStore.hasFiles(p)) return true;
        return false;
    }

    /** Runs work off the main thread with a wait dialog; done gets the result or the error (not called when the activity is gone meanwhile) */
    private static void run(MainActivity a, Game g, String wait, Work work, Done done) {
        if (!take(g.titleId)) { a.error(a.getString(R.string.s2_save_err_working, g.name)); return; }
        AlertDialog w = new AlertDialog.Builder(a).setMessage(wait).setCancelable(false).show();
        new Thread(() -> {
            IOException err = null;
            Object r = null;
            try { r = work.run(); } catch (IOException e) { err = e; } catch (RuntimeException e) { err = new IOException(String.valueOf(e.getMessage()), e); }
            IOException fe = err;
            Object fr = r;
            a.runOnUiThread(() -> {
                give(g.titleId);
                if (a.isDestroyed() || a.isFinishing()) return;   // recreated meanwhile (a theme or language change): the work is done, its window is gone
                if (w.isShowing()) w.dismiss();
                done.done(fr, fe);
            });
        }, "nx-save").start();
    }

    interface Work { Object run() throws IOException; }
    interface Done { void done(Object result, IOException error); }

    // ---- Back up save ----

    static void backup(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        File save = Folders.save(a, g);
        if (!hasSave(save)) { a.error(a.getString(R.string.s2_save_none, g.name, String.valueOf(save))); return; }
        File to = backups(g);
        run(a, g, a.getString(R.string.s2_save_backing_up, g.name), () -> SaveStore.backup(save, to, stamp()), (r, err) -> {
            if (err != null) { a.error(a.getString(R.string.s2_save_backup_failed, message(a, g, err, false), save.getPath())); return; }
            SaveStore.Backup b = (SaveStore.Backup) r;
            new AlertDialog.Builder(a).setTitle(R.string.s2_save_backed_up_title)
                    .setMessage(a.getString(R.string.s2_save_backed_up, b.files, SaveStore.size(b.bytes), b.device ? a.getString(R.string.s2_save_with_device) : "", b.dir.getPath()))
                    .setPositiveButton(android.R.string.ok, null).show();
        });
    }

    // ---- Restore a backup ----

    /** A backup's date in the user's language: "2026-11-03 14:05:09", and that it was made before a restore */
    private static String when(MainActivity a, SaveStore.Backup b) {
        String w = SaveStore.when(b.name.replace(SaveStore.BEFORE_RESTORE, ""));
        return b.beforeRestore() ? w + a.getString(R.string.s2_save_backup_auto) : w;
    }

    static void restoreList(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        File to = backups(g);
        List<SaveStore.Backup> l = SaveStore.list(to);
        if (l.isEmpty()) { a.error(a.getString(R.string.s2_save_no_backups, g.name, to.getPath())); return; }
        String[] labels = new String[l.size()];
        for (int i = 0; i < labels.length; i++) {
            SaveStore.Backup b = l.get(i);
            String from = b.source.isEmpty() ? "" : "\n" + a.getString(R.string.s2_save_backup_from, new File(b.source).getParentFile().getName() + "/" + new File(b.source).getName());
            labels[i] = when(a, b) + "\n" + a.getString(R.string.s2_save_files, b.files, SaveStore.size(b.bytes), b.device ? a.getString(R.string.s2_save_with_device) : "") + from;
        }
        new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_save_restore_from, g.name)).setItems(labels, (d, w) -> confirmRestore(a, g, l.get(w)))
                .setNegativeButton(android.R.string.cancel, null).show();
    }

    private static void confirmRestore(MainActivity a, Game g, SaveStore.Backup b) {
        File save = Folders.save(a, g);
        String why = SaveStore.refuseSource(b.dir, save);
        if (why != null) { a.error(a.getString(R.string.s2_save_restore_failed, why, save.getPath())); return; }
        String st = stamp();
        String msg = a.getString(R.string.s2_save_restore_confirm, save.getPath(), when(a, b)) + "\n\n" + firstBackup(a, g, save, st);
        Ui.confirmDanger(a, a.getString(R.string.s2_save_restore_confirm_title, g.name), msg, a.getString(R.string.s2_save_restore_yes), () -> {
            if (!ready(a, g)) return;
            run(a, g, a.getString(R.string.s2_save_restoring, g.name), () -> SaveStore.restore(b.dir, save, backups(g), st), (r, err) -> {
                if (err != null) { a.error(failed(a, R.string.s2_save_restore_failed, message(a, g, err, false), save)); return; }
                done(a, R.string.s2_save_restored, (SaveStore.Restored) r);
            });
        });
    }

    /** What happens to the current save first: its automatic, checked backup, or nothing when it is empty */
    private static String firstBackup(MainActivity a, Game g, File save, String st) {
        return hasSave(save) ? a.getString(R.string.s2_save_backup_first, new File(backups(g), st + SaveStore.BEFORE_RESTORE).getPath()) : a.getString(R.string.s2_save_import_empty);
    }

    private static String failed(MainActivity a, int text, String why, File save) {
        String s = a.getString(text, why, save.getPath());
        return SaveStore.pending(save) ? s + "\n\n" + a.getString(R.string.s2_save_pending) : s;
    }

    private static void done(MainActivity a, int text, SaveStore.Restored x) {
        String s = a.getString(text, x.now.files, SaveStore.size(x.now.bytes), x.parts.contains(SaveStore.DEVICE) ? a.getString(R.string.s2_save_with_device) : "");
        if (x.before != null) s += " " + a.getString(R.string.s2_save_old_in, x.before.dir.getPath());
        Toast.makeText(a, s, Toast.LENGTH_LONG).show();
    }

    // ---- Import save from another emulator (a .zip) ----

    static void importPick(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        String tid = g.titleId.toUpperCase(Locale.ROOT);
        List<File> zips = SaveZip.found(g.titleId, Switch2Layout.root(), Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS));
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(box, Ui.small(a, a.getString(R.string.s2_save_import_how, tid)), 0);
        if (zips.isEmpty()) Ui.add(box, Ui.body(a, a.getString(R.string.s2_save_import_none_found, tid)), 12);
        AlertDialog[] d = new AlertDialog[1];
        for (int i = 0; i < zips.size(); i++) {
            File z = zips.get(i);
            String label = z.getName() + "\n" + SaveStore.when(new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date(z.lastModified()))) + " · " + SaveStore.size(z.length());
            Ui.add(box, Ui.button(a, label, i == 0 ? Ui.Kind.TONAL : Ui.Kind.SOFT, x -> { d[0].dismiss(); importRead(a, g, new SaveZip.Source(z)); }), i == 0 ? 16 : 8);
        }
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_pick_file), Ui.Kind.SOFT, x -> {
            d[0].dismiss();
            importFor = g;
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");   // some providers label zips otherwise
            i.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed", "application/octet-stream", "*/*"});
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, MainActivity.SWITCH2_URI);
            a.startActivityForResult(i, PICK_IMPORT_ZIP);
        }), 12);
        d[0] = Ui.sheet(a, a.getString(R.string.s2_save_import_title, g.name), box).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** MainActivity.onActivityResult, before a folder's path is read: the .zip picked for Import save… (by its path when it has one, else read as a stream) */
    static boolean documentResult(MainActivity a, int request, Uri doc) {
        if (request != PICK_IMPORT_ZIP) return false;
        Game g = importFor;
        importFor = null;
        if (g == null) return true;
        String p = PathUtil.documentToPath(doc);
        File f = p == null ? null : new File(p);
        if (f != null && f.isFile() && f.canRead()) { importRead(a, g, new SaveZip.Source(f)); return true; }
        ContentResolver cr = a.getContentResolver();
        importRead(a, g, new SaveZip.Source(() -> {
            InputStream in = cr.openInputStream(doc);
            if (in == null) throw new IOException("cannot open " + doc);
            return in;
        }, displayName(a, doc)));
        return true;
    }

    private static String displayName(MainActivity a, Uri doc) {
        try (Cursor c = a.getContentResolver().query(doc, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getString(0);
        } catch (RuntimeException e) {
            // a provider without the column
        }
        String s = doc.getLastPathSegment();
        return s == null ? ".zip" : s;
    }

    /** Lists the zip and finds this game's save in it; one found is asked about, several are offered first (the likeliest first) */
    private static void importRead(MainActivity a, Game g, SaveZip.Source src) {
        if (!ready(a, g)) return;
        run(a, g, a.getString(R.string.s2_save_reading_zip, src.name), () -> SaveZip.plan(src, g.titleId), (r, err) -> {
            if (err != null) { a.error(a.getString(R.string.s2_save_import_refused, message(a, g, err, false))); return; }
            @SuppressWarnings("unchecked") List<SaveZip.Part> parts = (List<SaveZip.Part>) r;
            if (parts.size() == 1) { confirmImport(a, g, src, parts.get(0)); return; }
            String[] labels = new String[parts.size()];
            for (int i = 0; i < labels.length; i++) labels[i] = partLabel(a, parts.get(i));
            new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_save_import_which, parts.size())).setItems(labels, (d, w) -> confirmImport(a, g, src, parts.get(w)))
                    .setNegativeButton(android.R.string.cancel, null).show();
        });
    }

    /** A part of the zip: its folder, its files and size, its newest file's date */
    private static String partLabel(MainActivity a, SaveZip.Part p) {
        String s = (p.prefix.isEmpty() ? a.getString(R.string.s2_save_zip_top) : p.prefix + "/") + "\n"
                + a.getString(R.string.s2_save_files, p.files, SaveStore.size(p.bytes), p.device != null ? a.getString(R.string.s2_save_with_device) : "");
        if (p.newest > 0) s += " · " + a.getString(R.string.s2_save_newest, SaveStore.when(new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date(p.newest))));
        return s;
    }

    private static void confirmImport(MainActivity a, Game g, SaveZip.Source src, SaveZip.Part p) {
        File save = Folders.save(a, g);
        String st = stamp();
        String msg = a.getString(R.string.s2_save_import_confirm, src.name, partLabel(a, p), save.getPath()) + "\n\n" + firstBackup(a, g, save, st);
        Ui.confirmDanger(a, a.getString(R.string.s2_save_import_confirm_title, g.name), msg, a.getString(R.string.s2_save_import_yes), () -> {
            if (!ready(a, g)) return;
            run(a, g, a.getString(R.string.s2_save_importing, g.name), () -> SaveZip.importZip(src, p, save, backups(g), st), (r, err) -> {
                if (err != null) { a.error(failed(a, R.string.s2_save_import_failed, message(a, g, err, false), save)); return; }
                done(a, R.string.s2_save_imported, (SaveStore.Restored) r);
            });
        });
    }

    // ---- Export save (a .zip) ----

    static void exportPick(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        File save = Folders.save(a, g);
        if (!hasSave(save)) { a.error(a.getString(R.string.s2_save_none, g.name, String.valueOf(save))); return; }
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(box, Ui.small(a, a.getString(R.string.s2_save_export_note)), 0);
        AlertDialog[] d = new AlertDialog[1];
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_save_export_switch2), Ui.Kind.TONAL, x -> { d[0].dismiss(); exportRun(a, g, Switch2Layout.root()); }), 16);
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_export_other), Ui.Kind.SOFT, x -> {
            d[0].dismiss();
            exportFor = g;
            a.pickFolder(PICK_EXPORT_DIR, a.getString(R.string.s2_save_export_where, g.name));
        }), 8);
        d[0] = Ui.sheet(a, a.getString(R.string.s2_save_export_where, g.name), box).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** MainActivity.onActivityResult: the folder picked for Export save… */
    static boolean activityResult(MainActivity a, int request, File dir) {
        if (request != PICK_EXPORT_DIR) return false;
        Game g = exportFor;
        exportFor = null;
        if (g != null) exportRun(a, g, dir);
        return true;
    }

    private static void exportRun(MainActivity a, Game g, File dir) {
        if (!ready(a, g)) return;
        File save = Folders.save(a, g);
        run(a, g, a.getString(R.string.s2_save_exporting, g.name), () -> SaveZip.export(save, g.titleId, dir, stamp()), (r, err) -> {
            if (err != null) { a.error(a.getString(R.string.s2_save_export_failed, message(a, g, err, true), save.getPath())); return; }
            SaveZip.Exported e = (SaveZip.Exported) r;
            new AlertDialog.Builder(a).setTitle(R.string.s2_save_exported_title)
                    .setMessage(a.getString(R.string.s2_save_exported, e.zip.getPath(), e.files, SaveStore.size(e.bytes), e.device ? a.getString(R.string.s2_save_with_device) : ""))
                    .setPositiveButton(android.R.string.ok, null).show();
        });
    }

    // ---- Messages ----

    private static String arg(SaveZip.Failure f, int i) { return f.args != null && f.args.length > i && f.args[i] != null ? f.args[i] : ""; }

    /** An error in the user's language: SaveZip's own failures worded here, else the detail as SaveStore gives it */
    static String message(MainActivity a, Game g, IOException e, boolean export) {
        if (!(e instanceof SaveZip.Failure)) return String.valueOf(e.getMessage());
        SaveZip.Failure f = (SaveZip.Failure) e;
        Log.w(TAG, g.titleId + ": " + f.why + ": " + f.getMessage());   // the detail in English (a zip reader's own words), for the log only
        String tid = g.titleId.toUpperCase(Locale.ROOT);
        switch (f.why) {
            case NOT_ZIP: return a.getString(R.string.s2_save_err_not_zip, arg(f, 0));
            case UNSAFE_NAME: return a.getString(R.string.s2_save_err_unsafe, arg(f, 0));
            case DUPLICATE: return a.getString(R.string.s2_save_err_duplicate, arg(f, 0));
            case NONE_FOUND: return a.getString(R.string.s2_save_err_none_found, g.name, arg(f, 0), tid);
            case TOO_BIG: return export ? a.getString(R.string.s2_save_err_save_too_big, arg(f, 0), arg(f, 1), arg(f, 2))
                    : a.getString(R.string.s2_save_err_too_big, arg(f, 0).isEmpty() ? "/" : arg(f, 0), arg(f, 1), arg(f, 2));
            case ZIP_TOO_BIG: return a.getString(R.string.s2_save_err_zip_too_big, arg(f, 0));
            case TOO_MANY: return a.getString(R.string.s2_save_err_too_many, arg(f, 0));
            case FILE_TOO_BIG: return a.getString(R.string.s2_save_err_file_too_big, arg(f, 0), arg(f, 1));
            case NO_SPACE: return a.getString(R.string.s2_save_err_space, arg(f, 0), arg(f, 1), arg(f, 2));
            case NO_SAVE: return a.getString(R.string.s2_save_none, g.name, arg(f, 0));
            case READ_BACK: return a.getString(R.string.s2_save_err_read_back, arg(f, 0));
            case CHANGED: return a.getString(R.string.s2_save_err_changed, arg(f, 0));
            default: return String.valueOf(e.getMessage());
        }
    }
}
