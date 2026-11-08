package dev.nxnative.android;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * The exefs patches (mods) of a game's modules, chosen as dm/tools/exefs_patches.py chooses them for the rewrite (scripts/pack_android.py --mods, DM_MODS_DIR): the
 * same folders, files, order and digest, so the launcher can tell that a pack's code was rewritten with another set of mods (PackCheck.mods) without the tools.
 * Under the mods folder ({@link #root}: &lt;Switch2&gt;/Mods): &lt;title ID&gt;/&lt;mod&gt;/exefs/&lt;build ID&gt;.ips or .pchtxt (yuzu and Eden's layout), and
 * &lt;title ID&gt;/exefs_patches/&lt;mod&gt;/… (Atmosphere's); a mod folder whose name starts with '-' is off. Plain Java (no Android classes): the JVM tests run it.
 */
final class ExefsMods {
    private ExefsMods() {}

    /** One patch file: its label (the path below the title folder, as exefs_patches.py names it) and the file */
    static final class Entry {
        final String label;
        final File file;

        Entry(String label, File file) { this.label = label; this.file = file; }
    }

    /**
     * The mods folder beside the profiles: &lt;shared storage&gt;/Switch2/Mods (android/README.md "Mods (exefs patches)"), or the older mods/ while it is there
     * and Mods/ is not (the launcher's start moves it: Switch2Migration; on the phone's case-insensitive storage the two names are one folder)
     */
    static File root(File profilesDir) {
        File sw = profilesDir.getParentFile();
        String[] l = sw == null ? null : sw.list();
        boolean neu = false, old = false;
        if (l != null) for (String n : l) { neu |= n.equals("Mods"); old |= n.equals("mods"); }
        return new File(sw, !neu && old ? "mods" : "Mods");
    }

    private static final Comparator<File> BY_NAME = Comparator.comparing(File::getName);

    private static File[] sorted(File[] fs) {
        if (fs == null) return new File[0];
        Arrays.sort(fs, BY_NAME);
        return fs;
    }

    /** d's subfolder called name in any case, the first by name when several are (exefs_patches.child) */
    static File child(File d, String name) {
        for (File f : sorted(d.listFiles(File::isDirectory))) if (f.getName().equalsIgnoreCase(name)) return f;
        return null;
    }

    /** The folders of patch files for the title, in order: &lt;mod&gt;/exefs, and exefs_patches/&lt;mod&gt; (exefs_patches.mod_dirs) */
    static List<Entry> modDirs(File root, String titleId) {
        List<Entry> out = new ArrayList<>();
        File t = root != null && root.isDirectory() ? child(root, titleId) : null;
        if (t == null) return out;
        for (File m : sorted(t.listFiles(File::isDirectory))) {
            if (m.getName().startsWith("-")) continue;
            if (m.getName().equalsIgnoreCase("exefs_patches")) {
                for (File a : sorted(m.listFiles(File::isDirectory))) if (!a.getName().startsWith("-")) out.add(new Entry(m.getName() + "/" + a.getName(), a));
            } else {
                File e = child(m, "exefs");
                if (e != null) out.add(new Entry(m.getName() + "/" + e.getName(), e));
            }
        }
        return out;
    }

    /** The build ID as 64 lowercase hex digits: h zero-padded (or cut) to 64 */
    static String pad(String h) {
        StringBuilder s = new StringBuilder(h.toLowerCase(Locale.ROOT));
        while (s.length() < 64) s.append('0');
        return s.substring(0, 64);
    }

    private static boolean hex(char c) { return c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F'; }

    private static boolean space(char c) { return c == ' ' || c == '\t' || c == 0x0b || c == '\f'; }

    /** A .pchtxt line without its leading space, its comment ('/' or '#' outside quotes) and its trailing space (exefs_patches.strip_line) */
    static String stripLine(String s) {
        int i = 0;
        while (i < s.length() && space(s.charAt(i))) i++;
        s = s.substring(i);
        char quote = 0;
        int end = 0;
        i = 0;
        while (i < s.length()) {
            char c = s.charAt(i);
            if (space(c)) { i++; continue; }
            if (quote == 0 && (c == '/' || c == '#')) break;
            if (c == '"' || c == '\'') { quote = quote == c ? 0 : quote != 0 ? quote : c; i++; }
            else if (c == '\\' && i + 1 < s.length()) i += 2;
            else i++;
            end = i;
        }
        return s.substring(0, end);
    }

    /** The build ID a .pchtxt file is for (exefs_patches.pchtxt_build_id): the hex digits after "@nsobid-" of its last @n… line before any @s… line, padded; null without one */
    static String pchtxtBuildId(byte[] b) {
        String id = null;
        for (String raw : new String(b, StandardCharsets.ISO_8859_1).split("[\r\n]", -1)) {
            String ln = stripLine(raw);
            if (ln.length() <= 2 || ln.charAt(0) != '@') continue;
            char k = ln.charAt(1);
            if (k == 's' || k == 'S') break;
            if (k == 'n' || k == 'N') {
                int e = Math.min(8, ln.length());
                while (e < ln.length() && hex(ln.charAt(e))) e++;
                id = pad(ln.substring(Math.min(8, ln.length()), e));
            }
        }
        return id;
    }

    private static String ext(String name) {
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
    }

    /** The patch files for a module of buildId (hex, the whole 0x20 bytes or fewer) under root, in the order they apply (exefs_patches.find) */
    static List<Entry> find(File root, String titleId, String buildId) throws IOException {
        String want = pad(buildId);
        List<Entry> out = new ArrayList<>();
        for (Entry d : modDirs(root, titleId))
            for (File f : sorted(d.file.listFiles(File::isFile))) if (applies(f, want)) out.add(new Entry(d.label + "/" + f.getName(), f));
        return out;
    }

    /** Whether a file of a mod's folder is a patch for the module of want (a padded build ID): find's choice of one file */
    static boolean applies(File f, String want) throws IOException {
        String n = f.getName(), x = ext(n);
        if (n.startsWith(".")) return false;   // a hidden file (macOS's ._ companions), as exefs_patches.find
        if (x.equals(".ips")) {
            String stem = n.substring(0, n.indexOf('.'));
            return !stem.isEmpty() && stem.length() <= 64 && stem.chars().allMatch(c -> hex((char) c)) && pad(stem).equals(want);
        }
        return x.equals(".pchtxt") && want.equals(pchtxtBuildId(Files.readAllBytes(f.toPath())));
    }

    /** SHA-256 (hex) of the patch files: label, '\0', length, '\0', bytes of each, in order (exefs_patches.digest); "" for none */
    static String digest(List<Entry> files) throws IOException {
        if (files.isEmpty()) return "";
        MessageDigest h;
        try {
            h = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
        for (Entry e : files) {
            byte[] b = Files.readAllBytes(e.file.toPath());
            h.update((e.label + "\0" + b.length + "\0").getBytes(StandardCharsets.UTF_8));
            h.update(b);
        }
        StringBuilder s = new StringBuilder();
        for (byte x : h.digest()) s.append(String.format(Locale.ROOT, "%02x", x & 0xff));
        return s.toString();
    }

    /** What changes when the title's mods change: every file below its mod folders, by path, size and time (PackCheck.code's cache) */
    static String stamp(File root, String titleId) {
        StringBuilder s = new StringBuilder();
        for (Entry d : modDirs(root, titleId))
            for (File f : sorted(d.file.listFiles(File::isFile))) s.append(d.label).append('/').append(f.getName()).append(':').append(f.length()).append(':').append(f.lastModified()).append(';');
        return s.toString();
    }

    /** The " mods=&lt;digest&gt;" part of a module's key (scripts/pack_android.py rewrite_key), "" when it has none */
    static String keyPart(String key) {
        int i = key.indexOf(" mods=");
        return i < 0 ? "" : key.substring(i + 6).trim();
    }

    // ---- A game's mods as its settings page shows and changes them (GameSettings' Mods section): list, on and off, remove, add ----

    /** Atmosphere's folder of mods in a title folder: never a mod itself, so never made, renamed or removed here */
    static final String ATMOSPHERE = "exefs_patches";

    /** A mod folder of a title, on or off: &lt;title&gt;/&lt;mod&gt; (its patches in exefs/) or &lt;title&gt;/exefs_patches/&lt;mod&gt; (Atmosphere's: in the folder itself) */
    static final class Mod {
        final File dir;
        final String name;   // the folder's name without the leading '-' that turns it off
        final boolean on, atmosphere;
        final boolean groupOff;   // an Atmosphere mod in a "-exefs_patches" folder: off with the whole folder, whatever its own name

        Mod(File dir, boolean atmosphere) { this(dir, atmosphere, false); }

        Mod(File dir, boolean atmosphere, boolean groupOff) {
            this.dir = dir;
            this.atmosphere = atmosphere;
            this.groupOff = groupOff;
            on = !groupOff && !dir.getName().startsWith("-");
            name = bare(dir.getName());
        }

        /** The folder of its patch files, as modDirs takes it: exefs/ in any case (Atmosphere's: the mod's folder); null when it has none */
        File exefs() { return atmosphere ? dir : child(dir, "exefs"); }

        /** Its patch files (.ips and .pchtxt, not hidden ones), by name */
        List<File> patches() {
            List<File> out = new ArrayList<>();
            File e = exefs();
            if (e != null) for (File f : sorted(e.listFiles(File::isFile))) if (patch(f.getName())) out.add(f);
            return out;
        }

        /** Its patch files for the module of buildId, as find chooses them when the mod is on */
        List<File> matching(String buildId) throws IOException {
            String want = pad(buildId);
            List<File> out = new ArrayList<>();
            for (File f : patches()) if (applies(f, want)) out.add(f);
            return out;
        }
    }

    /** A name without its leading '-' (a mod that is off) */
    static String bare(String n) {
        int i = 0;
        while (i < n.length() && n.charAt(i) == '-') i++;
        return n.substring(i);
    }

    /** A patch file's name: .ips or .pchtxt (any case), not hidden */
    static boolean patch(String n) {
        String x = ext(n);
        return !n.startsWith(".") && (x.equals(".ips") || x.equals(".pchtxt"));
    }

    /** Whether a title folder's entry is Atmosphere's folder of mods, on ("exefs_patches") or off ("-exefs_patches"), in any case */
    static boolean atmosphereGroup(String n) { return bare(n).equalsIgnoreCase(ATMOSPHERE); }

    /**
     * Every mod folder of the title, on and off, in modDirs' order (an Atmosphere one in exefs_patches/ where modDirs reads it). The mods of a "-exefs_patches"
     * folder (Atmosphere's folder turned off as a whole, which modDirs skips) are listed too, off (Mod.groupOff); the folder itself is never a mod
     */
    static List<Mod> list(File root, String titleId) {
        List<Mod> out = new ArrayList<>();
        File t = root != null && root.isDirectory() ? child(root, titleId) : null;
        if (t == null) return out;
        for (File m : sorted(t.listFiles(File::isDirectory))) {
            if (atmosphereGroup(m.getName())) { for (File a : sorted(m.listFiles(File::isDirectory))) out.add(new Mod(a, true, m.getName().startsWith("-"))); }
            else out.add(new Mod(m, false));
        }
        return out;
    }

    /** The names (lower case, without '-') of the title's mods in both layouts, other than self: Add mod's and the clash rule's "already there" */
    static Set<String> names(File root, String titleId, File self) {
        Set<String> out = new HashSet<>();
        for (Mod m : list(root, titleId)) if (self == null || !m.dir.equals(self)) out.add(m.name.toLowerCase(Locale.ROOT));
        return out;
    }

    /** Whether parent holds name, on or off ("name" or "-name"), in any case (shared storage's names are case-blind), other than self */
    static boolean taken(File parent, String name, File self) {
        String[] l = parent.list();
        if (l != null) for (String n : l) if (bare(n).equalsIgnoreCase(name) && (self == null || !new File(parent, n).equals(self))) return true;
        return false;
    }

    /** The clash rule: name when parent does not hold it (on or off), else the first free "name (2)", "name (3)"…; never Atmosphere's folder name */
    static String freeName(File parent, String name, File self) { return freeName(parent, name, self, Collections.emptySet()); }

    /** freeName, also avoiding the names in also (lower case: the other layout's mods, names already handed out) */
    static String freeName(File parent, String name, File self, Set<String> also) {
        String n = name;
        for (int k = 2; taken(parent, n, self) || n.equalsIgnoreCase(ATMOSPHERE) || also.contains(n.toLowerCase(Locale.ROOT)); k++) n = name + " (" + k + ")";
        return n;
    }

    /**
     * Turns a mod on (its folder's name without '-') or off (with one), in its folder; a clash with another folder takes the first free name. A mod of a
     * "-exefs_patches" folder turned on moves into "exefs_patches" (made when there is none), so its neighbours stay off. Returns the mod as it is now
     */
    static Mod setEnabled(Mod m, boolean on) throws IOException {
        if (m.on == on) return m;
        File parent = m.dir.getParentFile();
        if (m.groupOff) {   // on (off it is already): out of the folder that is off
            File title = parent.getParentFile();
            File live = child(title, ATMOSPHERE);
            if (live == null) live = new File(title, ATMOSPHERE);
            if (!live.isDirectory() && !live.mkdirs()) throw new IOException("cannot create " + live);
            File to = new File(live, freeName(live, m.name, null));
            if (!m.dir.renameTo(to)) throw new IOException("cannot move " + m.dir.getName() + " into " + live);
            return new Mod(to, true);
        }
        File to = new File(parent, (on ? "" : "-") + freeName(parent, m.name, m.dir));
        if (!m.dir.renameTo(to)) throw new IOException("cannot rename " + m.dir.getName() + " to " + to.getName());
        return new Mod(to, m.atmosphere);
    }

    /** Deletes one mod folder of the title with what is in it (links themselves, never what they point to) and nothing else: m must be one of list's */
    static void remove(File root, String titleId, Mod m) throws IOException {
        boolean known = false;
        for (Mod x : list(root, titleId)) known |= x.dir.getAbsolutePath().equals(m.dir.getAbsolutePath());
        if (!known) throw new IOException(m.dir + " is not a mod folder of " + titleId);
        deleteTree(m.dir.toPath());
    }

    /** A file or folder and everything below it; a link is removed, not followed */
    static void deleteTree(Path p) throws IOException {
        if (!Files.exists(p, LinkOption.NOFOLLOW_LINKS)) return;
        Files.walkFileTree(p, new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult visitFile(Path f, BasicFileAttributes a) throws IOException { Files.delete(f); return FileVisitResult.CONTINUE; }

            @Override public FileVisitResult postVisitDirectory(Path d, IOException e) throws IOException {
                if (e != null) throw e;
                Files.delete(d);
                return FileVisitResult.CONTINUE;
            }
        });
    }

    static final long MAX_BYTES = 16L << 20;   // of patch files in one install (a code mod is a few KB)
    static final int MAX_FILES = 256, MAX_ENTRIES = 65536, MAX_DEPTH = 8;
    static final String STAGING = ".installing-";   // root/.installing-<n>: what an install unpacks, before it is moved into the title folder
    private static final java.util.concurrent.atomic.AtomicInteger STAGINGS = new java.util.concurrent.atomic.AtomicInteger();

    /** What a picked zip, file or folder holds: its mods (each a folder of the staging folder, with exefs/), and the files left out with why */
    static final class Staged {
        final File dir;
        final Map<String, String> mods = new LinkedHashMap<>();   // lower-case name → the name, in the order they came
        final List<String> skipped = new ArrayList<>();   // "<path in the zip> (<why>)"
        int files;
        long bytes;

        Staged(File dir) { this.dir = dir; }

        List<String> names() { return new ArrayList<>(mods.values()); }
    }

    /**
     * Where a file of a picked zip or folder goes: { its mod's name ("" for the zip's own name), its file name }, or null with why in why[0] (null: a hidden file,
     * left out without a word). Taken: &lt;mod&gt;/exefs/&lt;file&gt; (deeper too: &lt;title ID&gt;/&lt;mod&gt;/exefs/…), exefs/&lt;file&gt;, &lt;file&gt;,
     * exefs_patches/&lt;mod&gt;/&lt;file&gt;, where the file is .ips or .pchtxt. Never an absolute path or one with "..".
     */
    static String[] place(String entry, String[] why) {
        why[0] = null;
        String e = entry.replace('\\', '/');
        if (e.startsWith("/") || e.length() > 1 && e.charAt(1) == ':') { why[0] = "an absolute path"; return null; }
        List<String> s = new ArrayList<>();
        for (String p : e.split("/")) {
            if (p.equals("..")) { why[0] = "a path that leaves its folder"; return null; }
            if (!p.isEmpty() && !p.equals(".")) s.add(p);
        }
        if (s.isEmpty()) return null;
        for (String p : s) if (p.startsWith(".") || p.equals("__MACOSX")) return null;
        int n = s.size();
        String file = s.get(n - 1);
        if (!patch(file)) { why[0] = "not an .ips or .pchtxt file"; return null; }
        if (file.length() > 128 || !file.equals(file.replaceAll("[\\\\:*?\"<>|\\p{Cntrl}]", ""))) { why[0] = "a file name the storage cannot hold"; return null; }
        if (n == 1 || n == 2 && s.get(0).equalsIgnoreCase("exefs")) return new String[] {"", file};
        if (s.get(n - 2).equalsIgnoreCase("exefs")) return new String[] {s.get(n - 3), file};
        if (n >= 3 && s.get(n - 3).equalsIgnoreCase(ATMOSPHERE)) return new String[] {s.get(n - 2), file};
        why[0] = "not in an exefs folder";
        return null;
    }

    /** A mod folder's name from a zip's or a mod's: no leading '-', '.' or space (an installed mod is on), no character the storage refuses, at most 64; "" when none is left */
    static String cleanName(String s) {
        String t = s.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replaceAll("^[-. ]+", "").replaceAll("[. ]+$", "");
        return t.length() > 64 ? t.substring(0, 64).trim() : t;
    }

    /** A picked file's name without its folder and extension ("My mod.zip" → "My mod") */
    static String stem(String fileName) {
        String n = fileName.replace('\\', '/');
        n = n.substring(n.lastIndexOf('/') + 1);
        int dot = n.lastIndexOf('.');
        return dot > 0 ? n.substring(0, dot) : n;
    }

    private interface Filler { void fill(Staged st) throws IOException; }

    /** One file of a picked zip or folder into the staging folder, when place takes it: at most MAX_BYTES and MAX_FILES in all, an .ips only when it is one */
    private static void add(Staged st, String entry, String defaultName, InputStream in) throws IOException {
        String[] why = new String[1];
        String[] at = place(entry, why);
        if (at == null) { if (why[0] != null) st.skipped.add(entry + " (" + why[0] + ")"); return; }
        String mod = cleanName(at[0]);
        if (mod.isEmpty()) mod = cleanName(defaultName);
        if (mod.isEmpty()) mod = "mod";
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        byte[] buf = new byte[1 << 16];
        int k;
        while ((k = in.read(buf)) > 0) {
            if (st.bytes + o.size() + k > MAX_BYTES) throw new IOException("more than " + (MAX_BYTES >> 20) + " MB of patch files: not a code mod");
            o.write(buf, 0, k);
        }
        byte[] b = o.toByteArray();
        if (ext(at[1]).equals(".ips") && !(startsWith(b, "PATCH") || startsWith(b, "IPS32"))) { st.skipped.add(entry + " (not an IPS patch)"); return; }
        String have = st.mods.get(mod.toLowerCase(Locale.ROOT));
        File d = new File(st.dir, (have != null ? have : mod) + "/exefs");
        if (have != null && taken(d, at[1], null)) { st.skipped.add(entry + " (the same file twice: the first is kept)"); return; }
        if (++st.files > MAX_FILES) throw new IOException("more than " + MAX_FILES + " patch files: not a code mod");
        if (!d.isDirectory() && !d.mkdirs()) throw new IOException("cannot create " + d);
        Files.write(new File(d, at[1]).toPath(), b);
        st.bytes += b.length;
        if (have == null) st.mods.put(mod.toLowerCase(Locale.ROOT), mod);
    }

    private static boolean startsWith(byte[] b, String magic) {
        if (b.length < magic.length()) return false;
        for (int i = 0; i < magic.length(); i++) if (b[i] != magic.charAt(i)) return false;
        return true;
    }

    /** A new staging folder in root filled by f; anything f throws becomes an IOException with the reason, and leaves no staging folder */
    private static Staged stage(File root, Filler f) throws IOException {
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("cannot create " + root);
        long now = System.currentTimeMillis();
        for (File old : sorted(root.listFiles(x -> x.getName().startsWith(STAGING))))
            if (now - old.lastModified() > 3600_000L) deleteTree(old.toPath());   // a killed install's
        File dir = new File(root, STAGING + now + "-" + STAGINGS.incrementAndGet());
        if (!dir.mkdirs()) throw new IOException("cannot create " + dir);
        Staged st = new Staged(dir);
        boolean ok = false;
        try {
            f.fill(st);
            if (st.mods.isEmpty())
                throw new IOException("no .ips or .pchtxt patch in an exefs folder" + (st.skipped.isEmpty() ? "" : " (left out: " + String.join(", ", st.skipped) + ")"));
            ok = true;
            return st;
        } catch (IOException e) {
            if (e.getMessage() != null && !e.getMessage().isEmpty()) throw e;
            throw new IOException("it cannot be read (a damaged or cut-short zip: " + e.getClass().getSimpleName() + ")", e);   // EOFException has no message
        } catch (RuntimeException e) {   // the zip reader's IllegalArgumentException (a name that is not UTF-8), a walk's UncheckedIOException
            throw new IOException("it cannot be read (a damaged zip, or a file name in it that is not UTF-8): " + (e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName()), e);
        } finally {
            if (!ok) deleteQuietly(dir);
        }
    }

    private static void deleteQuietly(File f) {
        try { deleteTree(f.toPath()); } catch (IOException ignored) { /* a killed install's leftover: the next stage removes it */ }
    }

    /** A picked file: a zip (by its first bytes, whatever its name) of mods (see place; a bare patch's mod is named after the zip), or one .ips or .pchtxt (its mod named after it) */
    static Staged stage(File root, InputStream in, String fileName) throws IOException {
        String def = stem(fileName), name = fileName.replace('\\', '/').substring(fileName.replace('\\', '/').lastIndexOf('/') + 1);
        return stage(root, st -> {
            BufferedInputStream b = new BufferedInputStream(in);
            b.mark(4);
            int p = b.read(), k = b.read();
            b.reset();
            if (p == 'P' && k == 'K') {
                ZipInputStream z = new ZipInputStream(b);
                ZipEntry e;
                int n = 0;
                while ((e = z.getNextEntry()) != null) {
                    if (++n > MAX_ENTRIES) throw new IOException("more than " + MAX_ENTRIES + " files in the zip: not a code mod");
                    if (!e.isDirectory()) add(st, e.getName(), def, z);
                }
            } else if (patch(name)) add(st, name, def, b);
            else throw new IOException(name + " is not a .zip, .ips or .pchtxt file");
        });
    }

    /** A picked folder: its files as a zip's, by their paths below it (a bare patch's mod is named after the folder; a picked exefs folder, after the one above it). Links are not followed */
    static Staged stage(File root, File folder) throws IOException {
        File up = folder.getAbsoluteFile().getParentFile();
        String def = folder.getName().equalsIgnoreCase("exefs") && up != null ? up.getName() : folder.getName();
        Path base = folder.toPath();
        return stage(root, st -> {
            if (!Files.isDirectory(base)) throw new IOException(folder + " is not a folder the app can read");
            try (java.util.stream.Stream<Path> w = Files.walk(base, MAX_DEPTH)) {
                int n = 0;
                for (Path p : (Iterable<Path>) w.sorted()::iterator) {
                    if (!Files.isRegularFile(p, LinkOption.NOFOLLOW_LINKS)) continue;
                    if (++n > MAX_ENTRIES) throw new IOException("more than " + MAX_ENTRIES + " files in the folder: not a code mod");
                    String rel = base.relativize(p).toString().replace('\\', '/');
                    if (!patch(p.getFileName().toString())) { add(st, rel, def, null); continue; }   // left out by its name (place): never opened
                    try (InputStream in = Files.newInputStream(p)) { add(st, rel, def, in); }
                }
            }
        });
    }

    /** The title's folder in root (child: in any case), made when there is none */
    static File titleDir(File root, String titleId) throws IOException {
        File t = root.isDirectory() ? child(root, titleId) : null;
        if (t == null) t = new File(root, titleId);
        if (!t.isDirectory() && !t.mkdirs()) throw new IOException("cannot create " + t);
        return t;
    }

    /** The staged mods whose names the title has already (in either layout), on or off and in any case: Add mod asks whether to replace them or keep both */
    static List<String> clashes(File root, String titleId, Staged st) {
        List<String> out = new ArrayList<>();
        File t = root.isDirectory() ? child(root, titleId) : null;
        Set<String> have = names(root, titleId, null);
        for (String n : st.mods.values())
            if (have.contains(n.toLowerCase(Locale.ROOT)) || t != null && taken(t, n, null) || n.equalsIgnoreCase(ATMOSPHERE)) out.add(n);
        return out;
    }

    /** The folder names Keep both gives the staged mods (commit with replace false), in their order: what Add mod's question names */
    static List<String> keepBothNames(File root, String titleId, Staged st) {
        File t = root.isDirectory() ? child(root, titleId) : null;
        if (t == null) t = new File(root, titleId);
        Set<String> used = names(root, titleId, null);
        List<String> out = new ArrayList<>();
        for (String n : st.mods.values()) {
            String to = freeName(t, n, null, used);
            used.add(to.toLowerCase(Locale.ROOT));
            out.add(to);
        }
        return out;
    }

    /**
     * Moves the staged mods into the title's folder, on. replace: a mod of the same name (on or off) is deleted first; else a clashing one takes the first free name
     * ("name (2)"). Returns the folder names they got. The staging folder is gone after, whatever happens.
     */
    static List<String> commit(File root, String titleId, Staged st, boolean replace) throws IOException {
        try {
            File t = titleDir(root, titleId);
            List<String> out = new ArrayList<>();
            for (String n : st.mods.values()) {
                if (replace)   // either layout's mod of that name; list never gives the title's or Atmosphere's folder itself
                    for (Mod old : list(root, titleId)) if (old.name.equalsIgnoreCase(n)) deleteTree(old.dir.toPath());
                File to = new File(t, freeName(t, n, null, names(root, titleId, null)));
                if (!new File(st.dir, n).renameTo(to)) throw new IOException("cannot move " + n + " into " + t);
                out.add(to.getName());
            }
            return out;
        } finally {
            discard(st);
        }
    }

    /** Drops what was staged (Add mod's Cancel) */
    static void discard(Staged st) { deleteQuietly(st.dir); }

    /** stage, then commit (the JVM test; adb) */
    static List<String> install(File root, String titleId, InputStream in, String fileName, boolean replace) throws IOException {
        return commit(root, titleId, stage(root, in, fileName), replace);
    }
}
