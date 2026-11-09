package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.os.SystemClock;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;

/**
 * A game's Export shaders… and Import shaders… (its Options menu, its settings' Preparation, Prepare's question), over ShaderZip: only the translated shader
 * library, as a .zip, so a phone plays with shaders translated on a computer (scripts/shaders_zip.py) or on another phone, and translates none. Export writes
 * swap2-shaders-&lt;id&gt;-&lt;version&gt;-v-&lt;V&gt;.zip into Switch2/Shaders (kept when the app is uninstalled) or a folder the user picks; Import lists the zips of the
 * game in Switch2/Shaders and Download, or takes one from the system picker (by its path when it has one, else read as a stream: Recent and Downloads work too),
 * and puts the library into the game's pack folder (ShaderZip.install), or, with no pack yet, into the app's packs/&lt;id&gt;, where Prepare then only rewrites
 * the code (PackService skips the shader steps: ShaderZip.ready). Both show their progress with Cancel, and keep the screen on while they work; they share the
 * whole-pack export's busy lock (PackUi), so Play waits, and refuse while the game runs or its Prepare job translates into that pack.
 */
final class ShaderUi {
    static final int PICK_SHADERS_ZIP = 43, PICK_SHADERS_DIR = 44;
    static final Uri SHADERS_URI = Uri.parse("content://com.android.externalstorage.documents/document/primary%3ASwitch2%2FShaders");
    private static Game pending;

    private ShaderUi() {}

    private static boolean ready(MainActivity a, Game g) {
        if (a.needAccess()) return false;
        if (PackUi.busy(g.titleId)) { a.error(a.getString(R.string.s2_shaders_err_working, g.name)); return false; }
        if (SaveUi.gameRunning(a, g)) { a.error(a.getString(R.string.s2_shaders_err_running, g.name)); return false; }
        return true;
    }

    /** The Switch2/Shaders folder (Switch2Layout.shadersDir) */
    static File shadersDir() { return Switch2Layout.shadersDir(Switch2Layout.root()); }

    /** Whether the game has a library Export shaders… would take (cheap: by its path; ShaderZip.chooseExport decides) */
    static boolean canExport(Game g) {
        File pd = new File(g.packDir);
        return Pack.libraryOf(pd) != null || !Pack.libraryVersions(pd).isEmpty();
    }

    // ---- Export ----

