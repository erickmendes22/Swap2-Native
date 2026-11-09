package dev.nxnative.android;

import android.Manifest;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.RemoteException;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Locale;

/**
 * Preparing a game on the phone. "+ Add game" (MainActivity) on a dump without a usable pack calls {@link #prepare}: the dump is checked (DumpCheck), a pack
 * beside it is checked against it (PackCheck: game build, shader library, rewriter) and what does not fit is redone, else the whole job runs; PackService runs it,
 * and this card shows it on the main screen while there is one: its state (needs preparing, preparing N of 22,852 shaders, paused and why, stopped with an error
 * and what to do), a progress bar, Pause / Resume / Retry, and ⋯ Manage (forget, delete) away from them. When the job is done the game goes into the game list
 * with its pack and the card goes away: Play is on the game's card.
 * <p>
 * The folder is picked with the Storage Access Framework's tree picker and turned into its /storage path (PathUtil); everything after that is read by path with All
 * files access, as the host does. The SAF picker is the familiar system UI and needs no path typed; reading through the SAF (DocumentFile / ContentResolver) instead
 * would be one binder call per file for a RomFS of 158,000 files, and the tools (CPython, the translator) need POSIX paths in any case.
 * <p>
 * Progress comes from the service over a bound Messenger while it runs, otherwise from job.json (read every second while the screen shows).
 */
final class Ondevice {
    static final int PICK_DUMP = 100, ASK_NOTIFY = 101, PREPARE_SCREEN = 102;
    private static Panel panel;
    private static PrepareState current;   // the job's last state, for the library's mini summary (null: no game being prepared)
    private static java.util.function.Consumer<PrepareState> listener;

    private Ondevice() {}

    /** The job's state for the library (docs/SWAP2-NATIVE-PREPARE-FLOW.md): the game being prepared, null when there is none (or its finished game is in the list) */
    static PrepareState state() { return current; }

    /** One listener (the library) for every change of state(), on the main thread; null stops */
    static void listen(java.util.function.Consumer<PrepareState> l) { listener = l; }

    private static boolean openPending;   // the notification asked for the preparation screen before the job's state was known (a launcher started cold)

    private static void publish(PrepareState s) {
        current = s;
        if (listener != null) listener.accept(s);
        if (openPending && s != null && panel != null) { openPending = false; openScreen(panel.a); }
    }

    /**
     * The job logic for the library (MainActivity). Swap2-Native: it no longer shows a card of its own in the library (the preparation screen, PrepareActivity,
     * and the game card's mini summary show the job); root and index are kept for the callers
     */
    static void attach(MainActivity a, LinearLayout root, int index) {
        if (panel != null) panel.detach();
        panel = new Panel(a);
    }

    /**
     * Jogar on a game that needs preparing (docs/SWAP2-NATIVE-PREPARE-FLOW.md): the dump is checked, the job is started (or the one for it resumed), and the
     * preparation screen opens. A problem is one message, and the screen does not open
     */
    static void play(MainActivity a, File dump) {
        if (panel == null || panel.a != a) return;
        panel.screen = true;
        panel.autoPlay = false;
        panel.picked(dump, true, null);
    }

    /**
     * Jogar on a game whose code no longer fits while its shader library does (its mods changed, a pack made on another device, another game build: GameFlow's
     * auto): the code is rewritten in a short job with no question (Job.adopt, code only), the short progress screen shows it, and the game starts when it is
     * done (PrepareActivity.EXTRA_AUTOPLAY). again: a pack whose code other tools made is rewritten too
     */
    static void fixCodeThenPlay(MainActivity a, File dump, File pack, boolean again) {
        if (panel == null || panel.a != a) return;
        panel.screen = true;
        panel.autoPlay = true;
        panel.picked(dump, true, pack, again, false, true);
    }

    /**
     * Continue / Try again on a game's card: its own job is started again as it is (never rebuilt or replaced) and its preparation screen opens. Not beside an
     * export or import of the game (said in a Toast)
     */
    static void resumeJob(MainActivity a, PrepareState s) {
        if (s == null || panel == null || panel.a != a || a.needAccess() || importBusy(a, s.titleId, true)) return;
        Job.remember(a, s.file);
        panel.load();
        panel.screen = true;
        panel.autoPlay = false;
        try {
            Job j = Job.read(s.file);
            panel.job = j;
            panel.startService(j);
        } catch (IOException e) {
            android.util.Log.e("nxpack", "resume " + s.file + ": " + e.getMessage());
            android.widget.Toast.makeText(a, a.getString(R.string.s2_why_unreadable), android.widget.Toast.LENGTH_LONG).show();
        }
    }

    /** The preparation screen for the job there is (the mini summary's tap) */
    static void openScreen(MainActivity a) {
        if (current == null) return;
        a.startActivityForResult(new Intent(a, PrepareActivity.class), PREPARE_SCREEN);
    }

    /** The preparation screen of a game's own job (its card's View preparation, Options' View preparation): that job becomes the one the launcher follows */
    static void openScreen(MainActivity a, PrepareState s) {
        if (s == null || panel == null || panel.a != a) { openScreen(a); return; }
        if (current == null || !current.file.equals(s.file)) {
            Job.remember(a, s.file);
            panel.load();
            panel.show();
        }
        a.startActivityForResult(new Intent(a, PrepareActivity.class), PREPARE_SCREEN);
    }

    /**
     * Every game's own job (its job.json in its work folder, DumpCheck.workOf) and the remembered one, the newest first: the launcher's recovery and autoUpdate
     * look at all of them, not only the one it follows. Reads a few small files: off the main thread where it can be
     */
    static List<Job> gameJobs(android.content.Context c) {
        java.util.LinkedHashMap<String, Job> by = new java.util.LinkedHashMap<>();
        java.util.List<File> files = new java.util.ArrayList<>();
        File rem = Job.remembered(c);
        if (rem != null) files.add(rem);
        for (Game g : Game.load(c)) files.add(Job.fileOf(DumpCheck.workOf(new File(g.gameDir), g.titleId)));
        for (File f : files) {
            if (f == null || !f.isFile() || by.containsKey(f.getAbsolutePath())) continue;
            try { by.put(f.getAbsolutePath(), Job.read(f)); } catch (IOException e) { /* not a job of this app's format */ }
        }
        List<Job> out = new java.util.ArrayList<>(by.values());
        out.sort((x, y) -> Long.compare(y.updated(), x.updated()));
        return out;
    }

    /** Whether a job is unfinished (it should run, or waits for the user) */
    static boolean unfinished(Job j) { String s = j.state(); return s.equals("running") || s.equals("pending") || s.equals("paused") || s.equals("failed"); }

    /** Play needs the pack (Pack.read: pack.tsv and its modules) and its shader library of this APK's version */
    static boolean ready(Job j) { return Panel.ready(j); }

    /** Prepare the dump (MainActivity's Add game, a game card's Prepare again): checked off the main thread, then asked before anything is written */
    static void prepare(MainActivity a, File dump, boolean again) { if (panel != null && panel.a == a) panel.picked(dump, false, null, again); }

    /** Shaders a delta update of this pack translates (the profile's manifest rows for the pack's older libraries, ShaderLibs.toTranslate), -1 when the manifest has none of them */
    static int deltaShaders(File packDir, String titleId) { return Pack.deltaShaders(packDir, titleId); }

