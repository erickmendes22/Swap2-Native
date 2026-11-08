package dev.nxnative.android;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * The phone's Switch2 folder (android/README.md "The Switch2 folder"), with no Android classes (the JVM test, android/app/src/jvmtest's Switch2LayoutJvmTest):
 * <pre>
 *   Switch2/Games/            the games: dump folders and .nup files
 *   Switch2/Work/&lt;title ID&gt;/  a game's work folder: Prepare's ondevice/ (job, logs, split, xlate), nvn_shdump/, captures/, packs copied from a Mac
 *   Switch2/Mods/&lt;title ID&gt;/  a game's exefs mods (ExefsMods)
 *   Switch2/Shaders/           the shaders zips of Export shaders… (ShaderZip), kept when the app is uninstalled; Import shaders… lists them
 *   Switch2/profiles, covers, drivers, saves, save-backups, Config, …: the app's data, unchanged
 * </pre>
 * Up to 2026-11-06 the games were in Switch2/ itself, each work folder was &lt;title ID&gt;-work beside its dump and the mods were in mods/. Both layouts are read
 * (games in the root, an old work folder when there is no new one, mods/ when there is no Mods/), and {@link #migrate} moves the old one into the new once (by
 * rename only: never a copy), writing every move to Switch2/move.log, from which {@link #renames} gives the moves to repoint saved paths by ({@link #repoint},
 * {@link #repointJson}, {@link #repointJobs}).
 */
final class Switch2Layout {
    static final String GAMES = "Games", WORK = "Work", MODS = "Mods", OLD_MODS = "mods", SHADERS = "Shaders", LOG = "move.log";
    /** A two-step rename of mods/ into Mods/ on a case-insensitive file system (the phone's shared storage) goes through this name */
    static final String MODS_STEP = ".Mods-moving";
    /** Folders of the root that are the app's data or the layout's own, never a game (lower case) */
    static final Set<String> RESERVED = new HashSet<>(Arrays.asList("games", "work", "mods", "shaders", MODS_STEP.toLowerCase(Locale.ROOT), "profiles", "covers", "drivers",
            "config", "saves", "saves-test", "save-backups", "save-seed", "lost.dir"));
    private static final String WORK_SUFFIX = "-work";

    private Switch2Layout() {}

    // ---- Where things are ----

    /** The Switch2 folder on the shared storage: &lt;EXTERNAL_STORAGE&gt;/Switch2, in its primary form (/storage/emulated/0/Switch2: Frontend.normal) */
    static File root() {
        String s = System.getenv("EXTERNAL_STORAGE");
        return new File(Frontend.normal(new File(s != null && !s.isEmpty() ? s : "/storage/emulated/0", "Switch2").getPath()));
    }

    /** The folder that holds a game's folder or .nup: its parent, or the folder above it when that is Games/ (the Switch2 root of a game in Switch2/Games) */
    static File rootOf(File game) {
        File p = game.getAbsoluteFile().getParentFile();
        if (p != null && p.getName().equalsIgnoreCase(GAMES) && p.getParentFile() != null) return p.getParentFile();
        return p;
    }

    static File gamesDir(File root) { return new File(root, GAMES); }

    /** Where Export shaders… writes its zips by default: &lt;root&gt;/Shaders (shared storage: they outlive an uninstall, unlike the app's packs/) */
    static File shadersDir(File root) { return new File(root, SHADERS); }

    /** A title's work folder in the new layout: &lt;root&gt;/Work/&lt;title ID&gt; */
    static File workDir(File root, String titleId) { return new File(new File(root, WORK), titleId.toUpperCase(Locale.ROOT)); }

    /** The work folder a dump's job uses (DumpCheck.workOf): see {@link #workOf(File, File, String)} with the phone's Switch2 root */
    static File workOf(File dump, String titleId) { return workOf(root(), dump, titleId); }

    /**
     * The work folder of a dump: &lt;Switch2&gt;/Work/&lt;title ID&gt; for a dump inside the Switch2 folder (any depth), else &lt;the folder holding the dump&gt;/Work/&lt;title ID&gt;
     * (rootOf). An older &lt;title ID&gt;-work beside the dump or in that root is used instead while the new one does not exist (the migration moves it when it can)
     */
    static File workOf(File switch2, File dump, String titleId) {
        File d = dump.getAbsoluteFile(), r = rootOf(d);
        if (r == null) r = d;
        File base = switch2 != null && inside(d, switch2.getAbsoluteFile()) ? switch2.getAbsoluteFile() : r;
        File neu = workDir(base, titleId);
        if (neu.isDirectory()) return neu;
        for (File old : new File[] {new File(d.getParentFile() != null ? d.getParentFile() : d, titleId + WORK_SUFFIX), new File(r, titleId + WORK_SUFFIX),
                new File(base, titleId + WORK_SUFFIX)})
            if (old.isDirectory()) return old;
        return neu;
    }

    /** The work folders a folder may hold for a title, the new one first: &lt;dir&gt;/Work/&lt;id&gt; and &lt;dir&gt;/&lt;id&gt;-work (PackFind's candidates, Pack.find) */
    static File[] workDirsIn(File dir, String titleId) { return new File[] {workDir(dir, titleId), new File(dir, titleId + WORK_SUFFIX)}; }

    /** Whether a folder's name is an old work folder's, &lt;16 hex digits&gt;-work */
    static boolean isOldWork(String name) { return name.matches("(?i)[0-9a-f]{16}-work"); }

    /** The mods folder of a root: Mods/, else an older mods/ that is still there (on a case-sensitive file system), else Mods/ (made when a mod is added) */
    static File modsDir(File root) {
        String[] l = root.list();
        boolean neu = false, old = false;
        if (l != null) for (String n : l) { neu |= n.equals(MODS); old |= n.equals(OLD_MODS); }
        return new File(root, !neu && old ? OLD_MODS : MODS);
    }

    /**
     * Where a game the frontend or an older setting names is now: f when it is there, else the same path under &lt;root&gt;/Games when f was in the root (a game
     * the migration moved: the frontend's path is the old one), else f
     */
    static File moved(File root, File f) {
        if (f.exists() || root == null) return f;
        String r = root.getAbsolutePath(), p = f.getAbsolutePath();
        if (!p.startsWith(r) || p.length() <= r.length() + 1 || !isSep(p.charAt(r.length()))) return f;
        File g = new File(gamesDir(root), p.substring(r.length() + 1));
        return g.exists() ? g : f;
    }

    private static boolean inside(File f, File dir) {
        String a = Frontend.normal(f.getPath()), d = Frontend.normal(dir.getPath());   // /sdcard/… and /storage/emulated/0/… name the same folder
        return a.equals(d) || a.startsWith(d) && a.length() > d.length() && isSep(a.charAt(d.length()));
    }

    private static boolean isSep(char c) { return c == '/' || c == File.separatorChar; }

    // ---- The one-time move into the new layout ----

    /** A game's title ID (Pack.titleIdOf, as Add game identifies a game), null when the entry is not a game */
    interface Identify { String titleId(File f); }

    /** What one migrate() did; pending: something left for a later run (a running job, a rename that failed) */
    static final class Report {
        int moved, kept, skipped, failed;
        final List<String> lines = new ArrayList<>();

        // A rename that failed is not retried at every start: Android's storage service renames a folder file by file and gives up on one with tens of
        // thousands of files (an extracted RomFS: Mario Kart World's folder failed with EFAULT after 31 s, "mv" from adb the same after 83 s), so each
        // retry would cost a minute of storage work in the background. The item stays where it is, the scan still finds it in the root, and the log says why
        boolean pending() { return skipped > 0; }

        @Override public String toString() { return "moved " + moved + ", kept " + kept + " (the target exists), skipped " + skipped + " (a job runs), failed " + failed; }
    }

    /**
     * Moves the old layout of root into the new one, by rename only (File.renameTo: the same volume; a rename that fails leaves the item where it is): each
     * game in root (a folder or .nup that identify knows) into Games/, each &lt;id&gt;-work into Work/&lt;ID&gt;, mods/ into Mods/. Never an app data folder
     * (RESERVED) or an entry that is not a game. A title whose Prepare job runs (job.json state "running", in either work folder) is skipped, its game and its work
     * folder alike, and mods/ while any job runs: a later run moves them. An entry whose target exists stays (kept, logged). Every move is written to move.log,
     * its intent before ("move") and its result after ("moved", "failed"), so an interrupted run is finished by the next ({@link #renames}). Idempotent.
     */
    static Report migrate(File root, Identify identify) throws IOException {
        Report rep = new Report();
        String[] names = root.list();
        if (names == null) return rep;
        Arrays.sort(names);
        Set<String> logged = loggedOnce(root);
        Set<String> runningIds = new HashSet<>();
        boolean anyRunning = false;
        for (String n : names) {
            File f = new File(root, n);
            if (isOldWork(n) && f.isDirectory() && "running".equals(jobState(f))) { runningIds.add(n.substring(0, 16).toUpperCase(Locale.ROOT)); anyRunning = true; }
        }
        String[] work = new File(root, WORK).list();
        if (work != null) for (String n : work)
            if ("running".equals(jobState(new File(new File(root, WORK), n)))) { runningIds.add(n.toUpperCase(Locale.ROOT)); anyRunning = true; }

        for (String n : names) {
            if (n.startsWith(".") || n.equals(LOG)) continue;
            File f = new File(root, n);
            if (isOldWork(n) && f.isDirectory()) {
                String id = n.substring(0, 16).toUpperCase(Locale.ROOT);
                if (runningIds.contains(id)) { note(root, rep, logged, "skipped", f, workDir(root, id), "its Prepare job is running"); rep.skipped++; continue; }
                move(root, rep, logged, f, workDir(root, id));
                continue;
            }
            if (RESERVED.contains(n.toLowerCase(Locale.ROOT))) continue;
            if (!f.isDirectory() && !n.toLowerCase(Locale.ROOT).endsWith(".nup")) continue;   // a file that is not a .nup is never a game (Lossless.dll, notes)
            String id = identify.titleId(f);
            if (id == null) continue;   // not a game: left where it is
            if (runningIds.contains(id.toUpperCase(Locale.ROOT))) { note(root, rep, logged, "skipped", f, new File(gamesDir(root), n), "its Prepare job is running"); rep.skipped++; continue; }
            move(root, rep, logged, f, new File(gamesDir(root), n));
        }
        mods(root, rep, logged, anyRunning);
        return rep;
    }

    /** mods/ into Mods/: a rename; on a case-insensitive file system (where Mods names mods/ itself) in two steps through MODS_STEP; both there: each title folder */
    private static void mods(File root, Report rep, Set<String> logged, boolean anyRunning) throws IOException {
        String[] l = root.list();
        boolean neu = false, old = false, step = false;
        if (l != null) for (String n : l) { neu |= n.equals(MODS); old |= n.equals(OLD_MODS); step |= n.equals(MODS_STEP); }
        File oldDir = new File(root, OLD_MODS), newDir = new File(root, MODS), stepDir = new File(root, MODS_STEP);
        if (!old && !step) return;
        if (anyRunning) { note(root, rep, logged, "skipped", oldDir, newDir, "a Prepare job is running"); rep.skipped++; return; }
        if (step && !neu && !old) {   // an interrupted two-step rename: its second step
            if (stepDir.renameTo(newDir)) { log(root, "moved", oldDir, newDir, ""); rep.moved++; }
            else { note(root, rep, logged, "failed", stepDir, newDir, "the rename failed"); rep.failed++; }
            return;
        }
        if (!old) return;
        if (!neu && !newDir.exists()) { move(root, rep, logged, oldDir, newDir); return; }
        if (!neu) {   // a case-insensitive file system: mods/ is Mods/ but for its name
            noteMove(root, logged, oldDir, newDir);
            if (!oldDir.renameTo(stepDir)) { note(root, rep, logged, "failed", oldDir, newDir, "the rename failed"); rep.failed++; return; }
            if (!stepDir.renameTo(newDir)) { note(root, rep, logged, "failed", stepDir, newDir, "the rename failed; the next start finishes it"); rep.failed++; return; }
            log(root, "moved", oldDir, newDir, "");
            rep.moved++;
            return;
        }
        String[] titles = oldDir.list();   // both folders (a case-sensitive file system): each title folder
        if (titles != null) {
            Arrays.sort(titles);
            for (String t : titles) move(root, rep, logged, new File(oldDir, t), new File(newDir, t));
        }
        String[] left = oldDir.list();
        if (left != null && left.length == 0 && oldDir.delete()) log(root, "removed", oldDir, newDir, "empty after its folders moved");
    }

    private static void move(File root, Report rep, Set<String> logged, File from, File to) throws IOException {
        if (to.exists()) { note(root, rep, logged, "kept", from, to, "the target exists"); rep.kept++; return; }
        File parent = to.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) { note(root, rep, logged, "failed", from, to, "cannot make " + parent); rep.failed++; return; }
        noteMove(root, logged, from, to);
        if (from.renameTo(to)) { log(root, "moved", from, to, ""); rep.moved++; rep.lines.add("moved " + from + " -> " + to); }
        else { note(root, rep, logged, "failed", from, to, "the rename failed; left where it is"); rep.failed++; }
    }

    /**
     * The "move" line written before a rename, once per pair: a rename that failed before is retried at each start without a new line (an earlier "move"
     * line still lets renames() find the move when this one succeeds and the run stops before its "moved")
     */
    private static void noteMove(File root, Set<String> logged, File from, File to) throws IOException {
        if (logged.add("move\t" + from.getPath() + "\t" + to.getPath())) log(root, "move", from, to, "");
    }

    /** A line that would say the same at every start (kept, skipped, failed for the same pair) is written once */
    private static void note(File root, Report rep, Set<String> logged, String verb, File from, File to, String why) throws IOException {
        rep.lines.add(verb + " " + from + " (" + why + ")");
        if (logged.add(verb + "\t" + from.getPath() + "\t" + to.getPath())) log(root, verb, from, to, why);
    }

    /**
     * One move.log line: "&lt;yyyy-MM-dd HH:mm:ss&gt;\t&lt;verb&gt;\t&lt;from&gt;\t&lt;to&gt;[\t&lt;why&gt;]", appended and synced (verbs: move, moved, kept, skipped,
     * failed, removed). Lines in another form (an older log) are kept and ignored
     */
    static void log(File root, String verb, File from, File to, String why) throws IOException {
        String line = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()) + "\t" + verb + "\t" + from.getPath() + "\t" + to.getPath()
                + (why == null || why.isEmpty() ? "" : "\t" + why) + "\n";
        File f = new File(root, LOG);
        try (FileOutputStream out = new FileOutputStream(f, true)) {
            out.write(line.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
    }

    private static List<String[]> logRows(File root) {
        List<String[]> out = new ArrayList<>();
        File f = new File(root, LOG);
        if (!f.isFile()) return out;
        try {
            for (String line : Files.readAllLines(f.toPath(), StandardCharsets.UTF_8)) {
                String[] c = line.split("\t");
                if (c.length >= 4 && c[0].matches("\\d{4}-\\d\\d-\\d\\d \\d\\d:\\d\\d:\\d\\d")) out.add(c);
            }
        } catch (IOException e) {
            // an unreadable log: nothing known
        }
        return out;
    }

    private static Set<String> loggedOnce(File root) {
        Set<String> s = new HashSet<>();
        for (String[] c : logRows(root)) s.add(c[1] + "\t" + c[2] + "\t" + c[3]);
        return s;
    }

    /**
     * The moves of move.log that hold now, old path → new path, in their order: each "moved" line, and a "move" whose result was not written (the run was
     * stopped) when its source is gone and its target is there; only while the old path is gone and the new one is there, so a new game put at an old path keeps its own.
     * A "failed" line counts the same way: Android's storage service can report a folder rename as failed (EFAULT after its timeout, Mario Kart World's extracted
     * RomFS, 2026-11-06) and still finish it in the background, so the folder turns up at its new path later
     */
    static Map<String, String> renames(File root) {
        Map<String, String> m = new LinkedHashMap<>();
        for (String[] c : logRows(root)) {
            if (!c[1].equals("moved") && !c[1].equals("move") && !c[1].equals("failed")) continue;
            File from = new File(c[2]), to = new File(c[3]);
            if (to.exists() && (!from.exists() || sameFile(from, to))) m.put(c[2], c[3]);
        }
        return m;
    }

    /** mods/ and Mods/ on a case-insensitive file system */
    private static boolean sameFile(File a, File b) {
        try {
            return Files.isSameFile(a.toPath(), b.toPath());
        } catch (IOException e) {
            return false;
        }
    }

    /**
     * A path after the moves: the first rename whose old path is the path, one of its folders, or the .nup of a package path (&lt;name&gt;.nup:update/…), else the
     * path as it was. Paths compare in Frontend.normal's form
     */
    static String repoint(String path, Map<String, String> renames) {
        if (path == null || path.isEmpty()) return path;
        String p = Frontend.normal(path);
        for (Map.Entry<String, String> e : renames.entrySet()) {
            String from = Frontend.normal(e.getKey());
            if (p.equals(from)) return Frontend.normal(e.getValue());
            if (p.startsWith(from) && p.length() > from.length() && (isSep(p.charAt(from.length())) || p.charAt(from.length()) == ':')) return Frontend.normal(e.getValue()) + p.substring(from.length());
        }
        return path;
    }

    /**
     * A JSON text with each string that is a moved path, or a path inside one, repointed (repoint: any alias form of the path, /sdcard/… as an adb-started
     * job writes its dump, compares in Frontend.normal's form): the job.json fields (dump, work, pack, shader_cache, adopted) and the game list. Each string
     * literal is decoded, repointed and written back only when it changed, with "/" escaped as "\/" when the literal escaped it (Android's org.json does)
     */
    static String repointJson(String json, Map<String, String> renames) {
        if (renames.isEmpty()) return json;
        StringBuilder b = new StringBuilder(json.length());
        int i = 0, n = json.length();
        while (i < n) {
            char c = json.charAt(i);
            if (c != '"') { b.append(c); i++; continue; }
            int j = i + 1;
            boolean esc = false;
            while (j < n && (esc || json.charAt(j) != '"')) { esc = !esc && json.charAt(j) == '\\'; j++; }
            if (j >= n) { b.append(json, i, n); break; }   // an unterminated string: left as it is
            String lit = json.substring(i + 1, j), s = jsonUnescape(lit);
            String t = s == null ? null : repoint(s, renames);
            if (t != null && !t.equals(s)) b.append('"').append(jsonEscape(t, lit.contains("\\/"))).append('"');
            else b.append(json, i, j + 1);
            i = j + 1;
        }
        return b.toString();
    }

    /** A JSON string literal's text, null when it holds what jsonEscape would not write back (a control character, an unknown escape) */
    private static String jsonUnescape(String lit) {
        if (lit.indexOf('\\') < 0) return lit;
        StringBuilder b = new StringBuilder(lit.length());
        for (int i = 0; i < lit.length(); i++) {
            char c = lit.charAt(i);
            if (c != '\\') { b.append(c); continue; }
            if (++i >= lit.length()) return null;
            char e = lit.charAt(i);
            if (e == '"' || e == '\\' || e == '/') b.append(e);
            else if (e == 'u' && i + 4 < lit.length()) {
                char u;
                try { u = (char) Integer.parseInt(lit.substring(i + 1, i + 5), 16); } catch (NumberFormatException x) { return null; }
                if (u < 0x20) return null;
                b.append(u);
                i += 4;
            } else return null;
        }
        return b.toString();
    }

    static String jsonEscape(String s, boolean slash) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '/' && slash) b.append("\\/");
            else b.append(c);
        }
        return b.toString();
    }

    /**
     * Repoints the job.json of every work folder (Work/&lt;id&gt; and the &lt;id&gt;-work left in the root), as Job.save writes it (a .tmp renamed over it), except a
     * running job's (its service writes it; nothing of it moved). → the job files changed
     */
    static int repointJobs(File root, Map<String, String> renames) throws IOException {
        if (renames.isEmpty()) return 0;
        List<File> works = new ArrayList<>();
        File[] w = new File(root, WORK).listFiles(File::isDirectory);
        if (w != null) works.addAll(Arrays.asList(w));
        File[] old = root.listFiles(f -> f.isDirectory() && isOldWork(f.getName()));
        if (old != null) works.addAll(Arrays.asList(old));
        int n = 0;
        for (File work : works) {
            File jf = jobFile(work);
            if (!jf.isFile() || "running".equals(jobState(work))) continue;
            String s = new String(Files.readAllBytes(jf.toPath()), StandardCharsets.UTF_8), t = repointJson(s, renames);
            if (t.equals(s)) continue;
            File tmp = new File(jf.getParentFile(), jf.getName() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(t.getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            Files.move(tmp.toPath(), jf.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            n++;
        }
        return n;
    }

    static File jobFile(File work) { return new File(new File(work, "ondevice"), "job.json"); }

    /** The top-level "state" of a work folder's job.json (Job: pending, running, paused, done, failed), "" when there is none or it does not read */
    static String jobState(File work) {
        File jf = jobFile(work);
        if (!jf.isFile()) return "";
        try {
            return topLevelString(new String(Files.readAllBytes(jf.toPath()), StandardCharsets.UTF_8), "state");
        } catch (IOException e) {
            return "";
        }
    }

    /** The string value of a key of a JSON object's top level (not of the objects in it: a step's own "state"), "" when it has none */
    static String topLevelString(String json, String key) {
        int depth = 0;
        String lastString = null;
        boolean wantValue = false;
        for (int i = 0; i < json.length(); i++) {
            char c = json.charAt(i);
            if (c == '"') {
                StringBuilder b = new StringBuilder();
                for (i++; i < json.length() && json.charAt(i) != '"'; i++) {
                    char d = json.charAt(i);
                    if (d == '\\' && i + 1 < json.length()) { char x = json.charAt(++i); b.append(x == 'n' ? '\n' : x == 't' ? '\t' : x); }
                    else b.append(d);
                }
                if (wantValue && depth == 1) return b.toString();
                wantValue = false;
                lastString = b.toString();
            } else if (c == ':') {
                wantValue = depth == 1 && key.equals(lastString);
            } else if (c == '{' || c == '[') {
                depth++;
                wantValue = false;
            } else if (c == '}' || c == ']') {
                depth--;
            } else if (c == ',') {
                lastString = null;
                wantValue = false;
            } else if (!Character.isWhitespace(c)) {
                if (wantValue && depth == 1) return "";   // a number, true, false or null
            }
        }
        return "";
    }
}
