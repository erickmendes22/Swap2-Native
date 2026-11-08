package dev.nxnative.android;

import android.app.ActivityManager;
import android.app.usage.StorageStats;
import android.app.usage.StorageStatsManager;
import android.content.Context;
import android.os.storage.StorageManager;
import android.text.format.Formatter;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * What the app keeps on the phone, measured by category and by game (Settings › Storage: StorageUi), the leftovers nothing uses removed at each launcher start
 * (atStart, once per process), and the same breakdown as plain text in &lt;Switch2&gt;/Swap2-Native-armazenamento.txt, which a user who cannot open Android/data
 * can send. A friend's phone held 70 GB of "user data" after a save import picked a huge folder: the old code's &lt;save&gt;.restore copy filled the disk and
 * nothing ever removed it (SaveStore.restoreLocked now records the pair before the copy, and clearLeftovers removes such copies).
 * <p>
 * The app's data: the external files dir (Android/data/&lt;package&gt;/files: packs/, saves/, temp/, logs/, gpu_drivers/, root/, aoc/, loose ctl/env files), the
 * external cache dir, and the internal data dir (files/pack/&lt;version&gt;: the packer's Python and tools, files/gpu_drivers/, files/save/&lt;id&gt; (the first
 * versions' private save), no_backup/split.scan/&lt;id&gt;, cache/, shared_prefs/). Save backups are on shared storage (Prefs.backupsDir) and are counted apart.
 * <p>
 * The automatic cleanup removes only what is provably unused, and skips anything in use:
 * <ul>
 * <li>files/pack/&lt;v&gt; of other APK builds (PackEngine.start keeps only this build's, but only when a preparation runs); this build's &lt;v&gt;.tmp only while no
 *     :pack process lives (it may be unpacking)</li>
 * <li>packs/&lt;id&gt;.partial (a stopped Import pack) and packs/&lt;id&gt;.replaced once packs/&lt;id&gt; is there (PackZip.recover first), holding that game's
 *     PackUi slot (an import or export of it working skips it); a pack's shaders/.import-* and .replaced-* (ShaderZip.recover), and a .restamp-* untouched
 *     for an hour, under the same slot</li>
 * <li>beside each save (every card's save folder and every entry of saves/, whether or not a card names it), under the save's lock and after its journal is
 *     finished (SaveStore.recoverLocked): &lt;part&gt;.new, .re, .restore, the import staging (SaveZip.staging) and the migrate staging (SaveMigrate.staging);
 *     the Storage page's cleanup also the host's .work and .work.re (the host leaves .work after every game and clears and clones it again at each mount,
 *     hle_fs.c, so the launcher start leaves it: clean). A held lock (the game runs, a backup or restore works) or an unfinished swap skips that save</li>
 * <li>temp/&lt;id&gt;/vk_pipelines*.bin without a generation (the host reads only VKA_PCACHE_GEN's "-fp…" files and removes the old one of the current driver
 *     only) and vk_*.tmp of a stopped write, while no :game process lives</li>
 * <li>no_backup/split.scan/&lt;id&gt; of every game but the remembered unfinished job's, while no :pack process lives (PackService.dropOtherSplitScans does the same
 *     when a job starts); nothing when the remembered job cannot be read</li>
 * <li>logs/selftest-*.log beyond the newest KEEP_SELFTEST_LOGS (game logs: GameActivity.pruneLogs)</li>
 * </ul>
 * On shared storage outside Android/data (save backups, Work/, Shaders/, a picked folder) only the copies beside a card's save are removed (under that save's
 * lock), and the Storage page deletes there only older save backups (pruneBackups): never a library of a pack on shared storage, which the other app variant
 * may use (oldLibsDeletable). The start's measurement leaves shared storage out (scan with shared false).
 */
final class AppStorageReport {
    private static final String TAG = "Swap2Native";
    static final String REPORT = "Swap2-Native-armazenamento.txt";
    private static final String ID = "[0-9A-Fa-f]{16}";
    /** The working copies beside each part of a save: the host's &lt;save&gt;.work, its reclone .work.re, a commit's .new (hle_fs.c); SaveStore's .re and .restore */
    static final String[] SAVE_COPIES = {".new", ".re", ".work", ".work.re", SaveStore.RESTORE_SUFFIX};
    static final int KEEP_SELFTEST_LOGS = 5, KEEP_BACKUPS = 3;
    private static final long STAGING_AGE_MS = 3600_000L;

    private AppStorageReport() {}

    /** The categories: their name, the sentence that explains them, their icon */
    enum Cat {
        PACK_CODE(R.string.s2_storage_cat_pack, R.string.s2_storage_about_pack, R.drawable.s2_ic_file),
        SHADERS_CURRENT(R.string.s2_storage_cat_shaders, R.string.s2_storage_about_shaders, R.drawable.s2_ic_image),
        SHADERS_OLD(R.string.s2_storage_cat_shaders_old, R.string.s2_storage_about_shaders_old, R.drawable.s2_ic_image),
        SAVES(R.string.s2_storage_cat_saves, R.string.s2_storage_about_saves, R.drawable.s2_ic_lock),
        BACKUPS(R.string.s2_storage_cat_backups, R.string.s2_storage_about_backups, R.drawable.s2_ic_folder_open),
        PIPELINES(R.string.s2_storage_cat_pipelines, R.string.s2_storage_about_pipelines, R.drawable.s2_ic_gauge),
        GAME_TEMP(R.string.s2_storage_cat_temp, R.string.s2_storage_about_temp, R.drawable.s2_ic_grid),
        LOGS(R.string.s2_storage_cat_logs, R.string.s2_storage_about_logs, R.drawable.s2_ic_list),
        CAPTURES(R.string.s2_storage_cat_captures, R.string.s2_storage_about_captures, R.drawable.s2_ic_image),
        PACKER(R.string.s2_storage_cat_packer, R.string.s2_storage_about_packer, R.drawable.s2_ic_settings),
        PREPARE_SCAN(R.string.s2_storage_cat_prepare, R.string.s2_storage_about_prepare, R.drawable.s2_ic_filter),
        GPU_DRIVERS(R.string.s2_storage_cat_drivers, R.string.s2_storage_about_drivers, R.drawable.s2_ic_chip),
        LEFTOVERS(R.string.s2_storage_cat_leftovers, R.string.s2_storage_about_leftovers, R.drawable.s2_ic_warning),
        CACHE(R.string.s2_storage_cat_cache, R.string.s2_storage_about_cache, R.drawable.s2_ic_refresh),
        OTHER(R.string.s2_storage_cat_other, R.string.s2_storage_about_other, R.drawable.s2_ic_more);

        final int title, about, icon;

        Cat(int title, int about, int icon) {
            this.title = title;
            this.about = about;
            this.icon = icon;
        }
    }

    private static final int N = Cat.values().length;

    /** One measured file or folder: its category, its game (null: none), its bytes; inApp false for what is on shared storage (backups, a card's pack or save there) */
    static final class Entry {
        final File file;
        final Cat cat;
        final String id;
        final long bytes;
        final boolean inApp;

        Entry(File file, Cat cat, String id, long bytes, boolean inApp) {
            this.file = file;
            this.cat = cat;
            this.id = id;
            this.bytes = bytes;
            this.inApp = inApp;
        }
    }

    /** One game's share: a card's game, or the data of a title ID no card names any more */
    static final class GameUse {
        final String id;
        String name;
        Game card;
        File pack, save, backupsDir;
        boolean packInApp, saveInApp, libOk, running, jobPack;
        List<SaveStore.Backup> backups = new ArrayList<>();
        final long[] bytes = new long[N], outside = new long[N];

        GameUse(String id) { this.id = id; name = id; }

        long inApp() { long t = 0; for (long b : bytes) t += b; return t; }

        long outsideTotal() { long t = 0; for (long b : outside) t += b; return t; }
    }

    /** A measurement: per category (in the app's data, and outside it), per game, every entry; Android's own numbers when it gives them */
    static final class Scan {
        final long[] bytes = new long[N], outside = new long[N];
        final List<Entry> entries = new ArrayList<>();
        final Map<String, GameUse> games = new LinkedHashMap<>();
        long total, free = -1, androidData = -1, androidCache = -1, androidApp = -1, when;
        boolean gameProcess, packProcess, shared;
        String packerVersion;
        /** The pack folders (paths as measured) that hold this APK's library of their game: their older libraries are not needed */
        final Set<String> currentPacks = new HashSet<>();

        long leftovers() { return bytes[Cat.LEFTOVERS.ordinal()]; }
    }

    /** What a scan has counted so far (StorageUi's progress line) */
    static final class Progress {
        volatile long files, bytes;
    }

    /** What a cleanup removed: the bytes, and one line per removed file or folder (also logged) */
    static final class Cleaned {
        long freed;
        final List<String> lines = new ArrayList<>();

        void delete(File f, String why) {
            if (!f.exists() && !Files.isSymbolicLink(f.toPath())) return;
            long n = size(f, null);
            SaveStore.deleteTree(f);
            long left = f.exists() ? size(f, null) : 0;
            add(f, n - left, why + (left > 0 ? " (" + left + " bytes could not be removed)" : ""));
        }

        void add(File f, long n, String why) {
            freed += n;
            String l = f + ": " + n + " bytes, " + why;
            lines.add(l);
            Log.i(TAG, "storage: removed " + l);
        }
    }

    /** A deletion refused for a reason the user can fix or should know (a game or a preparation runs, the save is in use, the pack has a card): text is its string */
    static final class Blocked extends IOException {
        final int text;

        Blocked(int text) {
            super("blocked");
            this.text = text;
        }
    }

    private static volatile Cleaned startClean;

    /** What the cleanup at this process's launcher start removed (null until it has run) */
    static Cleaned startClean() { return startClean; }

    /**
     * The launcher's start (MainActivity.clearSaveLeftovers, once per process): the automatic cleanup (without the host's .work copies: clean), then a
     * measurement of the app's own storage only (scan with shared false: no walk of packs and backups on shared storage at every start) written to the report
     * file, on a background thread. freed gets the toast's text (on that thread) when anything was removed
     */
    static void atStart(Context app, java.util.function.Consumer<String> freed) {
        new Thread(() -> {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            try {
                Cleaned cl = clean(app, null, false);
                startClean = cl;
                Log.i(TAG, "storage: the start's cleanup freed " + cl.freed + " bytes");
                if (cl.freed > 0 && freed != null) freed.accept(app.getString(R.string.s2_storage_freed_start, size(app, cl.freed)));
                File r = writeReport(app, scan(app, null, false), cl);
                if (r != null) Log.i(TAG, "storage: report written to " + r);
            } catch (RuntimeException e) {
                Log.w(TAG, "storage: the start's cleanup or report failed", e);
            }
        }, "nx-storage").start();
    }

    // ---- Helpers ----

    static String size(Context c, long b) { return Formatter.formatFileSize(c, Math.max(0, b)); }

    /** The bytes of a file or a folder's files; links are not followed. p counts the files */
    static long size(File f, Progress p) {
        if (Files.isSymbolicLink(f.toPath())) return 0;
        if (!f.isDirectory()) {
            long n = f.length();
            if (p != null) { p.files++; p.bytes += n; }
            return n;
        }
        long t = 0;
        File[] l = f.listFiles();
        if (l != null) for (File x : l) t += size(x, p);
        return t;
    }

    /** The newest modification time under f (a folder's files and itself) */
    private static long newest(File f) {
        long t = f.lastModified();
        if (Files.isSymbolicLink(f.toPath()) || !f.isDirectory()) return t;
        File[] l = f.listFiles();
        if (l != null) for (File x : l) t = Math.max(t, newest(x));
        return t;
    }

    /** The title ID a name starts with (after a leading dot: .&lt;id&gt;.migrate), as written; null when none */
    static String idIn(String name) {
        String n = name.startsWith(".") ? name.substring(1) : name;
        return n.length() >= 16 && n.substring(0, 16).matches(ID) ? n.substring(0, 16) : null;
    }

    /**
     * Whether a process of this app with that name suffix (":game", ":pack") lives; true when Android does not say (the cautious answer). ":pack" counts only
     * above cached, as Switch2Migration.busy: a cached :pack process has no worker (its service stopped, as after a pause), while a worker that waits
     * (PackService.waitWhileAuto: battery, heat) keeps its service and stays above cached. ":game" counts at any importance (its process holds the save's lock)
     */
    static boolean processAlive(Context c, String suffix) {
        try {
            List<ActivityManager.RunningAppProcessInfo> l = c.getSystemService(ActivityManager.class).getRunningAppProcesses();
            if (l == null) return true;
            String want = c.getPackageName() + suffix;
            boolean anyImportance = !suffix.equals(":pack");
            for (ActivityManager.RunningAppProcessInfo p : l)
                if (want.equals(p.processName) && (anyImportance || p.importance < ActivityManager.RunningAppProcessInfo.IMPORTANCE_CACHED)) return true;
            return false;
        } catch (RuntimeException e) {
            return true;
        }
    }

    /** This APK's packer version (assets/pack/version.txt: PackEngine), null when the APK has none (the simulated engine) */
    static String packerVersion(Context c) {
        try (BufferedReader b = new BufferedReader(new InputStreamReader(c.getAssets().open("pack/version.txt"), StandardCharsets.UTF_8))) {
            String v = b.readLine();
            return v != null && v.trim().matches("[0-9a-f]{16}") ? v.trim() : null;
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /** The job the launcher remembers; known false when it is remembered but cannot be read (shared storage unreadable: decide nothing from it) */
    private static final class JobState {
        boolean known = true;
        String titleId;   // an unfinished job's game, null when none
        File pack;   // the remembered job's pack folder (any state), null when none
    }

    private static JobState job(Context c) {
        JobState s = new JobState();
        File f = Job.remembered(c);
        if (f == null) return s;
        try {
            Job j = Job.read(f);
            s.pack = j.pack();
            if (!"done".equals(j.state()) && !j.titleId().isEmpty()) s.titleId = j.titleId();
        } catch (IOException | RuntimeException e) {
            s.known = false;
        }
        return s;
    }

    /** A save's parts (the main save and its device save beside it) */
    private static File[] parts(File save) { return new File[] {save, SaveStore.device(save)}; }

    private static File sibling(File b, String suffix) { return new File(b.getAbsoluteFile().getParentFile(), b.getName() + suffix); }

    // ---- The automatic cleanup ----

    /** The Storage page's cleanup (Clean up leftovers, a game's leftovers): also the host's .work copies (clean(c, onlyId, true)) */
    static Cleaned clean(Context c, String onlyId) { return clean(c, onlyId, true); }

    /**
     * Removes the leftovers nothing uses (see the class comment); onlyId: one game's (its save's copies, its pack's staging, its old-generation pipeline caches),
     * null: everything, also the packer trees, the split scans and the self-test logs. work: also the host's &lt;save&gt;.work and .work.re. The launcher start
     * passes false: the host leaves .work after every game (hle_fs.c clears and clones it again at the next mount), so removing it there would take every save's
     * lock at every start (a Play tapped meanwhile would be refused: GameActivity.holdLock) and free nothing for long. Never throws
     */
    static Cleaned clean(Context c, String onlyId, boolean work) {
        Cleaned r = new Cleaned();
        try {
            boolean game = processAlive(c, ":game"), pack = processAlive(c, ":pack");
            JobState job = job(c);
            if (onlyId == null) cleanPacker(c, pack, r);
            cleanPacks(c, onlyId, pack, job, r);
            cleanSaves(c, onlyId, work, r);
            if (!game) cleanTemp(c, onlyId, r);
            if (onlyId == null && !pack) cleanSplitScans(c, job, r);
            if (onlyId == null) cleanSelftestLogs(c, r);
        } catch (RuntimeException e) {
            Log.w(TAG, "storage: cleanup stopped", e);
        }
        return r;
    }

    private static boolean wanted(String onlyId, String id) { return onlyId == null || id != null && onlyId.equalsIgnoreCase(id); }

    private static void cleanPacker(Context c, boolean packRuns, Cleaned r) {
        String v = packerVersion(c);
        File[] l = new File(c.getFilesDir(), "pack").listFiles();
        if (v == null || l == null) return;
        for (File f : l) {
            String n = f.getName();
            if (n.equals(v) || packRuns && n.equals(v + ".tmp")) continue;
            r.delete(f, "the packer tools of another app build");
        }
    }

    private static void cleanPacks(Context c, String onlyId, boolean packRuns, JobState job, Cleaned r) {
        File packs = AppStorage.packs(c);
        File[] l = packs.listFiles();
        if (l == null) return;
        for (File f : l) {
            String n = f.getName(), id = idIn(n);
            if (id == null || !wanted(onlyId, id)) continue;
            boolean staging = n.equals(id) && f.isDirectory() && hasStaging(f);
            if (!n.equals(id + PackZip.PARTIAL) && !n.equals(id + PackZip.REPLACED) && !staging) continue;   // the usual case: the slot is not taken (Play waits for it)
            // the game's pack slot is held for the whole check and deletion: an Import pack or a shaders import/export (PackUi.run, ShaderUi) that starts meanwhile
            // is refused as "still working" instead of having its staged <id>.partial deleted or its swapIn's two renames undone; a slot already held skips the pack
            if (!PackUi.take(id)) continue;
            try {
                if (n.equals(id + PackZip.PARTIAL)) r.delete(f, "a pack import that stopped");
                else if (n.equals(id + PackZip.REPLACED)) {
                    File target = new File(packs, id);
                    PackZip.recover(target);   // a swap that stopped before the new pack had its name: the old one comes back
                    if (target.isDirectory() && f.exists()) r.delete(f, "the pack a finished import replaced");
                } else if (staging && !(packRuns && (!job.known || job.pack != null && SaveStore.same(job.pack, f)))) cleanShaderStaging(f, r);
            } finally {
                PackUi.give(id);
            }
        }
    }

    /** Whether a pack's shaders/ holds dot-named staging (.import-*, .replaced-*, .restamp-*) */
    private static boolean hasStaging(File packDir) {
        String[] l = new File(packDir, "shaders").list((d, x) -> x.startsWith("."));
        return l != null && l.length > 0;
    }

    /** A pack's shaders/.import-* and .replaced-* (ShaderZip.recover decides each) and a .restamp-* no restamp has written to for an hour */
    private static void cleanShaderStaging(File packDir, Cleaned r) {
        File sh = new File(packDir, "shaders");
        File[] l = sh.listFiles(f -> f.getName().startsWith("."));
        if (l == null || l.length == 0) return;
        Map<File, Long> before = new HashMap<>();
        for (File f : l) if (f.getName().startsWith(ShaderZip.IMPORT) || f.getName().startsWith(ShaderZip.REPLACED)) before.put(f, size(f, null));
        if (!before.isEmpty()) {
            ShaderZip.recover(packDir);
            for (Map.Entry<File, Long> e : before.entrySet()) if (!e.getKey().exists()) r.add(e.getKey(), e.getValue(), "a shaders import or swap that stopped");
        }
        long now = System.currentTimeMillis();
        for (File f : l) if (f.getName().startsWith(".restamp-") && f.exists() && now - newest(f) > STAGING_AGE_MS) r.delete(f, "a shader library restamp that stopped");
    }

    /** Every card's save, then every save in saves/ (also one no card names) */
    private static void cleanSaves(Context c, String onlyId, boolean work, Cleaned r) {
        Set<String> seen = new HashSet<>();
        for (Game g : Game.load(c)) {
            if (!wanted(onlyId, g.titleId)) continue;
            File s = Folders.save(c, g);
            if (s != null && seen.add(SaveStore.canon(s))) cleanSave(s, work, r);
        }
        File saves = new File(AppStorage.root(c), "saves");
        File[] l = saves.listFiles();
        if (l == null) return;
        for (File f : l) {
            String id = idIn(f.getName());
            if (id == null || !wanted(onlyId, id)) continue;
            File s = new File(saves, id);
            if (seen.add(SaveStore.canon(s))) cleanSave(s, work, r);
        }
    }

    /** The host's own work copy and its reclone, which it leaves after every game and clears at the next mount */
    private static boolean hostWork(String suffix) { return suffix.equals(".work") || suffix.equals(".work.re"); }

    /**
     * The copies beside one save, under its lock and after its journal is finished; nothing while the lock is held or a swap is unfinished. work false: the
     * host's .work and .work.re are not looked for (no lock is taken for them alone)
     */
    static void cleanSave(File save, boolean work, Cleaned r) {
        List<File> found = new ArrayList<>();
        for (File b : parts(save)) for (String x : SAVE_COPIES) if ((work || !hostWork(x)) && sibling(b, x).exists()) found.add(sibling(b, x));
        for (File f : new File[] {SaveZip.staging(save), SaveStore.device(SaveZip.staging(save)), SaveMigrate.staging(save)}) if (f.exists()) found.add(f);
        if (found.isEmpty()) return;   // the usual case: no lock file is made
        try (SaveStore.Lock l = SaveStore.tryLock(save)) {
            if (l == null) { Log.i(TAG, "storage: " + save + " is in use (its game runs, or a backup or restore works): its copies are left for now"); return; }
            SaveStore.recoverLocked(save);
            if (SaveStore.pending(save)) return;
            for (File f : found) {
                File b = f.getName().startsWith(SaveStore.device(save).getName()) ? SaveStore.device(save) : save;
                if (SaveStore.marker(b, 1).exists() || SaveStore.marker(b, 2).exists()) continue;   // a swap names it (pending says none, checked again)
                r.delete(f, "a copy beside the save " + save.getName() + " that no game or swap uses");
            }
            long more = SaveStore.clearLeftoversLocked(save);   // what SaveStore itself counts as left over (the same copies; anything it learns later)
            if (more > 0) r.add(save, more, "save leftovers (SaveStore)");
        } catch (IOException | RuntimeException e) {
            Log.w(TAG, "storage: the copies beside " + save + " are left: " + e.getMessage());
        }
    }

    /** temp/&lt;id&gt;: pipeline caches without a generation (no host reads them) and stopped writes (vk_*.tmp); only while no game runs */
    private static void cleanTemp(Context c, String onlyId, Cleaned r) {
        File[] l = new File(AppStorage.root(c), "temp").listFiles(f -> f.isDirectory() && f.getName().matches(ID));
        if (l == null) return;
        for (File d : l) {
            if (!wanted(onlyId, d.getName())) continue;
            File[] k = d.listFiles(File::isFile);
            if (k == null) continue;
            for (File f : k) {
                String n = f.getName();
                if (n.startsWith("vk_") && n.endsWith(".tmp")) r.delete(f, "a cache write that stopped");
                else if (n.matches("vk_pipelines(-[^.]+)?\\.bin") && !n.contains("-fp")) r.delete(f, "a pipeline cache of an earlier generation (no host reads it)");
            }
        }
    }

    private static void cleanSplitScans(Context c, JobState job, Cleaned r) {
        if (!job.known) return;
        File[] l = new File(c.getNoBackupFilesDir(), "split.scan").listFiles();
        if (l == null) return;
        for (File f : l) if (job.titleId == null || !f.getName().equals(job.titleId)) r.delete(f, "the shader scan of a preparation that is not unfinished");
    }

    private static void cleanSelftestLogs(Context c, Cleaned r) {
        File[] l = LogProvider.dir(c).listFiles((d, n) -> n.startsWith("selftest-") && n.endsWith(".log"));
        if (l == null || l.length <= KEEP_SELFTEST_LOGS) return;
        Arrays.sort(l, Comparator.comparingLong(File::lastModified).reversed());
        for (int i = KEEP_SELFTEST_LOGS; i < l.length; i++) r.delete(l[i], "an older graphics test log");
    }

    // ---- The measurement ----

    /** Measures the app's data and what its games keep on shared storage (the Storage page) */
    static Scan scan(Context c, Progress p) { return scan(c, p, true); }

    /**
     * Measures the app's data (off the main thread: it walks every file); shared: also each card's pack and save on shared storage and the save backups
     * (FUSE: slow, and a Work or dump pack is large), which the launcher start's report leaves out
     */
    static Scan scan(Context c, Progress p, boolean shared) {
        Scan s = new Scan();
        s.shared = shared;
        s.when = System.currentTimeMillis();
        s.gameProcess = processAlive(c, ":game");
        s.packProcess = processAlive(c, ":pack");
        s.packerVersion = packerVersion(c);
        JobState job = job(c);
        List<Game> cards = Game.load(c);
        for (Game g : cards) {
            GameUse u = game(s, g.titleId);
            if (u.card != null) continue;
            u.card = g;
            u.name = g.name;
        }
        File ext = c.getExternalFilesDir(null), data = c.getDataDir();
        if (ext != null && !SaveStore.inside(ext, data)) {
            files(c, s, ext, false, p);
            File top = ext.getParentFile();   // Android/data/<package>
            File[] l = top == null ? null : top.listFiles();
            if (l != null) for (File f : l) {
                if (f.getName().equals(ext.getName())) continue;
                if (f.getName().equals("cache")) children(s, f, Cat.CACHE, p);
                else add(s, f, Cat.OTHER, null, true, p);
            }
        }
        File[] l = data.listFiles();
        if (l != null) for (File f : l) {
            String n = f.getName();
            if (Files.isSymbolicLink(f.toPath())) continue;   // lib: the APK's libraries
            if (n.equals("files")) files(c, s, f, true, p);
            else if (n.equals("no_backup")) {
                File[] k = f.listFiles();
                if (k != null) for (File x : k) {
                    if (!x.getName().equals("split.scan")) { add(s, x, Cat.OTHER, null, true, p); continue; }
                    File[] g = x.listFiles();
                    if (g != null) for (File y : g) add(s, y, Cat.PREPARE_SCAN, idIn(y.getName()), true, p);
                }
            } else if (n.equals("cache")) children(s, f, Cat.CACHE, p);   // its entries, so a deletion keeps the folder (code_cache is ART's: Other)
            else add(s, f, Cat.OTHER, null, true, p);
        }
        // a card's pack or save on shared storage (a picked folder, the old default beside the game): shown with its game, outside the app's data
        Set<String> seen = new HashSet<>();
        for (Game g : cards) {
            GameUse u = s.games.get(g.titleId);
            File pk = new File(g.packDir);
            boolean in = SaveStore.inside(pk, AppStorage.packs(c));
            if (u.card == g) { u.pack = pk; u.packInApp = in; }   // the first card's pack folder is the one the game plays
            if (shared && !in && pk.isDirectory() && seen.add(SaveStore.canon(pk))) pack(s, u, pk, false, p);
            File sv = Folders.save(c, g);
            if (sv != null && u.save == null) {
                u.save = sv;
                u.saveInApp = SaveStore.inside(sv, new File(AppStorage.root(c), "saves"));
                if (shared && !u.saveInApp && seen.add(SaveStore.canon(sv))) {
                    for (File b : parts(sv)) {
                        if (b.exists()) add(s, b, Cat.SAVES, g.titleId, false, p);
                        for (String x : SAVE_COPIES) if (sibling(b, x).exists()) add(s, sibling(b, x), Cat.LEFTOVERS, g.titleId, false, p);
                    }
                }
            }
            File bk = SaveUi.backups(g);
            if (shared && u.backupsDir == null && bk.isDirectory() && seen.add(SaveStore.canon(bk))) backups(s, u, bk, p);
        }
        for (GameUse u : s.games.values()) {
            if (u.save == null) { u.save = AppStorage.save(c, u.id); u.saveInApp = true; }
            if (u.pack == null) { u.pack = new File(AppStorage.packs(c), u.id); u.packInApp = true; }
            if (u.card == null) {
                Profile pr = Profile.of(u.id);
                if (pr != null) u.name = pr.name;
                File bk = new File(Switch2Layout.root(), "save-backups/" + u.id);
                if (shared && bk.isDirectory() && seen.add(SaveStore.canon(bk))) backups(s, u, bk, p);
            }
            try { u.libOk = u.pack.isDirectory() && Pack.libraryProblem(u.pack, u.id) == null; } catch (RuntimeException e) { u.libOk = false; }
            u.jobPack = !job.known || job.pack != null && SaveStore.same(job.pack, u.pack);
            u.running = s.gameProcess && SaveStore.lockFile(u.save).exists() && SaveStore.inUse(u.save);
        }
        for (Entry e : s.entries) if (e.inApp && e.cat != Cat.BACKUPS) s.total += e.bytes;
        File where = ext != null ? ext : data;
        s.free = where.getUsableSpace();
        try {
            StorageStats st = c.getSystemService(StorageStatsManager.class).queryStatsForPackage(StorageManager.UUID_DEFAULT, c.getPackageName(), android.os.Process.myUserHandle());
            s.androidData = st.getDataBytes();
            s.androidCache = st.getCacheBytes();
            s.androidApp = st.getAppBytes();
        } catch (Exception e) {
            Log.w(TAG, "storage: Android's own numbers for this app are not there: " + e);
        }
        return s;
    }

    private static void children(Scan s, File dir, Cat k, Progress p) {
        File[] l = dir.listFiles();
        if (l != null) for (File f : l) add(s, f, k, null, true, p);
    }

    private static GameUse game(Scan s, String id) {
        if (id == null) return null;
        for (Map.Entry<String, GameUse> e : s.games.entrySet()) if (e.getKey().equalsIgnoreCase(id)) return e.getValue();
        GameUse u = new GameUse(id);
        s.games.put(id, u);
        return u;
    }

    private static void add(Scan s, File f, Cat k, String id, boolean inApp, Progress p) {
        long n = size(f, p);
        s.entries.add(new Entry(f, k, id, n, inApp));
        (inApp ? s.bytes : s.outside)[k.ordinal()] += n;
        GameUse u = game(s, id);
        if (u != null) (inApp ? u.bytes : u.outside)[k.ordinal()] += n;
    }

    /** A files dir (the external one, or the internal one: internal also has pack/, save/ and its own gpu_drivers/) */
    private static void files(Context c, Scan s, File dir, boolean internal, Progress p) {
        File[] l = dir.listFiles();
        if (l == null) return;
        for (File f : l) {
            String n = f.getName();
            if (Files.isSymbolicLink(f.toPath())) continue;
            File[] k = f.isDirectory() ? f.listFiles() : null;
            switch (n) {
                case "packs":
                    if (k != null) for (File x : k) {
                        String xn = x.getName(), id = idIn(xn);
                        if (id != null && xn.equals(id) && x.isDirectory()) {
                            GameUse u = game(s, id);
                            pack(s, u, x, true, p);
                        } else add(s, x, id != null && (xn.endsWith(PackZip.PARTIAL) || xn.endsWith(PackZip.REPLACED)) ? Cat.LEFTOVERS : Cat.OTHER, id, true, p);
                    }
                    break;
                case "saves":
                    if (k != null) for (File x : k) {
                        String xn = x.getName(), id = idIn(xn);
                        Cat cat = id == null ? Cat.OTHER : xn.equalsIgnoreCase(id) || xn.equalsIgnoreCase(id + SaveStore.DEVICE_SUFFIX) || xn.endsWith(SaveStore.LOCK_SUFFIX)
                                || xn.matches(".*\\.pend[12]") || xn.endsWith(SaveStore.SET_SUFFIX) ? Cat.SAVES : Cat.LEFTOVERS;
                        add(s, x, cat, id, true, p);
                    }
                    break;
                case "temp":
                    if (k != null) for (File x : k) {
                        String xn = x.getName(), id = idIn(xn);
                        File[] y = xn.matches(ID) ? x.listFiles() : null;
                        if (y != null) {
                            for (File z : y) {
                                String zn = z.getName();
                                // the host's own files there: vk_pipelines* (the pipeline cache and its prewarm keys), vk_view_formats.txt (learned view formats:
                                // kept, Other), nan-*.blk (NaN scan dumps); the rest is the game's temporary storage (the mount is temp/<id> itself)
                                add(s, z, zn.startsWith("vk_pipelines") ? Cat.PIPELINES : zn.startsWith("vk_") ? Cat.OTHER
                                        : zn.startsWith("nan-") && zn.endsWith(".blk") ? Cat.CAPTURES : Cat.GAME_TEMP, id, true, p);
                            }
                        } else add(s, x, id != null ? Cat.GAME_TEMP : Cat.OTHER, id, true, p);   // <id>_cache<n>, <id>_sysdata
                    }
                    break;
                case "logs":
                    if (k != null) for (File x : k) add(s, x, Cat.LOGS, idIn(x.getName()), true, p);
                    break;
                case "gpu_drivers":
                    add(s, f, Cat.GPU_DRIVERS, null, true, p);
                    break;
                case "root":   // cheats/ (the user's), run/ (the host's probe dumps)
                    if (k != null) for (File x : k) add(s, x, x.getName().equals("run") ? Cat.CAPTURES : Cat.OTHER, null, true, p);
                    break;
                case "pack":
                    if (internal && k != null) {
                        for (File x : k) add(s, x, s.packerVersion == null || x.getName().equals(s.packerVersion) ? Cat.PACKER : Cat.LEFTOVERS, null, true, p);
                        break;
                    }
                    add(s, f, Cat.OTHER, null, true, p);
                    break;
                case "save":   // the first versions' private save (GameActivity.saveDir's fallback)
                    if (internal && k != null) {
                        for (File x : k) add(s, x, Cat.SAVES, idIn(x.getName()), true, p);
                        break;
                    }
                    add(s, f, Cat.OTHER, null, true, p);
                    break;
                default:
                    boolean dump = f.isFile() && n.matches("(?i).*\\.(png|blk|raw|dump|rgba)");   // DM_CTL screenshots and dumps (its folder is HOME)
                    add(s, f, dump ? Cat.CAPTURES : Cat.OTHER, null, true, p);
            }
        }
    }

    /** A pack folder: its shaders/v-&lt;this version&gt; (current), other v-* (older), dot-named staging (leftovers), the rest (code) */
    private static void pack(Scan s, GameUse u, File dir, boolean inApp, Progress p) {
        File[] l = dir.listFiles();
        if (l == null) return;
        try {
            if (Pack.libraryProblem(dir, u.id) == null) s.currentPacks.add(dir.getAbsoluteFile().getPath());
        } catch (RuntimeException e) {
            // no current library known: its older ones stay
        }
        String current = "v-" + BuildConfig.NX_DMSH_VK_CHAIN;
        for (File f : l) {
            File[] k = f.getName().equals("shaders") && f.isDirectory() ? f.listFiles() : null;
            if (k == null) { add(s, f, Cat.PACK_CODE, u.id, inApp, p); continue; }
            for (File x : k) {
                String n = x.getName();
                add(s, x, n.startsWith(".") ? Cat.LEFTOVERS : n.startsWith("v-") && !n.equals(current) && x.isDirectory() ? Cat.SHADERS_OLD : Cat.SHADERS_CURRENT, u.id, inApp, p);
            }
        }
    }

    private static void backups(Scan s, GameUse u, File dir, Progress p) {
        u.backupsDir = dir;
        u.backups = SaveStore.list(dir);
        add(s, dir, Cat.BACKUPS, u.id, false, p);
    }

    // ---- Deleting from the Storage page (each checks again, on its thread, that nothing uses what it deletes) ----

    /** The entries of a category (of one game, or of all when id is null) */
    static List<Entry> entries(Scan s, Cat k, String id) {
        List<Entry> out = new ArrayList<>();
        for (Entry e : s.entries) if (e.cat == k && (id == null || id.equalsIgnoreCase(e.id))) out.add(e);
        return out;
    }

    /**
     * Bytes of the older shader libraries the page may delete: in the app's own packs (Android/data/&lt;package&gt;/files/packs) whose current library is in place.
     * A pack on shared storage (Switch2/Work/&lt;id&gt;, a picked folder) may be the other app variant's too (com.swap2native and com.swap2native.test share one
     * Work pack, each with its own library version): its older libraries are never deleted here
     */
    static long oldLibsDeletable(Scan s, String id) {
        long t = 0;
        for (Entry e : entries(s, Cat.SHADERS_OLD, id)) if (e.inApp && s.currentPacks.contains(packOf(e.file).getPath())) t += e.bytes;
        return t;
    }

    /** The pack folder of a shaders/v-&lt;V&gt; folder */
    private static File packOf(File lib) { return lib.getAbsoluteFile().getParentFile().getParentFile(); }

    /**
     * Deletes a category's files of one game (id) or of all: older shader libraries (only of games whose current library is in place, not while a game or that
     * pack's preparation runs), pipeline caches, temporary storage, captures (no game running), cache (no game and no preparation running), the preparation's
     * scans (no preparation running). → the bytes freed
     */
    static long delete(Context c, Scan s, Cat k, String id) throws IOException {
        boolean game = processAlive(c, ":game"), pack = processAlive(c, ":pack");
        switch (k) {
            case SHADERS_OLD: case PIPELINES: case GAME_TEMP: case CAPTURES:
                if (game) throw new Blocked(R.string.s2_storage_running_any);
                break;
            case CACHE:
                if (game) throw new Blocked(R.string.s2_storage_running_any);
                if (pack) throw new Blocked(R.string.s2_storage_prep_running);
                break;
            case PREPARE_SCAN:
                if (pack) throw new Blocked(R.string.s2_storage_prep_running);
                break;
            case LOGS:
                return pruneLogs(c, s, id);
            case LEFTOVERS:
                return clean(c, id).freed;
            default:
                throw new IOException("nothing of " + k + " is deleted here");
        }
        JobState job = job(c);
        Cleaned r = new Cleaned();
        for (Entry e : entries(s, k, id)) {
            if (!e.inApp) continue;   // shared storage (a pack in Switch2/Work or a picked folder): the other app variant may need it (oldLibsDeletable)
            if (k == Cat.SHADERS_OLD) {
                File pk = packOf(e.file);
                if (e.id == null || Pack.libraryProblem(pk, e.id) != null) continue;   // that pack has no current library (again): the game may still need an older one
                if (pack && (!job.known || job.pack != null && SaveStore.same(job.pack, pk))) continue;
                if (!PackUi.take(e.id)) continue;   // an export or import of that pack works
                try {
                    r.delete(e.file, "deleted from Settings › Storage (" + k + ")");
                } finally {
                    PackUi.give(e.id);
                }
                continue;
            }
            r.delete(e.file, "deleted from Settings › Storage (" + k + ")");
        }
        return r.freed;
    }

    /** Every log but the newest of each game (and the newest graphics test log) */
    private static long pruneLogs(Context c, Scan s, String id) {
        Map<String, List<File>> by = new HashMap<>();
        for (Entry e : entries(s, Cat.LOGS, id)) {
            String n = e.file.getName(), key = e.id != null ? e.id : n.startsWith("selftest-") ? "selftest" : n;
            by.computeIfAbsent(key, x -> new ArrayList<>()).add(e.file);
        }
        Cleaned r = new Cleaned();
        for (List<File> l : by.values()) {
            l.sort(Comparator.comparingLong(File::lastModified).reversed());
            for (int i = 1; i < l.size(); i++) r.delete(l.get(i), "an older log");
        }
        return r.freed;
    }

    /** Keeps the newest keep backups of a game, under its save's lock (no backup or restore of it works, its game does not run) */
    static long pruneBackups(GameUse u, int keep) throws IOException {
        if (u.backupsDir == null) return 0;
        try (SaveStore.Lock l = SaveStore.tryLock(u.save)) {
            if (l == null) throw new Blocked(R.string.s2_storage_save_busy);   // the game, or a backup, restore, import or migration of the save
            List<SaveStore.Backup> list = SaveStore.list(u.backupsDir);
            Cleaned r = new Cleaned();
            for (int i = keep; i < list.size(); i++) {
                SaveStore.Backup b = list.get(i);
                r.delete(new File(u.backupsDir, b.name + SaveStore.MANIFEST), "an older save backup's manifest");
                r.delete(b.dir, "an older save backup");
            }
            return r.freed;
        }
    }

    /** Deletes a game's save in the app's storage (both parts, the first versions' private copy, the copies beside it), under its lock */
    static long deleteSave(Context c, GameUse u) throws IOException {
        if (!u.saveInApp) throw new Blocked(R.string.s2_storage_save_outside);
        try (SaveStore.Lock l = SaveStore.tryLock(u.save)) {
            if (l == null) throw new Blocked(R.string.s2_storage_save_busy);
            SaveStore.recoverLocked(u.save);
            Cleaned r = new Cleaned();
            for (File b : parts(u.save)) {
                for (String x : SAVE_COPIES) r.delete(sibling(b, x), "a copy beside the deleted save");
                r.delete(b, "the save, deleted from Settings › Storage");
            }
            r.delete(new File(c.getFilesDir(), "save/" + u.id), "the first versions' private copy of the deleted save");
            r.freed += SaveStore.clearLeftoversLocked(u.save);
            return r.freed;
        }
    }

    /** Whether a game's pack in the app's storage may be deleted here: no card names its game, no remembered preparation writes it, no import works on it */
    static boolean packDeletable(Scan s, GameUse u) { return u.card == null && u.packInApp && !u.jobPack && u.pack.isDirectory(); }

    static long deletePack(Context c, Scan s, GameUse u) throws IOException {
        if (processAlive(c, ":game")) throw new Blocked(R.string.s2_storage_running_any);
        JobState job = job(c);
        if (!job.known || job.pack != null && SaveStore.same(job.pack, u.pack)) throw new Blocked(R.string.s2_storage_prep_running);
        for (Game g : Game.load(c)) if (g.titleId.equalsIgnoreCase(u.id)) throw new Blocked(R.string.s2_storage_pack_has_card);
        if (!PackUi.take(u.id)) throw new Blocked(R.string.s2_storage_pack_busy);
        try {
            Cleaned r = new Cleaned();
            r.delete(u.pack, "the pack of a game with no card, deleted from Settings › Storage");
            return r.freed;
        } finally {
            PackUi.give(u.id);
        }
    }

    // ---- The report ----

    private static String line(Context c, Cat k, long in, long out) {
        return c.getString(k.title) + ": " + size(c, in) + (out > 0 ? (in > 0 ? " + " : "") + size(c, out) + " " + c.getString(R.string.s2_storage_outside_short) : "");
    }

    /** The categories, largest first */
    static List<Cat> sorted(long[] in, long[] out) {
        List<Cat> l = new ArrayList<>(Arrays.asList(Cat.values()));
        l.sort((a, b) -> Long.compare(in[b.ordinal()] + out[b.ordinal()], in[a.ordinal()] + out[a.ordinal()]));
        return l;
    }

    static String report(Context c, Scan s, Cleaned cl) {
        StringBuilder b = new StringBuilder();
        b.append(c.getString(R.string.s2_storage_report_title)).append('\n');
        b.append(Prefs.buildTag(c)).append(" · ").append(c.getPackageName()).append('\n');
        b.append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date(s.when))).append("\n\n");
        b.append(c.getString(R.string.s2_storage_total, size(c, s.total))).append(" (").append(s.total).append(" bytes)\n");
        if (s.androidData >= 0) b.append(c.getString(R.string.s2_storage_android, size(c, s.androidData - s.androidCache), size(c, s.androidCache))).append('\n');
        if (s.free >= 0) b.append(c.getString(R.string.s2_storage_free, size(c, s.free))).append('\n');
        if (!s.shared) b.append(c.getString(R.string.s2_storage_report_app_only)).append('\n');
        if (s.gameProcess) b.append(c.getString(R.string.s2_storage_running_any)).append('\n');
        if (s.packProcess) b.append(c.getString(R.string.s2_storage_prep_running)).append('\n');
        if (cl != null) {
            b.append(c.getString(R.string.s2_storage_report_freed, size(c, cl.freed))).append('\n');
            for (String l : cl.lines) b.append("  ").append(l).append('\n');
        }
        b.append('\n').append(c.getString(R.string.s2_storage_by_category)).append('\n');
        for (Cat k : sorted(s.bytes, s.outside)) {
            if (s.bytes[k.ordinal()] == 0 && s.outside[k.ordinal()] == 0) continue;
            b.append("  ").append(line(c, k, s.bytes[k.ordinal()], s.outside[k.ordinal()])).append('\n');
        }
        b.append('\n').append(c.getString(R.string.s2_storage_by_game)).append('\n');
        for (GameUse u : s.games.values()) {
            b.append("  ").append(u.name).append(" (").append(u.id).append(")").append(u.card == null ? " · " + c.getString(R.string.s2_storage_no_card) : "")
                    .append(": ").append(size(c, u.inApp())).append('\n');
            for (Cat k : sorted(u.bytes, u.outside)) {
                if (u.bytes[k.ordinal()] == 0 && u.outside[k.ordinal()] == 0) continue;
                b.append("    ").append(line(c, k, u.bytes[k.ordinal()], u.outside[k.ordinal()]));
                if (k == Cat.BACKUPS) b.append(" · ").append(c.getResources().getQuantityString(R.plurals.s2_storage_backups_count, u.backups.size(), u.backups.size()));
                b.append('\n');
            }
            b.append("    pack: ").append(u.pack).append(u.libOk ? "" : " (" + c.getString(R.string.s2_storage_lib_missing) + ")").append('\n');
            b.append("    save: ").append(u.save).append('\n');
        }
        b.append('\n').append(c.getString(R.string.s2_storage_report_largest)).append('\n');
        List<Entry> big = new ArrayList<>(s.entries);
        big.sort((x, y) -> Long.compare(y.bytes, x.bytes));
        for (int i = 0; i < Math.min(30, big.size()) && big.get(i).bytes > 0; i++) {
            Entry e = big.get(i);
            b.append(String.format(Locale.ROOT, "  %14d  %-15s %s%s%n", e.bytes, e.cat, e.file, e.inApp ? "" : "  [shared storage]"));
        }
        return b.toString();
    }

    /** The report file in the Switch2 folder: written by a .tmp and a rename; null when it could not be written (no file access yet) */
    static File reportFile() { return new File(Switch2Layout.root(), REPORT); }

    private static long reportWhen;   // the start time of the scan the report file was last written from (this process)

    /**
     * synchronized: the start's report (atStart) and the Storage page's (StorageUi.measure) can be written at once, and both use the one .tmp name. A scan
     * that started before the one already written does not replace it (the start's app-only scan finishing after the page's full one)
     */
    static synchronized File writeReport(Context c, Scan s, Cleaned cl) {
        File out = reportFile(), tmp = new File(out.getPath() + ".tmp");
        if (out.getParentFile() == null || !out.getParentFile().isDirectory()) return null;
        if (s.when < reportWhen && out.isFile()) return out;
        try {
            try (FileOutputStream o = new FileOutputStream(tmp)) {
                o.write(report(c, s, cl).getBytes(StandardCharsets.UTF_8));
                o.getFD().sync();
            }
            if (!tmp.renameTo(out)) {
                out.delete();
                if (!tmp.renameTo(out)) throw new IOException("cannot rename " + tmp + " to " + out);
            }
            reportWhen = s.when;
            return out;
        } catch (IOException | RuntimeException e) {
            tmp.delete();
            Log.w(TAG, "storage: the report " + out + " was not written: " + e.getMessage());
            return null;
        }
    }
}