    /** What making a pack's shaders does and takes, for Prepare's dialogs: an update of the changed ones when the manifest knows the pack's older library, else all of them */
    static String shadersText(android.content.Context c, File packDir, String titleId) {
        int n = deltaShaders(packDir, titleId);
        Profile p = Profile.of(titleId);
        if (n >= 0 && p != null) return c.getString(R.string.s2_shaders_update_n, n, p.shaderTotal, about(c, titleId, p.shaderTotal, n, false));
        return c.getString(R.string.s2_shaders_make, p != null ? about(c, titleId, p.shaderTotal, p.shaderTotal, false) : c.getString(R.string.s2_minutes, 20, 35));
    }

    /**
     * "about 4 h 10 min on this phone" in the interface's language: a job that makes the game's shader library, translating toTranslate shaders of its map (and rewrites the code: code), at
     * this phone's rates (PrepareTime.seconds, Job.rates: learned from its jobs, else its SoC class's)
     */
    static String about(android.content.Context c, String titleId, int mapShaders, int toTranslate, boolean code) {
        return c.getString(R.string.s2_time_about, PrepareTime.text(PrepareTime.seconds(Job.rates(c, titleId), mapShaders, toTranslate, true, code)));
    }

    private static final java.util.Set<String> autoTried = new java.util.HashSet<>();
    /** The jobs the launcher's recovery started again (file@updated), once each per process */
    private static final java.util.Set<String> RECOVERED = new java.util.HashSet<>();

