package dev.nxnative.android;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * A game's Export shaders… and Import shaders… (its Options menu, ShaderUi): only the translated shader library, as a .zip, so a phone that cannot translate a
 * game's shaders (or should not spend the time) plays with a library made elsewhere: on a computer (scripts/shaders_zip.py) or on another phone. The whole pack
 * (code and shaders) goes through PackZip instead. No Android classes: the JVM test (ShaderZipJvmTest, run by dm/tools/tests/test_android_shaderzip.py) runs it.
 * <p>
 * <b>The zip</b> (android/SHADERS.md "Shader zips"): STORED, at its root or in its one top folder, exactly these entries in this order: manifest.tsv (key TAB
 * value: kind swap2-shaders, format 1, the title, the library's version, ABI, chain and inputs digest, its shader count, size and SHA-256, inputs.tsv's SHA-256,
 * who made it), inputs.tsv (the library's stamp: game and profile inputs) and dmsh_vk.lib. Named swap2-shaders-&lt;title ID&gt;-&lt;game version&gt;-v-&lt;V&gt;.zip.
 * <ul>
 * <li><b>Export</b> takes the library Play loads (this APK's version, else the older one the host plays: {@link #chooseExport}), hashes it, writes
 *     &lt;zip&gt;.partial, reads it back with the importer's own reader ({@link #read} with verifyOnly) and only then gives it its name. The pack is only read.</li>
 * <li><b>Import</b> reads the zip as a stream (a File or a content URI's stream, the same code): only the three names, nothing written before the manifest and
 *     the library's header agree with this app (the title, the version, the profile's inputs, the ABI, the tables inside the file, the free space), then the
 *     library is copied into &lt;pack&gt;/shaders/.import-&lt;V&gt;/ (hashed and synced: its size, SHA-256 and CRC must be the manifest's), then {@link #install}
 *     renames it to v-&lt;V&gt; (the one there before kept as .replaced-&lt;V&gt; until then; {@link #recover} puts a stopped swap back). A library of an older version
 *     is taken only when the profile's manifest has a "stamp" row for its exact bytes: it becomes this version's by its header (ShaderLibs.restamp). Nothing on
 *     the phone is translated.</li>
 * </ul>
 * Prepare then skips its shader steps for a pack that holds the library ({@link #ready}: PackService, Job.shadersInPack).
 */
final class ShaderZip {
    static final String KIND = "swap2-shaders", FORMAT = "1";
    static final String MANIFEST = "manifest.tsv", INPUTS = "inputs.tsv", LIB = "dmsh_vk.lib", SOURCE = "source.tsv";
    static final String IMPORT = ".import-", REPLACED = ".replaced-", PARTIAL = ".partial", PREFIX = "swap2-shaders-";
    /** The largest library taken (Pokemon Pokopia's blob is 9.8 GB), the largest manifest.tsv or inputs.tsv, the room kept free beside an import */
    static final long MAX_LIB = 32L << 30, SPARE = 256L << 20;
    static final int MAX_SMALL = 64 << 10;
    private static final int CHUNK = 1 << 20;
    /** Progress phases */
    static final int HASH = 0, WRITE = 1, CHECK = 2, COPY = 3, INSTALL = 4;

    enum Why { NOT_SHADER_ZIP, UNSAFE_NAME, ORDER, OTHER_GAME, OTHER_VERSION, OTHER_INPUTS, DAMAGED, TOO_BIG, NO_SPACE, NO_LIBRARY, BUSY, RUNNING, CANCELLED, IO }

    /**
     * What an I/O failure of this class's own (io) was, so ShaderUi says it in the user's language (its strings s2_shaders_io_&lt;kind&gt;): its args are {kind, path}.
     * Any other I/O failure's one arg is the system's message, as it is
     */
    static final String IO_INSIDE = "inside", IO_CHANGED_READ = "changed_read", IO_CREATE = "create", IO_CHANGED_WRITTEN = "changed_written", IO_READ_BACK = "read_back",
            IO_NAME_ZIP = "name_zip", IO_NOTHING_STAGED = "nothing_staged", IO_MOVE_ASIDE = "move_aside", IO_NAME_LIB = "name_lib", IO_OPEN = "open";

    static Failure io(String message, String kind, Object path) { return new Failure(Why.IO, message, kind, path == null ? "" : String.valueOf(path)); }

    /** Why an export or import stopped; getMessage() is English for logs and tests, ShaderUi shows {@link #why} with {@link #args} in the user's language */
    static final class Failure extends IOException {
        private static final long serialVersionUID = 1L;
        final Why why;
        final String[] args;

        Failure(Why why, String message, String... args) {
            super(message);
            this.why = why;
            this.args = args;
        }
    }

    interface Progress {
        void at(int phase, long done, long total);
        boolean cancelled();
    }

    static final Progress QUIET = new Progress() {
        @Override public void at(int phase, long done, long total) {}
        @Override public boolean cancelled() { return false; }
    };

    /** Free bytes on the volume of a folder (injected by the test) */
    interface Space { long free(File dir); }

    private static final Map<String, Integer> ACTIVE = new java.util.HashMap<>();   // pack folders an import is writing into: recover leaves them alone

    private ShaderZip() {}

    // ---- Names and places ----

    /** swap2-shaders-&lt;title ID&gt;-&lt;game version, or any&gt;-v-&lt;V&gt;.zip */
    static String exportName(String titleId, String gameVersion, String v) {
        String gv = gameVersion == null || gameVersion.isEmpty() ? "any" : gameVersion;
        return PREFIX + clean(titleId) + "-" + clean(gv) + "-v-" + clean(v) + ".zip";
    }

    private static String clean(String s) { return s.replaceAll("[^0-9A-Za-z._-]", "_"); }

    /** The shaders zips of a title in these folders (swap2-shaders-&lt;id&gt;-*.zip), newest first */
    static List<File> found(String titleId, File... dirs) {
        List<File> out = new ArrayList<>();
        String want = (PREFIX + titleId + "-").toLowerCase(Locale.ROOT);
        for (File d : dirs) {
            File[] l = d == null ? null : d.listFiles(f -> f.isFile() && f.getName().toLowerCase(Locale.ROOT).startsWith(want) && f.getName().toLowerCase(Locale.ROOT).endsWith(".zip"));
            if (l != null) for (File f : l) if (!out.contains(f)) out.add(f);
        }
        out.sort((x, y) -> Long.compare(y.lastModified(), x.lastModified()));
        return out;
    }

    /** Whether a folder holds nothing but shaders/ (an import into a game with no pack yet): Prepare's job then calls it its own pack */
    static boolean onlyShaders(File dir) {
        String[] l = dir.list();
        return l != null && l.length == 1 && l[0].equals("shaders");
    }

    /** Whether a pack folder holds this APK's library of this game, built from the profile's inputs: Prepare then translates nothing */
    static boolean ready(File pack, String titleId) {
        File lib = Pack.libraryOf(pack);
        if (lib != null && Pack.libraryProblem(pack, titleId) == null) {
            ShaderLibs.Header h = ShaderLibs.header(lib);
            if (h != null && titleId.equals(h.game) && h.fits(lib.length())
                    && (!Prefs.OCARINA_TITLE.equals(titleId)
                        || h.entries == ShaderLibs.OCARINA_BASE_ENTRIES))
                return true;
        }
        // Full same-ABI Ocarina library: both the original 0.1.2
        // compilation and the user's 42,339-entry version with six replaced
        // entries are imported and played AS-IS. Never demand a pristine SHA.
        Profile profile = Profile.of(titleId);
        return Prefs.OCARINA_TITLE.equals(titleId) && profile != null
                && ShaderLibs.trustedOcarinaBase(pack, titleId,
                    BuildConfig.NX_DMSH_VK_ABI, profile.shaderInputs) != null;
    }

    /** Whether the library was imported (its folder has source.tsv) */
    static boolean imported(File pack) {
        File lib = Pack.libraryOf(pack);
        return lib != null && new File(lib.getParentFile(), SOURCE).isFile();
    }

    /**
     * A swap or import that stopped: a .replaced-&lt;V&gt; whose v-&lt;V&gt; is missing comes back, one whose v-&lt;V&gt; is there goes, and a staged .import-* goes. Not while
     * an import of this process writes into the pack
     */
    static void recover(File pack) {
        File sh = new File(pack, "shaders");
        String[] l = sh.list();
        if (l == null) return;
        synchronized (ACTIVE) {
            if (ACTIVE.containsKey(key(pack))) return;
            for (String n : l) {
                File f = new File(sh, n);
                if (n.startsWith(IMPORT)) deleteTree(f);
                else if (n.startsWith(REPLACED)) {
                    File v = new File(sh, "v-" + n.substring(REPLACED.length()));
                    if (!v.exists()) f.renameTo(v);
                    else deleteTree(f);
                }
            }
        }
    }

    private static String key(File pack) { return SaveStore.canon(pack); }   // /sdcard and /storage/emulated/0 name one folder

    // ---- The manifest ----

    static Map<String, List<String>> rows(byte[] tsv) {
        Map<String, List<String>> rows = new LinkedHashMap<>();
        for (String line : new String(tsv, StandardCharsets.UTF_8).split("\n")) {
            line = line.replace("\r", "");
            int t = line.indexOf('\t');
            if (t > 0 && !line.startsWith("#")) rows.computeIfAbsent(line.substring(0, t), k -> new ArrayList<>()).add(line.substring(t + 1).trim());
        }
        return rows;
    }

    private static String one(Map<String, List<String>> rows, String k) {
        List<String> v = rows.get(k);
        return v == null || v.isEmpty() ? "" : v.get(0);
    }

    private static String tsvValue(String s) { return s == null ? "" : s.replaceAll("[\\t\\r\\n]", " "); }

    /** The stamp of a library folder: its inputs.tsv, else (a library copied without it) one written from the header's game and inputs, as pack_android.py lib_stamp */
    static byte[] stampOf(File libDir, ShaderLibs.Header h) throws IOException {
        File in = new File(libDir, INPUTS);
        if (in.isFile()) {
            if (in.length() > MAX_SMALL) throw new Failure(Why.DAMAGED, in + " is larger than 64 KiB", in.getName());
            return Files.readAllBytes(in.toPath());
        }
        return ("# the game and the profile inputs this library was built from (dm/gfx/tools/dmsh_chain.py inputs)\ngame\t" + h.game + "\ninputs\t" + h.inputs + "\n")
                .getBytes(StandardCharsets.UTF_8);
    }

    // ---- Export ----

    /**
     * The library Play loads from a pack: this APK's version when it is there (refused when it was built from other shader tables than the profile's), else the
     * older one the host plays (ShaderLibs.playable, then legacy): its zip carries its own version, which only an app of that version (or with a stamp row for it)
     * takes. → its dmsh_vk.lib
     */
    static File chooseExport(File packDir, String titleId) throws Failure {
        // The validated b6b21fb5753a chain also contains full user exports
        // with six original shader entries REPLACED by newer translations.
        // Export its actual bytes and SHA-256; do not swap in a historical
        // pristine copy or choose an incomplete six-entry overlay.
        Profile profile = Profile.of(titleId);
        if (Prefs.OCARINA_TITLE.equals(titleId) && profile != null) {
            File baseline = ShaderLibs.trustedOcarinaBase(packDir, titleId,
                    BuildConfig.NX_DMSH_VK_ABI, profile.shaderInputs);
            if (baseline != null) return baseline;
        }
        File cur = Pack.libraryOf(packDir);
        if (cur != null && Prefs.OCARINA_TITLE.equals(titleId)) {
            ShaderLibs.Header h = ShaderLibs.header(cur);
            if (h == null || h.entries != ShaderLibs.OCARINA_BASE_ENTRIES) cur = null;
        }
        if (cur != null) {
            ShaderLibs.Header h = ShaderLibs.header(cur);
            if (h == null || !h.fits(cur.length())) throw new Failure(Why.DAMAGED, cur + " is not a whole shader library", cur.getPath());
            if (!titleId.equals(h.game)) throw new Failure(Why.OTHER_GAME, cur + " holds the shaders of " + h.game, h.game, titleId);
            if (Pack.libraryProblem(packDir, titleId) != null) {
                Profile p = Profile.of(titleId);
                String theirs = h.inputs;
                try { theirs = one(rows(stampOf(cur.getParentFile(), h)), "inputs"); } catch (IOException e) { /* the header's */ }
                throw new Failure(Why.OTHER_INPUTS, "the pack's library was built from other shader tables (" + theirs + ")", theirs, p == null ? "unknown" : p.shaderInputs);
            }
            return cur;
        }
        File old = Pack.playableLibrary(packDir, titleId);
        if (old == null) old = Pack.legacyLibrary(packDir, titleId);
        if (old != null) return old;
        throw new Failure(Why.NO_LIBRARY, packDir + " has no shader library of " + titleId + " to export", titleId);
    }

    /** What an export wrote (or found already there) */
    static final class Exported {
        File zip;
        boolean reused;   // that zip was already there with the same library
        String version;
        long shaders, size;
    }

    /**
     * Exports the library Play loads ({@link #chooseExport}) as a shaders zip into outDir (see the class comment). app: who exports it ("versionName/versionCode",
     * or "mac:&lt;commit&gt;"), xlate: the translator's source digest; both informational
     */
    static Exported export(File packDir, String titleId, File outDir, String app, String xlate, Progress p) throws IOException {
        recover(packDir);
        if (inside(outDir, packDir)) throw io("the zip cannot go inside the pack folder " + packDir, IO_INSIDE, packDir);
        File lib = chooseExport(packDir, titleId), dir = lib.getParentFile();
        String v = dir.getName().substring(2);
        ShaderLibs.Header h = ShaderLibs.header(lib);
        long size = lib.length();
        if (h == null || !h.fits(size)) throw new Failure(Why.DAMAGED, lib + " is not a whole shader library", lib.getPath());
        byte[] inputs = stampOf(dir, h);
        // the game's version and builds: pack.tsv, else the source.tsv of an imported library
        String gameVersion = "", packer = "";
        List<String> builds = new ArrayList<>();
        try {
            Pack pk = Pack.read(packDir);
            gameVersion = pk.version;
            builds = pk.builds;
            packer = pk.packer;
        } catch (IOException e) {
            File src = new File(dir, SOURCE);
            if (src.isFile() && src.length() <= MAX_SMALL) {
                Map<String, List<String>> s = rows(Files.readAllBytes(src.toPath()));
                gameVersion = one(s, "game_version");
                builds = s.getOrDefault("build", builds);
                packer = one(s, "packer");
            }
        }
        // pass 1: the library's CRC and SHA-256 (the zip's entries carry their sizes and CRCs before their data: a stored zip any reader streams)
        CRC32 crc = new CRC32();
        MessageDigest md = sha();
        byte[] buf = new byte[CHUNK];
        long done = 0;
        try (InputStream in = new FileInputStream(lib)) {
            for (int n; (n = in.read(buf)) > 0; ) {
                crc.update(buf, 0, n);
                md.update(buf, 0, n);
                done += n;
                p.at(HASH, done, size);
                if (p.cancelled()) throw new Failure(Why.CANCELLED, "cancelled");
            }
        }
        if (done != size) throw io(lib + " changed while it was read", IO_CHANGED_READ, lib);
        String libSha = hex(md.digest()), inSha = hex(sha().digest(inputs));
        Profile prof = Profile.of(titleId);
        StringBuilder m = new StringBuilder("# a game's translated shaders (android/SHADERS.md \"Shader zips\"): Import shaders… in the game's Options takes it\n");
        row(m, "format", FORMAT);
        row(m, "kind", KIND);
        row(m, "title_id", titleId);
        row(m, "name", prof != null ? prof.name : titleId);
        row(m, "game_version", gameVersion);
        for (String b : builds) row(m, "build", b);
        row(m, "library_version", v);
        row(m, "abi", h.abi);
        row(m, "chain", h.chain);
        row(m, "inputs", h.inputs);
        row(m, "shaders", String.valueOf(h.entries));
        row(m, "lib_size", String.valueOf(size));
        row(m, "lib_sha256", libSha);
        row(m, "inputs_sha256", inSha);
        row(m, "app", app);
        row(m, "packer", packer);
        row(m, "xlate_source", xlate);
        row(m, "made", java.time.Instant.now().toString());
        byte[] manifest = m.toString().getBytes(StandardCharsets.UTF_8);

        Exported out = new Exported();
        out.version = v;
        out.shaders = h.entries;
        String name = exportName(titleId, gameVersion, v);
        File same = new File(outDir, name);
        if (same.isFile() && sameLibrary(same, libSha, size)) {   // exported before: kept, no second copy of a library of a GB or more
            out.zip = same;
            out.reused = true;
            out.size = same.length();
            return out;
        }
        if (!outDir.isDirectory() && !outDir.mkdirs()) throw io("cannot create " + outDir, IO_CREATE, outDir);
        long need = size + manifest.length + inputs.length + (64L << 20);
        if (outDir.getUsableSpace() < need)
            throw new Failure(Why.NO_SPACE, "the zip needs " + SaveStore.size(need) + ", " + outDir + " has " + SaveStore.size(outDir.getUsableSpace()) + " free",
                    SaveStore.size(need), outDir.getPath(), SaveStore.size(outDir.getUsableSpace()));
        File zip = PackZip.freeFile(outDir, name), tmp = new File(zip.getPath() + PARTIAL);
        try {
            try (FileOutputStream fo = new FileOutputStream(tmp); ZipOutputStream z = new ZipOutputStream(fo)) {
                z.setMethod(ZipOutputStream.STORED);
                put(z, MANIFEST, manifest);
                put(z, INPUTS, inputs);
                ZipEntry e = stored(LIB, size, crc.getValue());
                e.setTime(lib.lastModified());
                z.putNextEntry(e);
                long n = 0;
                try (InputStream in = new FileInputStream(lib)) {
                    for (int k; (k = in.read(buf)) > 0; ) {
                        z.write(buf, 0, k);   // ZipOutputStream checks the size and the CRC at closeEntry
                        n += k;
                        p.at(WRITE, n, size);
                        if (p.cancelled()) throw new Failure(Why.CANCELLED, "cancelled");
                    }
                }
                if (n != size) throw io(lib + " changed while it was written", IO_CHANGED_WRITTEN, lib);
                z.closeEntry();
                z.finish();
                fo.getFD().sync();
            } catch (ZipException e) {
                throw io(lib + " changed while it was written (" + e.getMessage() + ")", IO_CHANGED_WRITTEN, lib);
            }
            // read back with the importer's reader: a zip that is kept is one Import shaders… takes
            Target t = new Target(packDir, titleId);
            t.verifyOnly = true;
            try (InputStream in = new FileInputStream(tmp)) {
                Staged s = read(in, tmp.getName(), t, new Progress() {
                    @Override public void at(int phase, long d, long total) { p.at(CHECK, d, total); }
                    @Override public boolean cancelled() { return p.cancelled(); }
                });
                if (!libSha.equals(s.sha256) || s.libSize != size) throw io("the zip read back does not match " + lib, IO_READ_BACK, lib);
            }
            if (!tmp.renameTo(zip)) throw io("cannot name the zip " + zip, IO_NAME_ZIP, zip);
        } finally {
            if (tmp.exists()) tmp.delete();
        }
        out.zip = zip;
        out.size = zip.length();
        return out;
    }

    private static void row(StringBuilder b, String k, String v) { b.append(k).append('\t').append(tsvValue(v)).append('\n'); }

    private static ZipEntry stored(String name, long size, long crc) {
        ZipEntry e = new ZipEntry(name);
        e.setMethod(ZipEntry.STORED);
        e.setSize(size);
        e.setCompressedSize(size);
        e.setCrc(crc);
        return e;
    }

    private static void put(ZipOutputStream z, String name, byte[] data) throws IOException {
        CRC32 c = new CRC32();
        c.update(data);
        z.putNextEntry(stored(name, data.length, c.getValue()));
        z.write(data);
        z.closeEntry();
    }

    /** Whether a zip already there is a shaders zip of this library (its manifest's size and SHA-256) */
    private static boolean sameLibrary(File zip, String sha, long size) {
        try (ZipFile zf = new ZipFile(zip)) {
            String prefix = "";
            ZipEntry e = zf.getEntry(MANIFEST);
            if (e == null) for (Enumeration<? extends ZipEntry> en = zf.entries(); en.hasMoreElements(); ) {
                String n = en.nextElement().getName();
                if (n.endsWith("/" + MANIFEST) && n.indexOf('/') == n.length() - MANIFEST.length() - 1) { e = zf.getEntry(n); prefix = n.substring(0, n.indexOf('/') + 1); break; }
            }
            ZipEntry l = zf.getEntry(prefix + LIB);
            if (e == null || l == null || e.getSize() > MAX_SMALL || l.getSize() != size) return false;
            Map<String, List<String>> m;
            try (InputStream in = zf.getInputStream(e)) { m = rows(in.readAllBytes()); }
            return KIND.equals(one(m, "kind")) && sha.equals(one(m, "lib_sha256")) && String.valueOf(size).equals(one(m, "lib_size"));
        } catch (IOException e) {
            return false;
        }
    }

    // ---- Import ----

    /** Where an import goes and what it must agree with: the pack folder, this APK's library version and ABI, the profile's inputs digest and stamp rows */
    static final class Target {
        final File pack;
        final String titleId;
        String current = BuildConfig.NX_DMSH_VK_CHAIN, abi = BuildConfig.NX_DMSH_VK_ABI, inputs, stamps, name;
        /** The export's read-back: every check of the zip itself, none against this app (its version, the profile's inputs, the free space), nothing written */
        boolean verifyOnly;
        Space space = ShaderZip::freeSpace;

        Target(File pack, String titleId) {
            this.pack = pack;
            this.titleId = titleId;
            Profile p = Profile.of(titleId);
            inputs = p == null ? "unknown" : p.shaderInputs;
            stamps = p == null ? "" : p.stamp;
            name = p == null ? titleId : p.name;
        }
    }

    /** The usable space of the volume a folder is on (the nearest folder that is there) */
    static long freeSpace(File dir) {
        File d = dir.getAbsoluteFile();
        while (d != null && !d.exists()) d = d.getParentFile();
        return d == null ? 0 : d.getUsableSpace();
    }

    /** A checked library staged in &lt;pack&gt;/shaders/.import-&lt;V&gt;/ (null dir for a verifyOnly read), ready for {@link #install} */
    static final class Staged {
        Target target;
        File dir;
        boolean locked;   // holds its pack against recover until install or unstage
        String version, sha256, abi, inputs;
        long shaders, libSize;
        Map<String, List<String>> manifest;
    }

    /** What an import put in place */
    static final class Result {
        String version;   // the library's version in the pack now (this APK's, also after a restamp)
        String from;      // the zip's version
        long shaders, libSize;
        File packDir;
        boolean hadPack;  // the folder has a pack.tsv of this game (Play uses it now); else Prepare only rewrites the code
    }

    /** One zip entry as a reader gives it */
    private interface Opener { InputStream open() throws IOException; }

    /** The checks and the copy, the same for a stream and a ZipFile; entries come in the zip's order (a stream) or as manifest, inputs, library (a ZipFile) */
    private static final class Reader {
        final Target t;
        final String zipName;
        final Progress p;
        String prefix;   // null until the first entry decides it
        final Set<String> seen = new HashSet<>();
        Map<String, List<String>> m;
        byte[] inputs;
        Staged s = new Staged();
        boolean libDone;

        Reader(Target t, String zipName, Progress p) {
            this.t = t;
            this.zipName = zipName;
            this.p = p;
            s.target = t;
        }

        /** The entry's name in the zip's layout (manifest.tsv, inputs.tsv, dmsh_vk.lib), null for the top folder; Failure for anything else */
        String name(String n, boolean directory) throws Failure {
            Failure bad = new Failure(Why.UNSAFE_NAME, "the zip has an entry that is not a shaders file (" + n + ")", n);
            if (n.isEmpty() || n.indexOf('\\') >= 0 || n.startsWith("/") || n.indexOf('\0') >= 0 || n.matches("^[A-Za-z]:.*")) throw bad;
            String body = directory && n.endsWith("/") ? n.substring(0, n.length() - 1) : n;
            String[] seg = body.split("/", -1);
            for (String x : seg) if (x.isEmpty() || x.equals(".") || x.equals("..")) throw bad;
            if (directory) {
                if (seg.length != 1) throw bad;
                String top = seg[0] + "/";
                if (prefix == null) prefix = top;
                else if (!prefix.equals(top)) throw bad;
                return null;
            }
            if (seg.length > 2) throw bad;
            String top = seg.length == 2 ? seg[0] + "/" : "";
            if (prefix == null) prefix = top;
            else if (!prefix.equals(top)) throw bad;
            String rel = seg[seg.length - 1];
            if (!rel.equals(MANIFEST) && !rel.equals(INPUTS) && !rel.equals(LIB)) throw bad;
            if (!seen.add(rel)) throw new Failure(Why.UNSAFE_NAME, "the zip has " + rel + " twice", n);
            return rel;
        }

        void entry(String rel, long crcWant, Opener o) throws IOException {
            if (rel.equals(MANIFEST)) {
                m = rows(small(o.open(), MANIFEST, crcWant));
                manifest();
            } else if (rel.equals(INPUTS)) {
                inputs = small(o.open(), INPUTS, crcWant);
                if (m != null) inputsCheck();
            } else {
                if (m == null) throw new Failure(Why.ORDER, "the zip's " + MANIFEST + " comes after its library", zipName);
                library(o.open(), crcWant);
            }
        }

        byte[] small(InputStream in, String what, long crcWant) throws IOException {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            for (int n; (n = in.read(buf)) > 0; ) {
                b.write(buf, 0, n);
                if (b.size() > MAX_SMALL) throw new Failure(Why.NOT_SHADER_ZIP, what + " is larger than 64 KiB", zipName, what + " is larger than 64 KiB");
            }
            byte[] d = b.toByteArray();
            CRC32 c = new CRC32();
            c.update(d);
            if (crcWant != -1 && c.getValue() != crcWant) throw new Failure(Why.DAMAGED, what + "'s CRC does not match", what + " CRC");
            return d;
        }

        void manifest() throws Failure {
            String kind = one(m, "kind"), format = one(m, "format");
            if (!KIND.equals(kind) || !FORMAT.equals(format))
                throw new Failure(Why.NOT_SHADER_ZIP, zipName + " is not a shaders zip (kind " + kind + ", format " + format + ")", zipName, "kind " + kind + ", format " + format);
            String id = one(m, "title_id").toUpperCase(Locale.ROOT);
            if (!id.equals(t.titleId)) {
                String nm = one(m, "name");
                throw new Failure(Why.OTHER_GAME, "the zip has the shaders of " + id + ", not " + t.titleId, (nm.isEmpty() ? id : nm + " (" + id + ")"), t.name + " (" + t.titleId + ")");
            }
            String v = one(m, "library_version");
            if (!v.matches("[0-9a-f]{6,16}")) throw new Failure(Why.NOT_SHADER_ZIP, "library_version " + v + " is not a version", zipName, "library_version " + v);
            s.version = v;
            s.abi = one(m, "abi");
            s.inputs = one(m, "inputs");
            s.sha256 = one(m, "lib_sha256");
            if (!s.sha256.matches("[0-9a-f]{64}") || !one(m, "inputs_sha256").matches("[0-9a-f]{64}"))
                throw new Failure(Why.NOT_SHADER_ZIP, "the manifest has no SHA-256 of its files", zipName, "no lib_sha256");
            try {
                s.libSize = Long.parseLong(one(m, "lib_size"));
                s.shaders = Long.parseLong(one(m, "shaders"));
            } catch (NumberFormatException e) {
                throw new Failure(Why.NOT_SHADER_ZIP, "the manifest has no lib_size or shaders", zipName, "no lib_size");
            }
            if (s.libSize > MAX_LIB) throw new Failure(Why.TOO_BIG, "the library is " + s.libSize + " bytes", SaveStore.size(s.libSize));
            if (s.libSize < ShaderLibs.HEADER_SIZE) throw new Failure(Why.DAMAGED, "the library is " + s.libSize + " bytes", "lib_size " + s.libSize);
            s.manifest = m;
            if (t.verifyOnly) return;
            if (!v.equals(t.current) && !restampable(v) && !compatibleOcarinaBase())
                throw new Failure(Why.OTHER_VERSION, "the shaders are of version " + v + ", this app needs " + t.current, v, t.current);
            if (!"unknown".equals(t.inputs) && !t.inputs.equals(s.inputs))
                throw new Failure(Why.OTHER_INPUTS, "the shaders were built from other shader tables (" + s.inputs + ") than the profile's (" + t.inputs + ")", s.inputs, t.inputs);
            long need = (v.equals(t.current) || compatibleOcarinaBase() ? s.libSize : 2 * s.libSize) + SPARE;   // a trusted original keeps its version, no restamp copy
            long free = t.space.free(new File(t.pack, "shaders"));
            if (free < need) throw new Failure(Why.NO_SPACE, "the shaders need " + need + " bytes, " + free + " free", SaveStore.size(need), t.pack.getPath(), SaveStore.size(free));
        }

        /** Complete Ocarina 42,339-shader library: includes the original
         * b6b21fb5753a version and the user's same-chain full export with
         * six replaced entries. Neither is a partial overlay; preserve all
         * imported bytes and version. Verify game, inputs, ABI, count, SHA,
         * CRC and size before changing installed libraries. */
        boolean compatibleOcarinaBase() {
            return ShaderLibs.trustedOcarinaBase(t.titleId, s.version,
                    s.abi, s.inputs, s.shaders, t.abi, t.inputs);
        }

        /** An older version is taken only when a "stamp" row names its exact bytes (its manifest's SHA-256) and the pack has no library of this version yet */
        boolean restampable(String v) {
            if (new File(t.pack, "shaders/v-" + t.current + "/" + LIB).isFile()) return false;
            if (t.stamps == null) return false;
            for (String row : t.stamps.split(";")) {
                String[] c = row.trim().split(":");
                if (c.length == 3 && c[0].equals(v) && c[1].equals(s.sha256)) return true;
            }
            return false;
        }

        void inputsCheck() throws IOException {
            Map<String, List<String>> st = rows(inputs);
            if (!hex(sha().digest(inputs)).equals(one(m, "inputs_sha256"))) throw new Failure(Why.DAMAGED, INPUTS + "'s SHA-256 is not the manifest's", INPUTS);
            if (!t.titleId.equals(one(st, "game").toUpperCase(Locale.ROOT)) || !s.inputs.equals(one(st, "inputs")))
                throw new Failure(Why.DAMAGED, INPUTS + " names " + one(st, "game") + " " + one(st, "inputs") + ", the manifest " + t.titleId + " " + s.inputs, INPUTS);
        }

        void header(byte[] hb) throws Failure {
            ShaderLibs.Header h = ShaderLibs.header(hb);
            if (h == null) throw new Failure(Why.DAMAGED, "the library has no shader library header", "header");
            String bad = !t.titleId.equals(h.game) ? "game " + h.game : !s.version.equals(h.vkChain) ? "version " + h.vkChain : !s.inputs.equals(h.inputs) ? "inputs " + h.inputs
                    : !s.abi.equals(h.abi) ? "abi " + h.abi : h.entries != s.shaders ? h.entries + " shaders" : !h.fits(s.libSize) ? "tables outside the file" : null;
            if (bad == null && !t.verifyOnly && s.version.equals(t.current) && !t.abi.equals(h.abi)) bad = "abi " + h.abi + ", this app's " + t.abi;
            if (bad != null) throw new Failure(Why.DAMAGED, "the library's header does not match its manifest: " + bad, bad);
        }

        void library(InputStream in, long crcWant) throws IOException {
            byte[] hb = new byte[ShaderLibs.HEADER_SIZE];
            for (int got = 0, n; got < hb.length; got += n) if ((n = in.read(hb, got, hb.length - got)) < 0) throw new Failure(Why.DAMAGED, "the library is cut short", "cut short");
            header(hb);
            MessageDigest md = sha();
            CRC32 crc = new CRC32();
            md.update(hb);
            crc.update(hb);
            long done = hb.length;
            int phase = t.verifyOnly ? CHECK : COPY;
            FileOutputStream out = null;
            if (!t.verifyOnly) {
                File sh = new File(t.pack, "shaders");
                s.dir = new File(sh, IMPORT + s.version);
                if (s.dir.exists()) deleteTree(s.dir);
                if (!s.dir.mkdirs()) throw io("cannot create " + s.dir, IO_CREATE, s.dir);
                out = new FileOutputStream(new File(s.dir, LIB));
            }
            try {
                if (out != null) out.write(hb);
                byte[] buf = new byte[CHUNK];
                for (int n; (n = in.read(buf)) > 0; ) {
                    done += n;
                    if (done > s.libSize) throw new Failure(Why.DAMAGED, "the library is longer than the manifest says", "longer than " + s.libSize);
                    md.update(buf, 0, n);
                    crc.update(buf, 0, n);
                    if (out != null) out.write(buf, 0, n);
                    p.at(phase, done, s.libSize);
                    if (p.cancelled()) throw new Failure(Why.CANCELLED, "cancelled");
                }
                if (out != null) out.getFD().sync();
            } finally {
                if (out != null) out.close();
            }
            if (done != s.libSize) throw new Failure(Why.DAMAGED, "the library has " + done + " bytes, the manifest " + s.libSize, done + " of " + s.libSize + " bytes");
            if (crcWant != -1 && crc.getValue() != crcWant) throw new Failure(Why.DAMAGED, "the library's CRC does not match", "CRC");
            if (!hex(md.digest()).equals(s.sha256)) throw new Failure(Why.DAMAGED, "the library's SHA-256 is not the manifest's", "SHA-256");
            libDone = true;
        }

        Staged finish() throws IOException {
            for (String n : new String[] {MANIFEST, INPUTS, LIB})
                if (!seen.contains(n)) throw new Failure(Why.NOT_SHADER_ZIP, zipName + " has no " + n, zipName, "no " + n);
            if (!libDone) throw new Failure(Why.DAMAGED, "the library was not read", "library");
            inputsCheck();
            if (!t.verifyOnly) {
                write(new File(s.dir, INPUTS), inputs);
                StringBuilder b = new StringBuilder("# where this library came from (Import shaders…: the zip's manifest)\n");
                for (Map.Entry<String, List<String>> e : m.entrySet()) for (String v : e.getValue()) row(b, e.getKey(), v);
                row(b, "imported_from", zipName);
                row(b, "imported", java.time.Instant.now().toString());
                write(new File(s.dir, SOURCE), b.toString().getBytes(StandardCharsets.UTF_8));
            }
            return s;
        }
    }

    private static void write(File f, byte[] d) throws IOException {
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write(d);
            out.getFD().sync();
        }
    }

    /**
     * Reads and checks a shaders zip from a stream (a picked document's), staging its library into the target's pack (see the class comment); nothing is left
     * behind when it throws. A zip whose library comes before its manifest is refused with ORDER: a caller with the file reads it with {@link #read(File, Target, Progress)}
     */
    static Staged read(InputStream in, String zipName, Target t, Progress p) throws IOException {
        Reader r = new Reader(t, zipName, p);
        lock(t);
        try {
            try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(in, 1 << 16))) {
                int files = 0;
                for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                    String rel = r.name(e.getName(), e.isDirectory());
                    if (rel == null) continue;
                    if (++files > 3) throw new Failure(Why.UNSAFE_NAME, "the zip has more than 3 files", e.getName());
                    r.entry(rel, -1, () -> z);   // ZipInputStream checks the entry's CRC at its end itself (a ZipException)
                }
            }
            return held(r.finish());
        } catch (ZipException | EOFException e) {
            unstage(r.s);
            throw new Failure(Why.DAMAGED, zipName + " is not a whole zip file (" + e.getMessage() + ")", String.valueOf(e.getMessage()));
        } catch (IOException | RuntimeException e) {
            unstage(r.s);
            throw io(e);
        } finally {
            unlock(t);
        }
    }

    /** The same from a file: the whole name list first (the central directory), then manifest, inputs and library by name, so the entries' order does not matter */
    static Staged read(File zip, Target t, Progress p) throws IOException {
        Reader r = new Reader(t, zip.getName(), p);
        lock(t);
        try (ZipFile zf = new ZipFile(zip)) {
            Map<String, ZipEntry> by = new LinkedHashMap<>();
            int files = 0;
            for (Enumeration<? extends ZipEntry> en = zf.entries(); en.hasMoreElements(); ) {
                ZipEntry e = en.nextElement();
                String rel = r.name(e.getName(), e.isDirectory());
                if (rel == null) continue;
                if (++files > 3) throw new Failure(Why.UNSAFE_NAME, "the zip has more than 3 files", e.getName());
                by.put(rel, e);
            }
            for (String n : new String[] {MANIFEST, INPUTS, LIB}) {
                ZipEntry e = by.get(n);
                if (e == null) throw new Failure(Why.NOT_SHADER_ZIP, zip.getName() + " has no " + n, zip.getName(), "no " + n);
                try (InputStream in = zf.getInputStream(e)) {
                    r.entry(n, e.getCrc(), () -> in);   // ZipFile does not check a stored entry's CRC: the reader does
                }
            }
            return held(r.finish());
        } catch (ZipException | EOFException e) {
            unstage(r.s);
            throw new Failure(Why.DAMAGED, zip.getName() + " is not a whole zip file (" + e.getMessage() + ")", String.valueOf(e.getMessage()));
        } catch (IOException | RuntimeException e) {
            unstage(r.s);
            throw io(e);
        } finally {
            unlock(t);
        }
    }

    private static Failure io(Exception e) {
        if (e instanceof Failure) return (Failure) e;
        return new Failure(Why.IO, String.valueOf(e.getMessage()), String.valueOf(e.getMessage()));
    }

    // An import holds its pack from read() until install() or unstage(): recover (AppStorage.pack, from any thread) must not take its staged folder meanwhile
    private static void lock(Target t) { if (!t.verifyOnly) synchronized (ACTIVE) { ACTIVE.merge(key(t.pack), 1, Integer::sum); } }

    private static void unlock(Target t) {
        if (t.verifyOnly) return;
        synchronized (ACTIVE) { ACTIVE.computeIfPresent(key(t.pack), (k, n) -> n > 1 ? n - 1 : null); }
    }

    /** A successful read keeps its lock for its Staged; install and unstage give it back */
    private static Staged held(Staged s) {
        if (!s.target.verifyOnly) {
            lock(s.target);
            s.locked = true;
        }
        return s;
    }

    private static void release(Staged s) {
        if (s != null && s.locked) {
            s.locked = false;
            unlock(s.target);
        }
    }

    /** Removes a staged library (an import that stopped, was cancelled or is not installed after all) */
    static void unstage(Staged s) {
        if (s != null && s.dir != null && s.dir.getName().startsWith(IMPORT)) deleteTree(s.dir);
        release(s);
    }

    /**
     * Puts a staged library in place: v-&lt;V&gt; that was there goes aside as .replaced-&lt;V&gt;, the staged folder takes its name, then the old one goes (a failed
     * rename puts it back). A library of an older version then becomes this version's by its stamp row (ShaderLibs.restamp), or the import is undone
     */
    static Result install(Staged s, Target t) throws IOException {
        if (s.dir == null || !s.dir.isDirectory()) { release(s); throw io("nothing staged", IO_NOTHING_STAGED, null); }
        File sh = new File(t.pack, "shaders"), dst = new File(sh, "v-" + s.version), old = new File(sh, REPLACED + s.version);
        lock(t);
        try {
            synchronized (ACTIVE) {   // recover's own steps, with this import's staged folder kept
                if (old.exists()) {
                    if (!dst.exists()) old.renameTo(dst);
                    else deleteTree(old);
                }
            }
            if (dst.exists() && !dst.renameTo(old)) throw io("cannot move " + dst + " aside", IO_MOVE_ASIDE, dst);
            if (!s.dir.renameTo(dst)) {
                if (old.exists() && !dst.exists()) old.renameTo(dst);
                throw io("cannot name the imported library " + dst, IO_NAME_LIB, dst);
            }
            Result r = new Result();
            r.from = s.version;
            r.version = s.version;
            // Keep the complete original OR its fully merged six-replacement
            // export under their actual b6b21fb5753a chain. The Vulkan
            // loader accepts the same-ABI library with no header spoof.
            boolean keepBaseline = ShaderLibs.trustedOcarinaBase(t.titleId,
                    s.version, s.abi, s.inputs, s.shaders, t.abi, t.inputs);
            if (!s.version.equals(t.current) && !keepBaseline) {
                String took = ShaderLibs.restamp(t.pack, t.titleId, t.current, t.abi, t.stamps);
                if (!s.version.equals(took) || !new File(sh, "v-" + t.current + "/" + LIB).isFile()) {
                    deleteTree(dst);
                    if (old.exists()) old.renameTo(dst);
                    throw new Failure(Why.OTHER_VERSION, "the shaders of version " + s.version + " could not be made version " + t.current, s.version, t.current);
                }
                File src = new File(dst, SOURCE), to = new File(sh, "v-" + t.current + "/" + SOURCE);
                if (src.isFile() && !to.exists()) Files.copy(src.toPath(), to.toPath());
                r.version = t.current;
            }
            deleteTree(old);
            r.shaders = s.shaders;
            r.libSize = s.libSize;
            r.packDir = t.pack;
            try { r.hadPack = Pack.read(t.pack).titleId.equals(t.titleId); } catch (IOException e) { r.hadPack = false; }
            return r;
        } catch (IOException | RuntimeException e) {
            unstage(s);
            throw io(e);
        } finally {
            unlock(t);
            release(s);
        }
    }

    // ---- Helpers ----

    private static MessageDigest sha() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    static String hex(byte[] d) {
        StringBuilder b = new StringBuilder();
        for (byte x : d) b.append(String.format(Locale.ROOT, "%02x", x & 0xff));
        return b.toString();
    }

    /** Whether f is dir or inside it, by canonical paths (as SaveStore.inside, by path components) */
    static boolean inside(File f, File dir) {
        return new File(SaveStore.canon(f)).toPath().startsWith(new File(SaveStore.canon(dir)).toPath());
    }

    private static void deleteTree(File f) {
        File[] l = Files.isSymbolicLink(f.toPath()) ? null : f.listFiles();
        if (l != null) for (File x : l) deleteTree(x);
        f.delete();
    }

    /** The names ShaderUi's import list shows: the zips in these folders as "name (size)" */
    static List<String> labels(List<File> zips) {
        List<String> out = new ArrayList<>();
        for (File f : zips) out.add(f.getName() + " (" + SaveStore.size(f.length()) + ")");
        return Collections.unmodifiableList(out);
    }
}