    static void exportPick(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        File lib;
        try {
            lib = ShaderZip.chooseExport(new File(g.packDir), g.titleId);
        } catch (ShaderZip.Failure f) {
            a.error(message(a, g, f, true));
            return;
        }
        String v = lib.getParentFile().getName().substring(2);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(box, Ui.small(a, a.getString(R.string.s2_shaders_export_note)), 0);
        if (!v.equals(BuildConfig.NX_DMSH_VK_CHAIN)) Ui.add(box, Ui.body(a, a.getString(R.string.s2_shaders_exported_older, v)), 12);
        AlertDialog[] d = new AlertDialog[1];
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_export_switch2), Ui.Kind.TONAL, x -> { d[0].dismiss(); exportRun(a, g, shadersDir()); }), 16);
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_export_other), Ui.Kind.SOFT, x -> {
            d[0].dismiss();
            pending = g;
            a.pickFolder(PICK_SHADERS_DIR, a.getString(R.string.s2_shaders_export_where, g.name));
        }), 8);
        d[0] = Ui.sheet(a, a.getString(R.string.s2_shaders_export_where, g.name), box).setNegativeButton(android.R.string.cancel, null).show();
    }

    private static void exportRun(MainActivity a, Game g, File dir) {
        if (!ready(a, g)) return;
        File pack = new File(g.packDir);
        String app = BuildConfig.VERSION_NAME + "/" + BuildConfig.VERSION_CODE;
        run(a, g, a.getString(R.string.s2_shaders_exporting, g.name), p -> ShaderZip.export(pack, g.titleId, dir, app, BuildConfig.NX_XLATE_SOURCE, p), (r, f, gone) -> {
            if (gone) return;   // the activity was recreated meanwhile (a theme or language change): the zip is written, nothing to show on a window that is gone
            if (f != null) { a.error(message(a, g, f, true)); return; }
            ShaderZip.Exported e = (ShaderZip.Exported) r;
            String text = a.getString(R.string.s2_shaders_exported_message, e.zip.getPath(), SaveStore.size(e.size), e.shaders, e.version);
            if (e.reused) text += "\n\n" + a.getString(R.string.s2_shaders_exported_same);
            if (!e.version.equals(BuildConfig.NX_DMSH_VK_CHAIN)) text += "\n\n" + a.getString(R.string.s2_shaders_exported_older, e.version);
            new AlertDialog.Builder(a).setTitle(R.string.s2_shaders_exported_title).setMessage(text).setPositiveButton(android.R.string.ok, null).show();
        });
    }

    // ---- Import ----

    static void importPick(MainActivity a, Game g) {
        if (!ready(a, g)) return;
        String why = Profile.missing(g.titleId, g.name);
        if (why != null) { a.error(why); return; }
        if (translating(a, g, target(a, g))) { a.error(a.getString(R.string.s2_shaders_err_busy, g.name)); return; }
        List<File> zips = ShaderZip.found(g.titleId, shadersDir(), Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS));
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(box, Ui.small(a, a.getString(R.string.s2_shaders_import_note)), 0);
        AlertDialog[] d = new AlertDialog[1];
        if (zips.isEmpty()) Ui.add(box, Ui.body(a, a.getString(R.string.s2_shaders_none_found)), 12);
        List<String> labels = ShaderZip.labels(zips);
        for (int i = 0; i < zips.size(); i++) {
            File z = zips.get(i);
            Ui.add(box, Ui.button(a, labels.get(i), i == 0 ? Ui.Kind.TONAL : Ui.Kind.SOFT, x -> { d[0].dismiss(); importRun(a, g, z, null, null); }), i == 0 ? 16 : 8);
        }
        Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_pick_file), Ui.Kind.SOFT, x -> {
            d[0].dismiss();
            pending = g;
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
            i.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed", "application/octet-stream", "*/*"});
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, shadersDir().isDirectory() ? SHADERS_URI : MainActivity.SWITCH2_URI);
            a.startActivityForResult(i, PICK_SHADERS_ZIP);
        }), 12);
        d[0] = Ui.sheet(a, a.getString(R.string.s2_shaders_import_from, g.name), box).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** Where an import of this game goes: its card's pack folder when that holds its pack (Play and Prepare use it), else the app's packs/&lt;id&gt; */
    static File target(MainActivity a, Game g) {
        File pd = new File(g.packDir);
        try {
            if (Pack.read(pd).titleId.equals(g.titleId)) return pd;
        } catch (IOException e) {
            // no pack there yet
        }
        return AppStorage.pack(a, g.titleId);
    }

    /** The Prepare job that writes into this pack folder, null when none (the launcher's remembered job, else the one in the dump's work folder) */
    private static Job jobFor(MainActivity a, Game g, File pack) {
        File gd = new File(g.gameDir);
        File[] files = {Job.remembered(a), Ondevice.isDump(gd) ? Job.fileOf(DumpCheck.workOf(gd, g.titleId)) : null};
        for (File f : files) {
            if (f == null || !f.isFile()) continue;
            try {
                Job j = Job.read(f);
                if (SaveStore.same(j.pack(), pack) && j.titleId().equals(g.titleId)) return j;
            } catch (IOException e) {
                // a damaged job.json: no job
            }
        }
        return null;
    }

    /** Whether this game's Prepare is translating into that pack now (the service runs it): paused, failed and pending jobs are left as they are, and skip the shader steps when resumed */
    private static boolean translating(MainActivity a, Game g, File pack) {
        PrepareState s = Ondevice.state();
        Job j = jobFor(a, g, pack);
        return j != null && "running".equals(j.state()) && s != null && s.isFor(j.dump().getPath()) && s.canPause;
    }

    /** MainActivity.onActivityResult, before a folder's path is read: the .zip picked for Import shaders… */
    static boolean documentResult(MainActivity a, int request, Uri doc) {
        if (request != PICK_SHADERS_ZIP) return false;
        Game g = pending;
        pending = null;
        if (g == null) return true;
        String p = PathUtil.documentToPath(doc);
        File f = p == null ? null : new File(p);
        if (f != null && f.isFile() && f.canRead()) importRun(a, g, f, null, null);
        else importRun(a, g, null, doc, displayName(a, doc));
        return true;
    }

    private static String displayName(MainActivity a, Uri doc) {
        try (Cursor c = a.getContentResolver().query(doc, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getString(0);
        } catch (RuntimeException e) {
            // a provider without the column
        }
        String s = doc.getLastPathSegment();
        return s == null ? "the .zip" : s;
    }

    /** MainActivity.onActivityResult: the folder picked for Export shaders… */
    static boolean activityResult(MainActivity a, int request, File dir) {
        if (request != PICK_SHADERS_DIR) return false;
        Game g = pending;
        pending = null;
        if (g != null) exportRun(a, g, dir);
        return true;
    }

    /** Imports a zip: a file (read by name: the entries' order does not matter), or a document's stream (doc, its name) */
    private static void importRun(MainActivity a, Game g, File zip, Uri doc, String docName) {
        if (!ready(a, g)) return;
        File gd = new File(g.gameDir);
        run(a, g, a.getString(R.string.s2_shaders_importing, g.name), p -> {
            File target = target(a, g);
            if (translating(a, g, target)) throw new ShaderZip.Failure(ShaderZip.Why.BUSY, "its Prepare job translates into " + target);
            ShaderZip.Target t = new ShaderZip.Target(target, g.titleId);
            // User-picked Banana Native exports may have a different shader version.
            // Only the same title, file format and Vulkan library ABI can be used.
            t.allowCompatibleFallback = true;
            ShaderZip.Staged s;
            if (zip != null) s = ShaderZip.read(zip, t, p);
            else try (InputStream in = a.getContentResolver().openInputStream(doc)) {
                if (in == null) throw ShaderZip.io("cannot open " + doc, ShaderZip.IO_OPEN, docName);
                s = ShaderZip.read(in, docName, t, p);
            }
            if (SaveUi.gameRunning(a, g)) { ShaderZip.unstage(s); throw new ShaderZip.Failure(ShaderZip.Why.RUNNING, g.name + " was started meanwhile", g.name); }
            p.at(ShaderZip.INSTALL, 0, 1);
            return ShaderZip.install(s, t);
        }, (r, f, gone) -> {
            if (f != null) { if (!gone) a.error(message(a, g, f, false)); return; }
            ShaderZip.Result res = (ShaderZip.Result) r;
            // the card looks where Prepare writes its pack: this entry only (another entry of the title, another dump with its own pack, keeps its pack)
            if (!res.hadPack && !SaveStore.same(new File(g.packDir), res.packDir)) Folders.setPackOf(a, g.titleId, g.gameDir, res.packDir);
            if (gone) return;   // the activity was recreated meanwhile: the new one shows the card from the saved list
            a.refresh();
            AlertDialog.Builder b = new AlertDialog.Builder(a).setTitle(R.string.s2_shaders_imported_title);
            if (!res.version.equals(BuildConfig.NX_DMSH_VK_CHAIN)) {
                // Another version is a fallback, not a freshly prepared GMEM_FAST1 library.
                // Do not offer automatic Prepare here: it may translate all shaders again.
                b.setMessage(a.getString(R.string.s2_shaders_imported_fallback, res.shaders, res.version))
                        .setPositiveButton(android.R.string.ok, null).show();
                return;
            }
            if (res.hadPack && ShaderZip.ready(res.packDir, g.titleId)) {
                b.setMessage(a.getString(R.string.s2_shaders_imported_ready, res.shaders, res.version)).setPositiveButton(android.R.string.ok, null).show();
                return;
            }
            Job j = jobFor(a, g, res.packDir);
            String st = j == null ? "" : j.state();
            String text = a.getString(R.string.s2_shaders_imported_prepare, res.shaders, res.version);
            if (st.equals("paused") || st.equals("failed") || st.equals("pending")) text += "\n\n" + a.getString(R.string.s2_shaders_imported_resume);
            b.setMessage(text);
            if (Ondevice.isDump(gd)) b.setPositiveButton(R.string.s2_shaders_prepare_now, (x, w) -> Ondevice.prepare(a, gd, false)).setNegativeButton(android.R.string.cancel, null);
            else b.setPositiveButton(android.R.string.ok, null);
            b.show();
        });
    }

    /**
     * adb, test app only (android/TESTING.md "Shader zips"): am start -n &lt;package&gt;/dev.nxnative.android.MainActivity --es shaders_title &lt;title ID&gt;
     * [--es shaders_game &lt;game folder or .nup&gt;] (--es shaders_export &lt;folder&gt; | --es shaders_import &lt;.zip&gt;) runs Export shaders… into that folder or
     * Import shaders… of that zip for the listed game of that title (the entry of that game path, else the first), without the pickers, with the same checks
     */
    static void fromIntent(MainActivity a, Intent i) {
        String id = i.getStringExtra("shaders_title"), gp = i.getStringExtra("shaders_game"), ex = i.getStringExtra("shaders_export"), im = i.getStringExtra("shaders_import");
        if (BuildConfig.NX_PLAY || id == null || ex == null && im == null) return;
        i.removeExtra("shaders_export");   // not again when the activity is recreated with the same intent
        i.removeExtra("shaders_import");
        for (Game g : Game.load(a)) {
            if (!g.titleId.equals(id) || gp != null && !g.gameDir.equals(gp)) continue;
            if (ex != null) exportRun(a, g, new File(ex));
            else importRun(a, g, new File(im), null, null);
            return;
        }
        a.error("No game of " + id + " in the list.");
    }

    // ---- Messages ----

    private static String arg(ShaderZip.Failure f, int i) { return f.args != null && f.args.length > i && f.args[i] != null ? f.args[i] : ""; }

    /** A failure in the user's language (export: the export's own wording for an I/O error) */
    static String message(MainActivity a, Game g, ShaderZip.Failure f, boolean export) {
        switch (f.why) {
            case NOT_SHADER_ZIP: return a.getString(R.string.s2_shaders_err_not_zip, arg(f, 0), arg(f, 1));
            case UNSAFE_NAME: return a.getString(R.string.s2_shaders_err_unsafe, arg(f, 0));
            case ORDER: return a.getString(R.string.s2_shaders_err_order);
            case OTHER_GAME: return a.getString(R.string.s2_shaders_err_other_game, arg(f, 0), arg(f, 1));
            case OTHER_VERSION: return a.getString(R.string.s2_shaders_err_other_version, arg(f, 0), arg(f, 1));
            case OTHER_ABI: return a.getString(R.string.s2_shaders_err_other_abi, arg(f, 0), arg(f, 1));
            case OTHER_INPUTS: return a.getString(R.string.s2_shaders_err_other_inputs, arg(f, 0), arg(f, 1));
            case DAMAGED: return export ? a.getString(R.string.s2_shaders_err_export_damaged, arg(f, 0)) : a.getString(R.string.s2_shaders_err_damaged, arg(f, 0));
            case TOO_BIG: return a.getString(R.string.s2_shaders_err_too_big, arg(f, 0));
            case NO_SPACE: return a.getString(R.string.s2_shaders_err_space, arg(f, 0), arg(f, 1), arg(f, 2));
            case NO_LIBRARY: return a.getString(R.string.s2_shaders_err_none, g.name);
            case BUSY: return a.getString(R.string.s2_shaders_err_busy, g.name);
            case RUNNING: return a.getString(R.string.s2_shaders_err_running, g.name);
            case CANCELLED: return a.getString(R.string.s2_shaders_err_cancelled);
            default: return export ? a.getString(R.string.s2_shaders_err_export, io(a, f)) : a.getString(R.string.s2_shaders_err_io, io(a, f));
        }
    }

    /** An I/O failure's detail: ShaderZip's own (ShaderZip.io: {kind, path}) in the user's language, else the system's message as it is */
    private static String io(MainActivity a, ShaderZip.Failure f) {
        String path = arg(f, 1);
        switch (arg(f, 0)) {
            case ShaderZip.IO_INSIDE: return a.getString(R.string.s2_shaders_io_inside, path);
            case ShaderZip.IO_CHANGED_READ: return a.getString(R.string.s2_shaders_io_changed_read, path);
            case ShaderZip.IO_CREATE: return a.getString(R.string.s2_shaders_io_create, path);
            case ShaderZip.IO_CHANGED_WRITTEN: return a.getString(R.string.s2_shaders_io_changed_written, path);
            case ShaderZip.IO_READ_BACK: return a.getString(R.string.s2_shaders_io_read_back, path);
            case ShaderZip.IO_NAME_ZIP: return a.getString(R.string.s2_shaders_io_name_zip, path);
            case ShaderZip.IO_NOTHING_STAGED: return a.getString(R.string.s2_shaders_io_nothing_staged);
            case ShaderZip.IO_MOVE_ASIDE: return a.getString(R.string.s2_shaders_io_move_aside, path);
            case ShaderZip.IO_NAME_LIB: return a.getString(R.string.s2_shaders_io_name_lib, path);
            case ShaderZip.IO_OPEN: return a.getString(R.string.s2_shaders_io_open, path);
            default: return arg(f, 0);
        }
    }

    // ---- Progress ----

    interface Work { Object run(ShaderZip.Progress p) throws IOException; }
    /** gone: the activity was destroyed (recreated by a configuration change) while the work ran: nothing may be shown on it */
    interface Done { void done(Object result, ShaderZip.Failure failure, boolean gone); }

    /** Runs work off the main thread with a progress dialog (bytes done of the total, Cancel, the screen kept on); done on the main thread */
    private static void run(MainActivity a, Game g, String title, Work work, Done done) {
        if (!PackUi.take(g.titleId)) { a.error(a.getString(R.string.s2_shaders_err_working, g.name)); return; }
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        TextView phase = Ui.body(a, title), count = Ui.small(a, "");
        ProgressBar bar = Ui.progress(a);
        bar.setMax(1000);
        bar.setIndeterminate(true);
        Ui.add(box, phase, 0);
        Ui.add(box, bar, 12, new LinearLayout.LayoutParams(-1, Ui.dp(a, 8)));
        Ui.add(box, count, 8);
        java.util.concurrent.atomic.AtomicBoolean cancel = new java.util.concurrent.atomic.AtomicBoolean();
        AlertDialog w = Ui.sheet(a, title, box).setCancelable(false).setNegativeButton(android.R.string.cancel, null).create();
        w.setOnShowListener(x -> w.getButton(AlertDialog.BUTTON_NEGATIVE).setOnClickListener(v -> { cancel.set(true); v.setEnabled(false); }));   // stays open until the worker stops
        w.show();
        a.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        String checking = a.getString(R.string.s2_shaders_checking);
        ShaderZip.Progress p = new ShaderZip.Progress() {
            private long last;
            @Override public void at(int ph, long d, long total) {
                long now = SystemClock.elapsedRealtime();
                if (now - last < 100 && d < total) return;   // about 10 updates a second
                last = now;
                a.runOnUiThread(() -> {
                    phase.setText(ph == ShaderZip.CHECK ? checking : title);
                    if (total > 0) {
                        bar.setIndeterminate(false);
                        bar.setProgress((int) (d * 1000 / total));
                        count.setText(a.getString(R.string.s2_shaders_progress, SaveStore.size(d), SaveStore.size(total)));
                    }
                });
            }
            @Override public boolean cancelled() { return cancel.get(); }
        };
        new Thread(() -> {
            ShaderZip.Failure err = null;
            Object r = null;
            try { r = work.run(p); }
            catch (ShaderZip.Failure e) { err = e; }
            catch (IOException | RuntimeException e) { err = new ShaderZip.Failure(ShaderZip.Why.IO, String.valueOf(e.getMessage()), String.valueOf(e.getMessage())); }
            ShaderZip.Failure fe = err;
            Object fr = r;
            a.runOnUiThread(() -> {
                PackUi.give(g.titleId);
                // a uiMode, locale or density change recreates the activity (rotation does not: configChanges): its window and dialog are gone, so they are left alone
                boolean gone = a.isDestroyed() || a.isFinishing();
                if (!gone) {
                    a.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    if (w.isShowing()) w.dismiss();
                }
                done.done(fr, fe, gone);
            });
        }, "nx-shader-zip").start();
    }
}