    /**
     * The advanced choices of a game's preparation, one builder for the game's Options (under Advanced), its settings' Preparation and Prepare's link: Prepare
     * again (a dump), Pick the pack folder, Import / Export shaders, Import / Export the full pack. dismiss: closes the sheet the rows are in (null: none)
     */
    static void advancedRows(MainActivity a, Game g, LinearLayout box, Runnable dismiss) {
        Runnable close = dismiss != null ? dismiss : () -> {};
        boolean profile = Profile.of(g.titleId) != null;
        if (isDump(new File(g.gameDir)) && profile)
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_retry, a.getString(R.string.s2_prepare_again), v -> { close.run(); a.prepareAgain(g); })
                    .value(a.getString(R.string.s2_prepare_again_note)).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_folder_open, a.getString(R.string.s2_pick_pack), v -> { close.run(); a.pickPackFor(new File(g.gameDir), g.titleId); })
                .value(a.getString(R.string.s2_pick_pack_note)).chevron(a).view);
        if (profile)
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_folder_open, a.getString(R.string.s2_shaders_import), v -> { close.run(); ShaderUi.importPick(a, g); })
                    .value(a.getString(R.string.s2_shaders_import_note)).chevron(a).view);
        if (ShaderUi.canExport(g))
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_external, a.getString(R.string.s2_shaders_export), v -> { close.run(); ShaderUi.exportPick(a, g); })
                    .value(a.getString(R.string.s2_shaders_export_note)).chevron(a).view);
        if (profile)
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_folder_open, a.getString(R.string.s2_pack_import), v -> { close.run(); PackUi.importPick(a, g); })
                    .value(a.getString(R.string.s2_pack_import_note)).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_external, a.getString(R.string.s2_pack_export), v -> { close.run(); PackUi.exportPick(a, g); })
                .value(a.getString(R.string.s2_pack_export_note)).chevron(a).view);
    }

    /** The advanced choices as a sheet of their own (Prepare's "I already have a pack or shaders…") */
    static void advanced(MainActivity a, Game g) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        Ui.add(box, Ui.small(a, a.getString(R.string.s2_prepare_have_shaders)), 0);
        LinearLayout rows = Ui.add(box, Ui.panel(a), 12);
        AlertDialog[] d = new AlertDialog[1];
        advancedRows(a, g, rows, () -> d[0].dismiss());
        d[0] = Ui.sheet(a, a.getString(R.string.s2_advanced), box).setNegativeButton(android.R.string.cancel, null).show();
    }

    /**
     * A shader update the user need not ask for: a dump whose pack has an older library the profile's delta manifest knows (deltaShaders) is updated in the background
     * with no question, once per app process (a failed or paused job is resumed once). The game card then shows it, and Play stays on when that library is playable
     * (Pack.playableLibrary); otherwise Play waits for it as before. Only the card's own pack is updated (card = true): never the pack Folders.packFor would pick
     * (a game added with another pack, e.g. the play app's beside the dump), never a whole job, never a job for another pack folder
     */
    static void autoUpdate(MainActivity a, File dump, File packDir, String titleId) {
        // not while an export or import of the game works (tried again on a later refresh: autoTried is not taken)
        if (panel == null || panel.a != a || panel.alive() || importBusy(a, titleId, false)
                || Pack.playableLibrary(packDir, titleId) != null
                || Pack.bananaForeignLibrary(packDir, titleId) != null || deltaShaders(packDir, titleId) < 0) return;
        // never over another game's unfinished job: re-pointing the remembered job left that game's card without its state (2026-11-08); it waits for that job
        for (Job j : gameJobs(a)) if (unfinished(j) && !j.dump().getPath().equals(dump.getPath())) return;
        if (!autoTried.add(dump.getPath())) return;
        panel.picked(dump, true, packDir, false, true, false);
    }

    /**
     * An export or import of this game's pack or shaders works now (PackUi.busy, this process): Prepare's job does not start (it would translate beside an import
     * that then swaps the library in, or write into the pack folder the import swaps), nor does Play. tell: say so (a Toast), else quietly
     */
    static boolean importBusy(android.content.Context c, String titleId, boolean tell) {
        if (titleId == null || titleId.isEmpty() || !PackUi.busy(titleId)) return false;
        if (tell) {
            Profile p = Profile.of(titleId);
            android.widget.Toast.makeText(c, c.getString(R.string.s2_shaders_err_working, p != null ? p.name : titleId), android.widget.Toast.LENGTH_LONG).show();
        }
        return true;
    }

    /** Whether a folder or .nup is a dump Prepare can start from: an update, or a base game with its code and RomFS (Pack.isDump; DumpCheck checks it fully) */
    static boolean isDump(File dir) { return Pack.isDump(dir); }
    static void resume(MainActivity a) { if (panel != null && panel.a == a) panel.resume(); }

    static void pause(MainActivity a) { if (panel != null && panel.a == a) panel.pause(); }

    /** Whether Home shows the preparing card now */
    static boolean showing() { return panel != null && panel.view.getVisibility() == View.VISIBLE; }

    static boolean activityResult(MainActivity a, int request, int result, Intent data) {
        if (request == PREPARE_SCREEN) {   // Play on the preparation screen: the game goes into the list and starts
            if (result == MainActivity.RESULT_OK && data != null && data.getBooleanExtra(PrepareActivity.EXTRA_PLAY, false) && panel != null && panel.a == a) {
                panel.load();
                panel.play();
            }
            // Its Import shaders… (stopped at the shader steps): the game's import, into the pack the job writes; Resume then skips the shader steps
            if (result == MainActivity.RESULT_OK && data != null && data.getBooleanExtra(PrepareActivity.EXTRA_IMPORT_SHADERS, false)) {
                File f = Job.remembered(a);
                try {
                    Job j = f == null ? null : Job.read(f);
                    if (j != null) ShaderUi.importPick(a, a.cardFor(j.dump(), j.titleId()));
                } catch (IOException e) {
                    a.error(e.getMessage());
                }
            }
            return true;
        }
        if (request != PICK_DUMP) return false;
        if (result != MainActivity.RESULT_OK || data == null || data.getData() == null || panel == null || panel.a != a) return true;
        String path = PathUtil.treeToPath(data.getData());
        if (path == null) a.error(a.getString(R.string.s2_err_not_on_storage, String.valueOf(data.getData())));
        else panel.picked(new File(path), false, null);
        return true;
    }

    /** adb: am start -n dev.nxnative.android/.MainActivity (play app: dev.nxnative.android.play/dev.nxnative.android.MainActivity) --es ondevice_dump <dump folder> [--ez ondevice_start true] [--ez ondevice_pause true]
     *  [--es ondevice_pack <pack folder>] [--ez show_when_locked true] (TESTING.md). ondevice_pack: the job writes its pack there instead of the app's
     *  packs/<id> (AppStorage.pack), and a pack already there or beside the dump is not adopted (agents' test runs: <work>/ondevice/test-pack, so the user's pack is never written) */
    static void fromIntent(MainActivity a, Intent i) {
        if (panel != null && panel.a != a) return;   // a panel of an activity gone (the launcher was recreated on its Settings page)
        // Tests over adb on a locked phone: the launcher shows over the lock screen (it stays locked; only this screen shows), so its screen can be checked and captured
        if (i.getBooleanExtra("show_when_locked", false)) { a.setShowWhenLocked(true); a.setTurnScreenOn(true); a.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); }
        String dump = i.getStringExtra("ondevice_dump");
        String pack = i.getStringExtra("ondevice_pack");
        if (dump != null && panel != null) panel.picked(new File(dump), i.getBooleanExtra("ondevice_start", false), pack == null ? null : new File(pack));
        if (i.getBooleanExtra("ondevice_pause", false) && panel != null) panel.pauseJob("adb");
        // The preparation notification's tap (PackService.note, EXTRA_OPEN_SCREEN): the preparation screen over the library, at once or as soon as the job's state is known
        if (i.getBooleanExtra(PackService.EXTRA_OPEN_SCREEN, false)) {
            i.removeExtra(PackService.EXTRA_OPEN_SCREEN);   // not again when the activity is recreated with the same intent
            if (current != null) openScreen(a);
            else openPending = true;
        }
    }

    private static final class Panel implements ServiceConnection {
        final MainActivity a;
        final LinearLayout view, card;
        final TextView head, title, status, detail, headline, explain, pct, activity, after;
        final ProgressBar bar;
        final LinearLayout body, gameCol, mainCol;
        final Button go;
        final Ui.Action play;
        final View more;
        /** The job (file and creation time) whose game this app put into the list ("added" in the ondevice prefs): once per job, so a game the user removed stays removed */
        static String addedKey(Job j) { return j.file.getPath() + "@" + j.created(); }
        final Handler h = new Handler(Looper.getMainLooper());
        final Messenger client = new Messenger(new Handler(Looper.getMainLooper(), this::onMessage));
        Messenger service;
        boolean bound, resumed;
        long resumedAt;
        Job job;
        boolean jobAlive;   // the service said its worker runs this job
        boolean screen;     // Jogar asked for this job: the preparation screen opens once it starts (Ondevice.play)
        boolean autoPlay;   // ... and the game starts when it is done (Ondevice.fixCodeThenPlay: the short job)
        boolean saveFailed; // the service could not write job.json (PackService's saveError)
        boolean recoverAsked;   // this resume's recovery ran (recover)

        Panel(MainActivity a) {
            this.a = a;
            // Swap2-Native's preparation screen (docs/SWAP2-NATIVE-SHADERS-VISUAL-v2.md, assets/artwork/swap2-native/shaders/precompile-v2.png), as a card while there is a
            // job: the game on the left (a cover tile, "Selected game", its name and version), and on the right what happens (Preparing your game, one line on why), a
            // progress panel (the step and the share done, the bar, the shaders processed and whether it runs), then Pause / Resume and Play, with what pausing does
            // beside them. Side by side on a wide window, one column on a narrow one. The numbers are the job's own (Job.overall, shadersDone / shadersTotal): no
            // estimate of time and no step the job does not report. Forget and the deletes are in ⋯ Manage, never beside Play
            view = Ui.card(a);
            card = view;
            view.setPadding(dp(20), dp(16), dp(16), dp(20));
            LinearLayout top = Ui.row(a);
            TextView kicker = Ui.text(a, "●  PREPARATION", 12, R.color.bn_banana, 700);
            kicker.setLetterSpacing(0.12f);
            top.addView(kicker, Ui.weight());
            more = Ui.more(a, "Manage the preparing job", v -> manage());
            top.addView(more);
            card.addView(top);
            body = new LinearLayout(a);
            Ui.add(card, body, 4);
            // The game: a cover tile (no cover yet: the kit's symbol on the elevated surface), then its name
            gameCol = new LinearLayout(a);
            gameCol.setOrientation(LinearLayout.VERTICAL);
            android.widget.FrameLayout cover = new android.widget.FrameLayout(a);
            cover.setBackground(Ui.round(Ui.col(a, R.color.bn_tint), dp(20), Ui.col(a, R.color.bn_card_stroke), dp(1)));
            android.widget.ImageView sym = new android.widget.ImageView(a);
            sym.setImageResource(R.drawable.s2_mark_v6);   // the v6 compact mark, light or dark with the theme (Ui.badge)
            sym.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            cover.addView(sym, new android.widget.FrameLayout.LayoutParams(dp(56), dp(56), android.view.Gravity.CENTER));
            gameCol.addView(cover, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(132)));
            Ui.add(gameCol, Ui.section(a, "Selected game"), 14);
            head = Ui.text(a, "", 20, R.color.bn_text, 800);
            head.setAccessibilityHeading(true);
            head.setMaxLines(2);
            head.setEllipsize(android.text.TextUtils.TruncateAt.END);
            Ui.add(gameCol, head, 4);
            title = Ui.small(a, "");
            Ui.add(gameCol, title, 2);
            // What happens, and how far it is
            mainCol = new LinearLayout(a);
            mainCol.setOrientation(LinearLayout.VERTICAL);
            headline = Ui.text(a, "Preparing your game", 26, R.color.bn_text, 800);
            mainCol.addView(headline);
            explain = Ui.small(a, "Your game's code and graphics cache are built on this phone, once, so it plays with fewer pauses.");
            Ui.add(mainCol, explain, 6);
            LinearLayout prog = Ui.inner(a, R.color.bn_tint);
            prog.setBackground(Ui.round(Ui.col(a, R.color.bn_tint), dp(16), Ui.col(a, R.color.bn_card_stroke), dp(1)));
            prog.setPadding(dp(16), dp(14), dp(16), dp(14));
            LinearLayout pr = Ui.row(a);
            status = Ui.text(a, "", 15, R.color.bn_text, 700);
            status.setMaxLines(2);
            pr.addView(status, Ui.weight());
            pct = Ui.text(a, "", 28, R.color.bn_text, 800);
            pct.setPadding(dp(12), 0, 0, 0);
            pr.addView(pct);
            prog.addView(pr);
            bar = Ui.progress(a);
            bar.setMax(1000);
            Ui.add(prog, bar, 10);
            LinearLayout dr = Ui.row(a);
            detail = Ui.small(a, "");
            detail.setTextSize(12);
            dr.addView(detail, Ui.weight());
            activity = Ui.text(a, "", 12, R.color.bn_banana, 600);
            activity.setPadding(dp(12), 0, 0, 0);
            dr.addView(activity);
            Ui.add(prog, dr, 8);
            Ui.add(mainCol, prog, 16);
            go = Ui.button(a, "", Ui.Kind.SOFT, v -> goOrPause());
            go.setPadding(dp(12), 0, dp(12), 0);   // "Prepare again" fits half a narrow card
            go.setMinHeight(dp(56));
            go.setMinimumHeight(dp(56));
            play = Ui.action(a, R.drawable.ic_play, "Play", Ui.Kind.PRIMARY, v -> play());
            Ui.add(mainCol, Ui.pair(a, go, play), 16);
            after = Ui.small(a, "");
            after.setTextSize(12);
            Ui.add(mainCol, after, 8);
            layout();
            load();
            show();
        }

        int dp(int v) { return Math.round(v * a.getResources().getDisplayMetrics().density); }

        /** Side by side on a wide window (the game column a third of the card), one column on a narrow one (the cover shorter, the game above the progress) */
        void layout() {
            body.removeAllViews();
            boolean wide = a.getResources().getConfiguration().screenWidthDp >= 600;
            body.setOrientation(wide ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
            gameCol.getChildAt(0).getLayoutParams().height = dp(wide ? 132 : 96);
            if (wide) {
                LinearLayout.LayoutParams g = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
                g.rightMargin = dp(24);
                g.topMargin = dp(12);
                body.addView(gameCol, g);
                LinearLayout.LayoutParams m = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 2);
                m.topMargin = dp(8);
                body.addView(mainCol, m);
            } else {
                body.addView(gameCol, Ui.fill());
                LinearLayout.LayoutParams m = Ui.fill();
                m.topMargin = dp(20);
                body.addView(mainCol, m);
            }
        }

        void detach() {
            pause();
        }

        void resume() {
            resumed = true;
            resumedAt = SystemClock.elapsedRealtime();
            if (!bound) bound = a.bindService(new Intent(a, PackService.class), this, 0);   // 0: only while the service runs; never starts it
            tick();
            recoverAsked = false;
            h.postDelayed(this::recover, 3000);   // after the binding's grace (alive): a worker that runs has answered by then
        }

        /**
         * A job that should run but has no worker (the OEM's background limits ended the :pack process, START_STICKY never came back, or the job was written and
         * never started) is started again as the app opens, the newest one only (the others stay Continue on their cards). It counts as a sticky restart
         * (EXTRA_FROM recover: the step's kills add up, so a job Android ends every time fails with killed instead of looping). Once per job state per process
         */
        void recover() {
            if (!resumed || recoverAsked || alive()) return;
            recoverAsked = true;
            new Thread(() -> {
                List<Job> jobs = gameJobs(a);
                Job pick = null;
                for (Job j : jobs) if (j.state().equals("running") || j.state().equals("pending")) { pick = j; break; }
                Job p = pick;
                if (p == null) return;
                h.post(() -> {
                    if (!resumed || alive() || importBusy(a, p.titleId(), false) || !Environment.isExternalStorageManager()) return;
                    if (!RECOVERED.add(p.file.getPath() + "@" + p.updated())) return;
                    android.util.Log.i("nxpack", "recover: " + p.file + " was " + p.state() + " with no worker; starting it again");
                    Job.remember(a, p.file);
                    job = p;
                    try {
                        a.startForegroundService(new Intent(a, PackService.class).setAction(PackService.ACTION_START).putExtra(PackService.EXTRA_JOB, p.file.getPath())
                                .putExtra(PackService.EXTRA_FROM, "recover"));
                    } catch (RuntimeException e) {
                        android.util.Log.w("nxpack", "recover: " + e);
                        return;
                    }
                    if (!bound) bound = a.bindService(new Intent(a, PackService.class), this, 0);
                    resumedAt = SystemClock.elapsedRealtime();
                    show();
                });
            }, "nxpack-recover").start();
        }

        void pause() {
            resumed = false;
            h.removeCallbacksAndMessages(null);
            if (bound) {
                if (service != null) {
                    Message m = Message.obtain(null, PackService.MSG_UNREGISTER);
                    m.replyTo = client;
                    try { service.send(m); } catch (RemoteException e) { /* gone */ }
                }
                a.unbindService(this);
                bound = false;
                service = null;
                jobAlive = false;
            }
        }

        /** Every second while shown: job.json when the service is not telling us */
        void tick() {
            if (!resumed) return;
            if (service == null || !jobAlive) load();
            show();
            h.postDelayed(this::tick, 1000);
        }

        void load() {
            File f = Job.remembered(a);
            if (f == null || !f.isFile()) { job = null; return; }
            try {
                job = Job.read(f);
            } catch (IOException e) {
                // being renamed over, or damaged: keep the last one
            }
        }

        @Override public void onServiceConnected(ComponentName n, IBinder b) {
            service = new Messenger(b);
            Message m = Message.obtain(null, PackService.MSG_REGISTER);
            m.replyTo = client;
            try { service.send(m); } catch (RemoteException e) { service = null; }
        }

        @Override public void onServiceDisconnected(ComponentName n) {   // the :pack process died
            service = null;
            jobAlive = false;
            show();
        }

        @Override public void onBindingDied(ComponentName n) {
            service = null;
            jobAlive = false;
            if (bound) { a.unbindService(this); bound = false; }
            if (resumed) bound = a.bindService(new Intent(a, PackService.class), this, 0);
        }

        boolean onMessage(Message m) {
            if (m.what != PackService.MSG_STATE) return false;
            Bundle d = m.getData();
            if (d.getString("error") != null) {   // the service could not read the job it was asked to run
                android.widget.Toast.makeText(a, a.getString(R.string.s2_why_unreadable), android.widget.Toast.LENGTH_LONG).show();
                return true;
            }
            Job j = Job.of(new File(d.getString("file", "")), d.getString("job", "{}"));
            if (j != null) job = j;
            jobAlive = d.getBoolean("alive");
            saveFailed = d.getString("saveError") != null;
            show();
            return true;
        }

        /** Whether the service's worker is running the job now (or may be: just resumed, the binding not yet answered) */
        boolean alive() { return jobAlive || (service == null && SystemClock.elapsedRealtime() - resumedAt < 2500 && job != null && ("running".equals(job.state()) || "pending".equals(job.state()))); }

        void show() {
            boolean alive = job != null && alive();
            boolean ready = job != null && ready(job);
            // A finished job: its game goes into the list with its pack (once), and the card goes: Play is on the game's card
            if (ready && !alive && !addedKey(job).equals(Prefs.open(a, "ondevice").getString("added", ""))) addGame(job);
            boolean was = view.getVisibility() == View.VISIBLE;
            if (job == null || ready && listed(job)) { view.setVisibility(View.GONE); publish(null); if (was) a.refresh(); return; }
            view.setVisibility(View.VISIBLE);
            publish(PrepareState.of(a, job, alive, ready, saveFailed && alive));
            if (!was) a.refresh();   // the games' empty card hides while this one shows
            String st = job.state();
            String sim = "fake".equals(BuildConfig.NX_PACK_ENGINE) ? "  (simulated engine)" : "";
            head.setText(job.name().isEmpty() ? "Selected game" : job.name());
            title.setText(Profile.versionName(job.version()).substring(0, 1).toUpperCase(Locale.ROOT) + Profile.versionName(job.version()).substring(1) + sim);
            boolean running = alive && ("running".equals(st) || "paused".equals(st) && !"user".equals(job.reason()) && !"timeout".equals(job.reason()));
            headline.setText("done".equals(st) ? "Your game is ready" : "failed".equals(st) ? "Preparation stopped" : "pending".equals(st) ? "Ready to prepare"
                    : running ? "Preparing your game" : "Preparation paused");
            status.setText(job.statusText(alive));
            double overall = Math.max(0, Math.min(1, job.overall()));   // never past the bar
            bar.setProgress((int) Math.round(overall * 1000));
            pct.setText(String.format(Locale.getDefault(), "%d%%", (int) Math.floor(overall * 100)));
            long total = job.shadersTotal(), done = Math.max(0, Math.min(job.shadersDone(), total));
            detail.setText(total > 0 ? String.format(Locale.getDefault(), "%,d of %,d shaders processed", done, total) : "Shaders: counted when the split is done");
            activity.setText(running ? "In progress" : "done".equals(st) ? "Done" : "failed".equals(st) ? "Stopped" : "Paused");
            activity.setTextColor(Ui.col(a, running ? R.color.bn_banana : "done".equals(st) ? R.color.bn_leaf : "failed".equals(st) ? R.color.bn_danger : R.color.bn_text_2));
            after.setText(running ? "Pausing keeps everything done so far; Resume goes on from here. The game can be played when it is ready."
                    : "done".equals(st) ? "Play starts the game with its prepared pack." : "Nothing done so far is lost.");
            go.setText(running ? "Pause" : "done".equals(st) && !job.apkChanged() ? "Prepare again" : "failed".equals(st) ? "Retry" : "pending".equals(st) ? "Start" : "Resume");
            go.setEnabled(!"done".equals(st) || job.apkChanged());
            play.setEnabled(ready && !running);
        }

        /** Whether the list has this job's game with its pack */
        boolean listed(Job j) {
            for (Game g : Game.load(a)) if (g.gameDir.equals(j.dump().getPath()) && g.packDir.equals(j.pack().getPath())) return true;
            return false;
        }

        /** The finished job's game into the list (its dump and pack); a picked pack folder (Folders) follows to the new pack */
        void addGame(Job j) {
            Prefs.open(a, "ondevice").edit().putString("added", addedKey(j)).apply();
            if (listed(j)) return;
            Pack p;
            try { p = Pack.read(j.pack()); } catch (IOException e) { return; }
            if (p.simulated) return;
            Game g = new Game(j.titleId(), p.name.isEmpty() ? j.name() : p.name, j.dump().getPath(), j.pack().getPath());
            List<Game> list = Game.load(a);
            list.removeIf(x -> x.gameDir.equals(g.gameDir));
            list.add(g);
            Game.save(a, list);
            String picked = Folders.pickedPack(a, g.titleId);
            if (picked != null && !picked.equals(g.packDir)) Folders.pickedPack(a, g.titleId, g.packDir);
            a.refresh();
            android.widget.Toast.makeText(a, a.getString(R.string.s2_ready_toast, g.name), android.widget.Toast.LENGTH_LONG).show();
        }

        /** Play needs the pack (Pack.read: pack.tsv and its modules) and its shader library of this APK's version */
        static boolean ready(Job j) {
            if (!"done".equals(j.state()) || j.apkChanged()) return false;
            try {
                Pack p = Pack.read(j.pack());
                return (Pack.libraryProblem(j.pack(), j.titleId()) == null || Pack.playableLibrary(j.pack(), j.titleId()) != null
                                || Pack.bananaForeignLibrary(j.pack(), j.titleId()) != null)
                        && p.unfinishedModule() == null && p.titleId.equals(j.titleId());
            } catch (IOException e) {
                return false;
            }
        }

        /** What a background check found beside a picked dump */
        static final class Found {
            DumpCheck.Result r;
            File existing;   // the dump's job.json, in its work folder (DumpCheck.workOf)
            File packDir;    // the pack Folders.packFor finds for it (null: none)
            Pack pack;       // that pack, when it reads as this game's pack
            String build;    // PackCheck.playBlocking: why its code cannot run with this dump (unfinished, another game build, its mods changed), null when it fits
            Boolean code;    // PackCheck.code: its code is this APK's rewriter's (null: cannot tell)
            long tools;      // what unpacking the tools still takes (PackEngine.toolsBytes)
        }

        /**
         * A picked dump: checked off the main thread (the dump, the pack beside it), then the job: a job in progress for it is resumed; a pack that fits is used
         * as it is; a pack that fits in part has only the rest redone; else the whole job. again: the user asked to prepare again (a game card's Manage): a pack
         * whose code another rewriter made has its code redone too
         */
        void picked(File dump, boolean start, File packOverride) { picked(dump, start, packOverride, false); }

        void picked(File dump, boolean start, File packOverride, boolean again) { picked(dump, start, packOverride, again, false, false); }

        /**
         * card: an automatic update of a game card's pack (autoUpdate): packOverride is that pack, checked as the pack to keep; nothing else is started or asked.
         * codeOnly: Play's short job (fixCodeThenPlay): packOverride is the card's pack, checked like card's, and what does not fit is redone with no question.
         * The free space is checked for the job that will be made (DumpCheck.NEED_CODE or NEED_FULL, plus the tools' unpack), never skipped
         */
        void picked(File dump, boolean start, File packOverride, boolean again, boolean card, boolean codeOnly) {
            // the game starts after the job only for Play's short job: any other request clears what an earlier one left (an early return below does not reset it)
            if (!card) autoPlay = codeOnly;
            if (a.needAccess()) { if (!card) quiet(); return; }
            new Thread(() -> {
                Found f = new Found();
                try {
                    String id = Nup.isNup(dump) ? Pack.titleIdOf(dump) : Pack.programId(new File(dump, "base/exefs/main.npdm"));
                    File jf = Job.fileOf(DumpCheck.workOf(dump, id));
                    if (jf.isFile()) f.existing = jf;
                } catch (IOException e) {
                    // DumpCheck says what is wrong
                }
                f.r = DumpCheck.check(dump, 0);   // the dump; its space below, for the job it will be
                if (f.r.ok() && (packOverride == null || card || codeOnly)) {
                    f.packDir = card || codeOnly ? packOverride : Folders.packFor(a, f.r.dump, f.r.titleId);
                    try {
                        Pack p = f.packDir == null ? null : Pack.read(f.packDir);
                        if (p != null && !p.simulated && p.titleId.equals(f.r.titleId)) {
                            f.pack = p;
                            f.build = PackCheck.playBlocking(a, p, f.r.dump);
                            if (f.build == null) f.code = PackCheck.code(a, p, f.r.dump);
                        }
                    } catch (IOException e) {
                        // no usable pack: the whole job
                    }
                }
                f.tools = PackEngine.toolsBytes(a);
                h.post(() -> checked(f, start, packOverride, again, card, codeOnly));
            }, "nxpack-check").start();
        }

        /** A dump the check refused, in the interface's language (the check's own sentence as the detail) */
        String dumpError(DumpCheck.Result r) {
            String name = r.titleId != null && Profile.of(r.titleId) != null ? Profile.of(r.titleId).name : r.dump.getName();
            if (DumpCheck.NOSPACE.equals(r.code)) return GameState.whyText(a, GameFlow.Why.NO_SPACE, r.free, r.needBytes, "", name);
            int res = DumpCheck.NOTDUMP.equals(r.code) ? R.string.s2_dump_not_dump : DumpCheck.BUILD.equals(r.code) ? R.string.s2_dump_build
                    : DumpCheck.UNWRITABLE.equals(r.code) ? R.string.s2_dump_unwritable : R.string.s2_dump_bad;
            return a.getString(res, name) + "\n\n" + r.error;
        }

        void checked(Found f, boolean start, File packOverride, boolean again, boolean card, boolean codeOnly) {
            DumpCheck.Result r = f.r;
            if (!card && !start) screen = false;
            if (!r.ok()) { if (!card) { quiet(); a.error(dumpError(r)); show(); } return; }
            // A job in progress for this dump is resumed as it is (Prepare again on an unfinished job goes on: no second question)
            if (f.existing != null) {
                try {
                    Job j = Job.read(f.existing);
                    boolean same = j.dump().getPath().equals(r.dump.getPath()) && j.version() == r.version && (packOverride == null || packOverride.equals(j.pack()));
                    String s = j.state();
                    if (same && unfinished(j) && !card) {
                        Job.remember(a, f.existing);
                        job = j;
                        show();
                        startService(j);
                        return;
                    }
                    if (unfinished(j)) {   // unfinished, for another pack folder: never written over (its job.json is this dump's)
                        if (card) return;   // an automatic update leaves it to the user
                        quiet();
                        otherJob(j, f, start, packOverride, again, codeOnly);
                        return;
                    }
                } catch (IOException e) {
                    // a damaged job.json or one of another format: a new job replaces it
                }
            }
            // One job at a time: the service runs only the job it has, so a new one is not written or remembered while it runs
            if (alive() && job != null && !"done".equals(job.state())) {
                if (card) return;
                quiet();
                a.error(a.getString(R.string.s2_err_one_job, job.name()));
                return;
            }
            if (card && (f.pack == null || f.build != null)) return;   // an automatic update only updates the shaders of the card's own pack, when its code fits
            // A pack already there (the picked pack folder, else beside the dump): what fits is kept
            if (f.pack != null) {
                File pd = f.packDir;
                String lp = PackCheck.shaders(pd, r.titleId);
                boolean code = f.build != null || again && !Boolean.TRUE.equals(f.code),
                        shaders = lp != null && Pack.playableLibrary(pd, r.titleId) == null
                                && Pack.bananaForeignLibrary(pd, r.titleId) == null;
                if (!code && !shaders) { adopt(r, pd, false, false, 0, card); return; }
                long need = (shaders ? DumpCheck.NEED_FULL : DumpCheck.NEED_CODE) + f.tools;
                Runnable redo = () -> adopt(r, pd, code, shaders, need, card);
                // Play's short job only rewrites code: a library to make too (missing, or only an older one) is a real preparation, so it is asked like Prepare
                // again (never a translation started from Play, on the screen that then starts the game by itself)
                if (start && !(codeOnly && shaders) || card) { redo.run(); return; }
                quiet();
                // Prepare again (Options): one plain question, what it does and takes
                Profile prof = Profile.of(r.titleId);
                int delta = shaders ? deltaShaders(pd, r.titleId) : -1;
                String what = code && shaders ? (delta >= 0 ? a.getString(R.string.s2_redo_code_and_update, shadersText(a, pd, r.titleId))
                                : a.getString(R.string.s2_redo_all, about(a, r.titleId, prof.shaderTotal, prof.shaderTotal, true)))
                        : code ? a.getString(R.string.s2_redo_code) : shadersText(a, pd, r.titleId);
                confirm(a.getString(code ? R.string.s2_redo_title_code : R.string.s2_redo_title_shaders, prof.name),
                        what + "\n\n" + a.getString(R.string.s2_space_line, r.free / 1073741824.0, need / 1073741824.0),
                        a.getString(code ? R.string.s2_prepare_again : R.string.s2_prepare), redo);
                return;
            }
            Profile prof = Profile.of(r.titleId);   // DumpCheck refused a dump without one
            File target = packOverride != null ? packOverride : AppStorage.pack(a, r.titleId);
            // Its shaders imported already (Import shaders… with no pack yet, ShaderZip.ready): the job only rewrites the code (Job.shadersInPack)
            boolean imported = !"fake".equals(BuildConfig.NX_PACK_ENGINE)
                    && (ShaderZip.ready(target, r.titleId) || Pack.playableLibrary(target, r.titleId) != null
                    || Pack.bananaForeignLibrary(target, r.titleId) != null);
            long need = (imported ? DumpCheck.NEED_CODE : DumpCheck.NEED_FULL) + f.tools;
            String text = imported ? a.getString(R.string.s2_prepare_code_only, prof.shaderTotal) + "\n\n" + a.getString(R.string.s2_space_line, r.free / 1073741824.0, need / 1073741824.0)
                    : a.getString(R.string.s2_prepare_body, r.version == 0 ? a.getString(R.string.s2_version_base) : a.getString(R.string.s2_version_update, r.version), r.dlc,
                    prof.shaderTotal, about(a, r.titleId, prof.shaderTotal, prof.shaderTotal, true), need / 1073741824.0, r.free / 1073741824.0);
            Runnable go = () -> {
                try {
                    Job j = Job.create(r, AppStorage.pack(a, r.titleId));
                    if (packOverride != null) j.pack(packOverride);
                    if (!"fake".equals(BuildConfig.NX_PACK_ENGINE)
                            && (ShaderZip.ready(j.pack(), r.titleId) || Pack.playableLibrary(j.pack(), r.titleId) != null
                            || Pack.bananaForeignLibrary(j.pack(), r.titleId) != null)) j.shadersInPack();
                    begin(j, r, need, false);
                } catch (Exception e) {
                    android.util.Log.e("nxpack", "prepare " + r.titleId + ": " + e);
                    quiet();
                    a.error(a.getString(R.string.s2_err_cannot_start, String.valueOf(e.getMessage())));
                }
            };
            // Play's short job on a pack that no longer reads: the whole job is asked, never started from Play
            if (start && !codeOnly) go.run();
            else { quiet(); askPrepare(r, prof, text, go, imported); }
        }

        /**
         * A new job, written and started: not beside an export or import of the game (nothing is written then), and only with the room it needs. Without it the
         * job is written failed (nospace, with the free and needed space) instead: its card says Try again with the reason, and the preparation screen opens on it
         */
        void begin(Job j, DumpCheck.Result r, long need, boolean card) throws IOException {
            if (importBusy(a, j.titleId(), !card)) { quiet(); return; }
            long free = DumpCheck.freeOf(r.work);
            if (free >= 0 && !GameFlow.fits(free, need)) {
                android.util.Log.e("nxpack", "prepare " + j.titleId() + ": " + GameFlow.gb(free) + " free, needs " + GameFlow.gb(need) + (card ? " (background update: not started)" : ""));
                // a background shader update (autoUpdate) the user did not ask for: no job written, no message, the remembered job left as it is
                if (card) return;
                j.fail(GameFlow.NOSPACE, free, need, "the work folder " + r.work + " has " + GameFlow.gb(free) + " free; the job needs " + GameFlow.gb(need));
                try {
                    j.save();
                } catch (IOException e) {   // a disk so full that job.json cannot be written: the same sentence, nothing recorded
                    android.util.Log.e("nxpack", "prepare " + j.titleId() + ": job.json not written: " + e.getMessage());
                    quiet();
                    a.error(GameState.whyText(a, GameFlow.Why.NO_SPACE, free, need, "", j.name()));
                    return;
                }
                Job.remember(a, j.file);
                job = j;
                show();
                a.refresh();
                if (screen) { quiet(); a.startActivityForResult(new Intent(a, PrepareActivity.class), PREPARE_SCREEN); }
                else a.error(GameState.whyText(a, GameFlow.Why.NO_SPACE, free, need, "", j.name()));
                return;
            }
            try {
                j.save();
            } catch (IOException e) {   // the disk filled since the check: said as a full disk, not as the exception's English text
                if (!GameFlow.NOSPACE.equals(GameFlow.failCode(e))) throw e;
                android.util.Log.e("nxpack", "prepare " + j.titleId() + ": job.json not written: " + e.getMessage());
                quiet();
                if (!card) a.error(GameState.whyText(a, GameFlow.Why.NO_SPACE, free, need, "", j.name()));
                return;
            }
            Job.remember(a, j.file);
            job = j;
            show();
            startService(j);
        }

        /**
         * An unfinished job of this dump writes to another pack folder: its card's Continue goes on with it. Starting over deletes its working files first (asked,
         * with what goes and what stays), then prepares again as asked
         */
        void otherJob(Job j, Found f, boolean start, File packOverride, boolean again, boolean codeOnly) {
            Job.remember(a, j.file);
            job = j;
            show();
            a.refresh();
            Ui.confirmDanger(a, a.getString(R.string.s2_fix_other_job_title), a.getString(R.string.s2_fix_other_job, j.name(), String.valueOf(j.pack()), String.valueOf(j.dir())),
                    a.getString(R.string.s2_fix_other_job_yes), () -> new Thread(() -> {
                        Job.deleteTree(j.dir());
                        Job.deleteTree(j.splitScan(a));
                        h.post(() -> {
                            Job.remember(a, null);
                            job = null;
                            show();
                            a.refresh();
                            f.existing = null;
                            checked(f, start, packOverride, again, false, codeOnly);
                        });
                    }, "nxpack-delete").start());
        }

        /**
         * Prepare's question for a dump with no pack that fits: Prepare or Cancel, and the two ways to a pack made elsewhere: "Use an existing pack…" (the folder
         * picker; the picked folder becomes the game's, MainActivity.pickPackFor) and "Import pack…" (a .zip from Export pack… or a pack folder into the app's
         * storage, PackUi; the game gets its card first, so the import has a game to go to)
         */
        void askPrepare(DumpCheck.Result r, Profile prof, String text, Runnable go, boolean imported) {
            LinearLayout box = new LinearLayout(a);
            box.setOrientation(LinearLayout.VERTICAL);
            Ui.add(box, Ui.body(a, text), 0);
            AlertDialog[] d = new AlertDialog[1];
            File found = null;
            if (!imported) {
                // A shaders zip of this version in Switch2/Shaders (an export kept across a reinstall, or copied from a computer): imported first, nothing is translated
                // this version's names: -v-<V>.zip, and -v-<V>-2.zip … for a later export of the same version (PackZip.freeFile); found() lists the newest first
                java.util.regex.Pattern ours = java.util.regex.Pattern.compile(".*-v-" + java.util.regex.Pattern.quote(BuildConfig.NX_DMSH_VK_CHAIN) + "(-\\d+)?\\.zip",
                        java.util.regex.Pattern.CASE_INSENSITIVE);
                for (File z : ShaderZip.found(r.titleId, ShaderUi.shadersDir())) if (ours.matcher(z.getName()).matches()) { found = z; break; }
                if (found != null) {   // the one alternative worth a button: nothing is translated
                    Ui.add(box, Ui.small(a, a.getString(R.string.s2_shaders_use_found_note)), 16);
                    Ui.add(box, Ui.button(a, a.getString(R.string.s2_shaders_use_found_button), Ui.Kind.TONAL,
                            v -> { d[0].dismiss(); ShaderUi.importPick(a, a.cardFor(r.dump, r.titleId)); }), 8);
                }
            }
            // Packs and shaders made elsewhere: one small link to the advanced choices, never four buttons beside Prepare
            android.widget.TextView more = Ui.text(a, a.getString(R.string.s2_have_pack_link), 14, R.color.bn_banana, 600);
            more.setPadding(0, dp(12), 0, dp(12));
            more.setOnClickListener(v -> { d[0].dismiss(); advanced(a, a.cardFor(r.dump, r.titleId)); });
            Ui.add(box, more, 12);
            d[0] = Ui.sheet(a, a.getString(R.string.s2_prepare_title, prof.name), box).setPositiveButton(R.string.s2_prepare, (x, w) -> go.run())
                    .setNegativeButton(android.R.string.cancel, null).show();
        }

        /** A pack that is already there (PackCheck): ready (a done job pointing at it, the game added to the list), or a job that redoes its code, its shaders or both */
        void adopt(DumpCheck.Result r, File packDir, boolean code, boolean shaders, long need, boolean card) {
            try {
                Job j = Job.adopt(r, packDir, code, shaders);
                if (code || shaders) { begin(j, r, need, card); return; }
                if (card) return;   // a background update with nothing to update
                if (importBusy(a, j.titleId(), true)) { quiet(); return; }
                j.save();
                Job.remember(a, j.file);
                job = j;
                boolean play = autoPlay;
                screen = false;   // nothing to prepare: no preparation screen
                autoPlay = false;
                Prefs.open(a, "ondevice").edit().putString("added", addedKey(j)).apply();
                Pack p = Pack.read(packDir);
                Game g = new Game(r.titleId, p.name.isEmpty() ? j.name() : p.name, r.dump.getPath(), packDir.getPath());
                List<Game> list = Game.load(a);
                list.removeIf(x -> x.gameDir.equals(g.gameDir));
                list.add(g);
                Game.save(a, list);
                a.refresh();
                show();
                if (play) { a.launch(g, false); return; }   // Play's short job found nothing to redo: the game starts
                android.widget.Toast.makeText(a, a.getString(R.string.s2_ready_toast, g.name), android.widget.Toast.LENGTH_LONG).show();
            } catch (Exception e) {
                android.util.Log.e("nxpack", "adopt " + packDir + ": " + e);
                quiet();
                if (!card) a.error(a.getString(R.string.s2_err_cannot_start, packDir + ": " + e.getMessage()));
            }
        }

        /** A request that ends without a job started: neither the preparation screen nor the game's start is left for a later one */
        void quiet() { screen = false; autoPlay = false; }

        void confirm(String t, String msg, String yes, Runnable r) {
            new AlertDialog.Builder(a).setTitle(t).setMessage(msg).setPositiveButton(yes, (d, w) -> r.run()).setNegativeButton(android.R.string.cancel, null).show();
        }

        void startService(Job j) {
            if (importBusy(a, j.titleId(), true)) { screen = false; autoPlay = false; return; }
            // Android 13+: the progress notification needs the user's yes; the job runs either way (without it the notification shows only in the task manager)
            if (a.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                a.requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, ASK_NOTIFY);
            try {
                a.startForegroundService(new Intent(a, PackService.class).setAction(PackService.ACTION_START).putExtra(PackService.EXTRA_JOB, j.file.getPath()));
            } catch (RuntimeException e) {   // Android refused the start (the app is in the background): the card says Continue
                android.util.Log.w("nxpack", "start refused: " + e);
                screen = false;
                autoPlay = false;
                android.widget.Toast.makeText(a, a.getString(R.string.s2_why_refused_long), android.widget.Toast.LENGTH_LONG).show();
                return;
            }
            if (!bound) bound = a.bindService(new Intent(a, PackService.class), this, 0);
            resumedAt = SystemClock.elapsedRealtime();
            if (screen) {   // Jogar: the preparation screen, over the library (the short one for Play's code job, which starts the game when it is done)
                screen = false;
                boolean play = autoPlay;
                autoPlay = false;
                publish(PrepareState.of(a, j, true, false));
                a.startActivityForResult(new Intent(a, PrepareActivity.class).putExtra(PrepareActivity.EXTRA_AUTOPLAY, play), PREPARE_SCREEN);
            }
        }

        /** from: who asked (PackService.EXTRA_FROM: launcher or adb), for the logs */
        void pauseJob(String from) {
            a.startService(new Intent(a, PackService.class).setAction(PackService.ACTION_PAUSE).putExtra(PackService.EXTRA_FROM, from));
        }

        void goOrPause() {
            if (job == null) return;
            if (go.getText().toString().equals("Pause")) { pauseJob("launcher"); return; }
            if (a.needAccess()) return;
            startService(job);
        }

        void play() {
            if (job == null || !ready(job) || importBusy(a, job.titleId(), true)) return;
            Pack p;
            try { p = Pack.read(job.pack()); } catch (IOException e) { a.error(e.getMessage()); return; }
            if (p.simulated) {
                a.error(a.getString(R.string.s2_err_simulated));
                return;
            }
            Game g = new Game(job.titleId(), p.name.isEmpty() ? job.name() : p.name, job.dump().getPath(), job.pack().getPath());
            List<Game> list = Game.load(a);
            list.removeIf(x -> x.gameDir.equals(g.gameDir));
            list.add(g);
            Game.save(a, list);
            a.refresh();
            a.launch(g, false);   // no second short job from here: a pack that still does not fit says why
        }

        /**
         * The job's Manage sheet (⋯): Forget (nothing deleted), Delete working files (the job's own ondevice/ folder), and Delete the prepared pack as well (only
         * a pack this job made, never one it adopted). Each asks first and names every folder that goes; saves are never deleted. While the job runs, all wait.
         */
        void manage() {
            if (job == null) return;
            Job j = job;
            boolean running = alive() && ("running".equals(j.state()) || "paused".equals(j.state()) && !"user".equals(j.reason()) && !"timeout".equals(j.reason()));
            LinearLayout box = new LinearLayout(a);
            box.setOrientation(LinearLayout.VERTICAL);
            TextView info = Ui.small(a, j.statusText(alive()) + "\n\nDump: " + j.dump() + "\nWorking files: " + j.dir() + "\nPack: " + j.pack() + "\nLogs: " + new File(j.dir(), "logs"));
            info.setTextIsSelectable(true);
            box.addView(info);
            android.app.AlertDialog[] d = new android.app.AlertDialog[1];
            View line = new View(a);
            line.setBackgroundColor(Ui.col(a, R.color.bn_card_stroke));
            Ui.add(box, line, 20, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
            if (running) Ui.add(box, Ui.small(a, "Pause first to forget or delete."), 14);
            Button f = Ui.button(a, "Forget this job…", Ui.Kind.QUIET, v -> { d[0].dismiss(); forget(); });
            f.setEnabled(!running);
            Ui.add(box, f, 10, Ui.wrap());
            Button w = Ui.button(a, "Delete working files…", Ui.Kind.DANGER, v -> { d[0].dismiss(); deleteWork(j, false); });
            w.setEnabled(!running);
            Ui.add(box, w, 8, Ui.wrap());
            if (ownPack(j) != null) {
                Button pk = Ui.button(a, "Delete the prepared pack too…", Ui.Kind.DANGER, v -> { d[0].dismiss(); deleteWork(j, true); });
                pk.setEnabled(!running);
                Ui.add(box, pk, 8, Ui.wrap());
            }
            d[0] = Ui.sheet(a, "Preparing " + j.name(), box).setPositiveButton("Done", null).show();
        }

        void forget() {
            if (job == null) return;
            Ui.confirmDanger(a, "Forget this job?", "Deleted: nothing. The screen stops showing the job.\n\nKept: its files in " + job.dir()
                    + ", the pack, your dump and your saves. Picking the same dump again finds the job.\n\nThe split's kept progress (a copy in the app's own storage) "
                    + "is deleted when a job of another game starts; until then an unfinished split resumes from it.", "Forget", () -> {
                Job.remember(a, null);
                job = null;
                show();
            });
        }

        /** The pack folder this job made itself (the app's packs/<id>, an older job's <work>/android-pack, or the simulated engine's ondevice/fake-pack), else null: an adopted pack is the user's */
        File ownPack(Job j) {
            if (!j.ownsPack()) return null;   // a folder that was there before the job (a Mac pack, an adopted one) is the user's
            File p = j.pack(), w = j.work();
            boolean ours = p.equals(AppStorage.pack(a, j.titleId())) || p.getParentFile() != null && (p.getParentFile().equals(w) || p.getParentFile().equals(j.dir()));
            return ours && new File(p, "pack.tsv").isFile() ? p : null;
        }

        static boolean inside(File f, File dir) {
            String fp = f.getAbsolutePath() + "/", dp = dir.getAbsolutePath() + "/";
            return fp.startsWith(dp) || dp.startsWith(fp);
        }

        /** Delete working files (and, when asked, the pack this job made): asked first, never a folder that holds or is inside the dump or the save folder */
        void deleteWork(Job j, boolean pack) {
            File dir = j.dir(), pk = pack ? ownPack(j) : null;
            File save = Folders.save(a, new Game(j.titleId(), j.name(), j.dump().getPath(), j.pack().getPath()));
            java.util.List<File> gone = new java.util.ArrayList<>();
            gone.add(dir);
            if (pk != null && !inside(pk, dir)) gone.add(pk);
            for (File g : gone) {
                if (inside(g, j.dump()) || save != null && inside(g, save)) {
                    a.error("Not deleted: " + g + " holds or is inside " + (inside(g, j.dump()) ? "your dump" : "your save folder") + ".");
                    return;
                }
            }
            StringBuilder m = new StringBuilder("Deleted:\n· the working files in " + dir + " (rewritten code, split and translated shaders, the job's progress)"
                    + "\n· the split's kept progress, a copy in the app's own storage");
            if (pk != null) m.append(inside(pk, dir) ? " with the pack inside it" : "\n· the prepared pack and its shader library in " + pk);
            m.append("\n\nKept: your dump (" + j.dump() + ") and your saves").append(save != null ? " (" + save + ")" : "")
                    .append(pk == null ? ", and the pack (" + j.pack() + ")" : "").append(". Saves are never deleted here.");
            Profile prof = Profile.of(j.titleId());
            String again = prof == null ? "" : " (about " + PrepareTime.text(PrepareTime.seconds(Job.rates(a, j.titleId()), prof.shaderTotal, prof.shaderTotal, true, true)) + " on this phone)";
            m.append(pk != null ? "\n\nThe game will not start until it is prepared again" + again + "." :"\n\nA new Prepare starts from the beginning.");
            Ui.confirmDanger(a, pk != null ? "Delete the prepared pack?" : "Delete working files?", m, "Delete", () -> {
                android.app.AlertDialog wait = new android.app.AlertDialog.Builder(a).setMessage("Deleting…").setCancelable(false).show();
                new Thread(() -> {
                    for (File g : gone) Job.deleteTree(g);
                    Job.deleteTree(j.splitScan(a));   // the split's kept scan results, in the app's own storage
                    h.post(() -> {
                        wait.dismiss();
                        Job.remember(a, null);
                        job = null;
                        show();
                        a.refresh();
                        android.widget.Toast.makeText(a, "Deleted. Your dump and saves are untouched.", android.widget.Toast.LENGTH_LONG).show();
                    });
                }, "nxpack-delete").start();
            });
        }
    }
}
