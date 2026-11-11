package dev.nxnative.android;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.List;
import java.util.Random;
import java.util.TreeMap;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * ShaderZip (Export shaders… / Import shaders…) on the JVM: run by dm/tools/tests/test_android_shaderzip.py, which compiles this with ShaderZip, PackZip, Pack,
 * Nup, Zstd, Profile, ShaderLibs, SaveStore and a stub BuildConfig (library version CUR, ABI, profile 040074A01BF12000 with inputs INPUTS).
 * {@code <scratch folder>}: every case; prints "ok <n>" and exits 0, or the first failure and exits 1.
 * {@code import <zip> <scratch folder>}: imports a zip made by scripts/shaders_zip.py into an empty folder and prints "imported <version> <shaders>".
 */
public final class ShaderZipJvmTest {
    private static int n;
    static final String ID = "040074A01BF12000", MKW = "0400C3F00006E000", CUR = BuildConfig.NX_DMSH_VK_CHAIN, ABI = BuildConfig.NX_DMSH_VK_ABI, INPUTS = "abcdef012345";
    static final String OLD = "0123456789ab";

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        n++;
    }

    static void write(File f, byte[] b) throws IOException {
        f.getParentFile().mkdirs();
        Files.write(f.toPath(), b);
    }

    static void write(File f, String s) throws IOException { write(f, s.getBytes(StandardCharsets.UTF_8)); }

    static byte[] bytes(File f) throws IOException { return Files.readAllBytes(f.toPath()); }

    static String sha(byte[] b) throws Exception { return ShaderZip.hex(MessageDigest.getInstance("SHA-256").digest(b)); }

    static void put(byte[] h, int off, String s) { byte[] b = s.getBytes(StandardCharsets.US_ASCII); System.arraycopy(b, 0, h, off, Math.min(b.length, 16)); }

    static void u32(byte[] h, int off, long v) { for (int i = 0; i < 4; i++) h[off + i] = (byte) (v >>> (8 * i)); }

    static void u64(byte[] h, int off, long v) { for (int i = 0; i < 8; i++) h[off + i] = (byte) (v >>> (8 * i)); }

    /** A library as vk_android_build.py writes one: the 128-byte header, entries entries of 64 bytes, a blob of blob bytes (random from seed) */
    static byte[] lib(String game, String version, String inputs, String abi, int entries, int blob, long seed) {
        byte[] b = new byte[128 + entries * 64 + blob];
        u32(b, 0, ShaderLibs.MAGIC);
        u32(b, 4, ShaderLibs.VERSION);
        put(b, 8, "chain0000000");
        put(b, 24, version);
        put(b, 40, game);
        put(b, 56, inputs);
        u32(b, 72, entries);
        u32(b, 76, 128);
        u64(b, 96, 128 + entries * 64L);
        u64(b, 104, blob);
        byte[] a = abi.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(a, 0, b, 116, Math.min(a.length, 12));
        byte[] r = new byte[blob];
        new Random(seed).nextBytes(r);
        System.arraycopy(r, 0, b, 128 + entries * 64, blob);
        return b;
    }

    static String stamp(String game, String inputs) { return "# stamp\ngame\t" + game + "\ninputs\t" + inputs + "\n"; }

    /** A pack folder: pack.tsv (format 2) and a finished module, no library */
    static File pack(File dir) throws IOException {
        write(new File(dir, "pack.tsv"), "format\t2\ntarget\tandroid\ntitle_id\t" + ID + "\nname\tDonkey Kong Bananza\nversion\t458752\nromfs\tupdates/458752/romfs\n"
                + "modules\tmain\nshaders\tshaders\nbuild\tmain=aa\npacker\tabc123\n");
        write(new File(dir, "main.patched.bin"), "code");
        write(new File(dir, "main.android.key"), "key");
        return dir;
    }

    static File addLib(File pack, String version, byte[] lib, String inputs) throws IOException {
        File d = new File(pack, "shaders/v-" + version);
        write(new File(d, "dmsh_vk.lib"), lib);
        if (inputs != null) write(new File(d, "inputs.tsv"), inputs);
        return new File(d, "dmsh_vk.lib");
    }

    interface Io { void run() throws Exception; }

    static ShaderZip.Failure failure(Io r) throws Exception {
        try { r.run(); return null; } catch (ShaderZip.Failure e) { return e; }
    }

    /** The files under a folder with their sizes and SHA-256 (what "nothing changed" compares) */
    static TreeMap<String, String> tree(File dir) throws Exception {
        TreeMap<String, String> out = new TreeMap<>();
        if (dir.isDirectory()) for (java.util.Map.Entry<String, File> e : PackZip.files(dir).entrySet()) out.put(e.getKey(), sha(bytes(e.getValue())));
        return out;
    }

    static ShaderZip.Result importFile(File zip, ShaderZip.Target t) throws IOException { return ShaderZip.install(ShaderZip.read(zip, t, ShaderZip.QUIET), t); }

    static ShaderZip.Result importStream(File zip, ShaderZip.Target t) throws IOException {
        try (InputStream in = new FileInputStream(zip)) { return ShaderZip.install(ShaderZip.read(in, zip.getName(), t, ShaderZip.QUIET), t); }
    }

    /** A zip of these entries (name, bytes), stored, in this order */
    static void zip(File f, List<Object[]> entries) throws IOException {
        f.getParentFile().mkdirs();
        try (ZipOutputStream z = new ZipOutputStream(new FileOutputStream(f))) {
            z.setMethod(ZipOutputStream.STORED);
            for (Object[] e : entries) {
                byte[] d = (byte[]) e[1];
                CRC32 c = new CRC32();
                c.update(d);
                ZipEntry ze = new ZipEntry((String) e[0]);
                ze.setMethod(ZipEntry.STORED);
                ze.setSize(d.length);
                ze.setCompressedSize(d.length);
                ze.setCrc(c.getValue());
                z.putNextEntry(ze);
                z.write(d);
                z.closeEntry();
            }
        }
    }

    /** A manifest for this library and stamp, with rows replaced or added (key, value) */
    static byte[] manifest(byte[] lib, byte[] inputs, String... over) throws Exception {
        ShaderLibs.Header h = ShaderLibs.header(lib);
        TreeMap<String, String> m = new TreeMap<>();
        m.put("format", "1");
        m.put("kind", "swap2-shaders");
        m.put("title_id", h.game);
        m.put("name", "Donkey Kong Bananza");
        m.put("game_version", "458752");
        m.put("library_version", h.vkChain);
        m.put("abi", h.abi);
        m.put("chain", h.chain);
        m.put("inputs", h.inputs);
        m.put("shaders", String.valueOf(h.entries));
        m.put("lib_size", String.valueOf(lib.length));
        m.put("lib_sha256", sha(lib));
        m.put("inputs_sha256", sha(inputs));
        for (int i = 0; i + 1 < over.length; i += 2) m.put(over[i], over[i + 1]);
        StringBuilder b = new StringBuilder();
        for (java.util.Map.Entry<String, String> e : m.entrySet()) b.append(e.getKey()).append('\t').append(e.getValue()).append('\n');
        return b.toString().getBytes(StandardCharsets.UTF_8);
    }

    static File craft(File f, byte[] lib, byte[] inputs, String... over) throws Exception {
        zip(f, Arrays.asList(new Object[] {"manifest.tsv", manifest(lib, inputs, over)}, new Object[] {"inputs.tsv", inputs}, new Object[] {"dmsh_vk.lib", lib}));
        return f;
    }

    static List<String> names(File zip) throws IOException {
        List<String> out = new ArrayList<>();
        try (ZipFile zf = new ZipFile(zip)) {
            for (Enumeration<? extends ZipEntry> en = zf.entries(); en.hasMoreElements(); ) {
                ZipEntry e = en.nextElement();
                out.add(e.getName() + (e.getMethod() == ZipEntry.STORED ? "" : "*"));
            }
        }
        return out;
    }

    static boolean noStaging(File pack) {
        String[] l = new File(pack, "shaders").list();
        if (l != null) for (String x : l) if (x.startsWith(".")) return false;
        return true;
    }

    /** A refusal: the Why, and the target pack exactly as it was (no v-<V> change, no .import-*) */
    static ShaderZip.Failure refused(String what, ShaderZip.Why why, File zip, ShaderZip.Target t, boolean stream) throws Exception {
        TreeMap<String, String> before = tree(t.pack);
        ShaderZip.Failure f = failure(() -> { if (stream) importStream(zip, t); else importFile(zip, t); });
        check(f != null && f.why == why, what + ": " + (f == null ? "accepted" : f.why + " " + f.getMessage()));
        check(tree(t.pack).equals(before) && noStaging(t.pack), what + ": the pack changed");
        return f;
    }

    public static void main(String[] a) throws Exception {
        if (a.length == 3 && a[0].equals("import")) {
            File to = new File(a[2]);
            ShaderZip.Target t = new ShaderZip.Target(to, ID);
            ShaderZip.Result r = importFile(new File(a[1]), t);
            ShaderZip.Result r2 = importStream(new File(a[1]), new ShaderZip.Target(new File(a[2] + "-stream"), ID));
            check(r2.shaders == r.shaders, "stream import");
            System.out.println("imported " + r.version + " " + r.shaders + " " + ShaderZip.ready(to, ID));
            return;
        }
        File t = new File(a[0]);
        roundTrip(new File(t, "rt"));
        ocarinaBaseline(new File(t, "oot"));
        choice(new File(t, "choice"));
        refusals(new File(t, "ref"));
        cancel(new File(t, "cancel"));
        replace(new File(t, "replace"));
        restamp(new File(t, "restamp"));
        lists(new File(t, "lists"));
        System.out.println("ok " + n);
    }

    static void roundTrip(File t) throws Exception {
        byte[] lib = lib(ID, CUR, INPUTS, ABI, 5, 3 << 20, 1);
        File a = pack(new File(t, "a")), out = new File(t, "out");
        addLib(a, CUR, lib, stamp(ID, INPUTS));
        ShaderZip.Exported e = ShaderZip.export(a, ID, out, "test/1", "x", ShaderZip.QUIET);
        check(e.zip.getName().equals("swap2-shaders-" + ID + "-458752-v-" + CUR + ".zip") && !e.reused && e.shaders == 5 && e.version.equals(CUR), "export: " + e.zip);
        check(names(e.zip).equals(Arrays.asList("manifest.tsv", "inputs.tsv", "dmsh_vk.lib")), "entries in order, stored: " + names(e.zip));
        List<String> streamed = new ArrayList<>();
        try (ZipInputStream z = new ZipInputStream(new FileInputStream(e.zip))) { for (ZipEntry ze; (ze = z.getNextEntry()) != null; ) streamed.add(ze.getName()); }
        check(streamed.equals(Arrays.asList("manifest.tsv", "inputs.tsv", "dmsh_vk.lib")), "the stream's order");
        String[] left = out.list();
        check(left != null && left.length == 1, "no .partial left: " + Arrays.toString(left));
        String man;
        try (ZipFile zf = new ZipFile(e.zip)) { man = new String(zf.getInputStream(zf.getEntry("manifest.tsv")).readAllBytes(), StandardCharsets.UTF_8); }
        check(man.contains("library_version\t" + CUR + "\n") && man.contains("lib_sha256\t" + sha(lib) + "\n") && man.contains("build\tmain=aa\n") && man.contains("packer\tabc123\n")
                && man.contains("app\ttest/1\n"), "manifest: " + man);
        check(bytes(new File(a, "shaders/v-" + CUR + "/dmsh_vk.lib")).length == lib.length && noStaging(a), "the pack only read");
        long mtime = e.zip.lastModified();
        ShaderZip.Exported again = ShaderZip.export(a, ID, out, "test/1", "x", ShaderZip.QUIET);
        check(again.reused && again.zip.equals(e.zip) && e.zip.lastModified() == mtime && out.list().length == 1, "the same library: the zip there is kept");

        // into a pack (Play uses it now)
        File b = pack(new File(t, "b"));
        ShaderZip.Result r = importFile(e.zip, new ShaderZip.Target(b, ID));
        check(Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), lib) && Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/inputs.tsv")),
                stamp(ID, INPUTS).getBytes(StandardCharsets.UTF_8)), "imported byte for byte");
        String src = new String(bytes(new File(b, "shaders/v-" + CUR + "/source.tsv")), StandardCharsets.UTF_8);
        check(src.contains("imported_from\t" + e.zip.getName()) && src.contains("lib_sha256\t" + sha(lib)), "source.tsv: " + src);
        check(r.hadPack && r.version.equals(CUR) && r.shaders == 5 && r.libSize == lib.length, "result");
        check(Pack.libraryProblem(b, ID) == null && ShaderZip.ready(b, ID) && ShaderZip.imported(b) && noStaging(b), "the pack has the library");

        // into a folder with no pack yet, from a stream (a content URI)
        File c = new File(t, "c");
        ShaderZip.Result rc = importStream(e.zip, new ShaderZip.Target(c, ID));
        check(!rc.hadPack && ShaderZip.ready(c, ID) && ShaderZip.onlyShaders(c) && Arrays.equals(bytes(new File(c, "shaders/v-" + CUR + "/dmsh_vk.lib")), lib), "no pack: shaders/ only");
        check(!ShaderZip.ready(c, MKW), "ready names the game");

        // a changed library: a new name beside the old zip (PackZip.freeFile)
        addLib(a, CUR, lib(ID, CUR, INPUTS, ABI, 5, 3 << 20, 2), stamp(ID, INPUTS));
        ShaderZip.Exported e2 = ShaderZip.export(a, ID, out, "test/1", "x", ShaderZip.QUIET);
        check(!e2.reused && e2.zip.getName().equals("swap2-shaders-" + ID + "-458752-v-" + CUR + "-2.zip"), "another library: " + e2.zip.getName());

        // a library with no inputs.tsv: the stamp comes from its header; an export into the pack is refused
        File d = pack(new File(t, "d"));
        addLib(d, CUR, lib, null);
        ShaderZip.Exported e3 = ShaderZip.export(d, ID, new File(t, "out3"), "test/1", "x", ShaderZip.QUIET);
        File d2 = new File(t, "d2");
        importFile(e3.zip, new ShaderZip.Target(d2, ID));
        check(new String(bytes(new File(d2, "shaders/v-" + CUR + "/inputs.tsv")), StandardCharsets.UTF_8).contains("inputs\t" + INPUTS), "inputs.tsv from the header");
        check(failure(() -> ShaderZip.export(d, ID, new File(d, "x"), "t", "x", ShaderZip.QUIET)) != null, "not into the pack");
        // an imported library (no pack.tsv) exports with the game version of its source.tsv
        ShaderZip.Exported e4 = ShaderZip.export(c, ID, new File(t, "out4"), "test/1", "x", ShaderZip.QUIET);
        check(e4.zip.getName().equals("swap2-shaders-" + ID + "-458752-v-" + CUR + ".zip"), "re-export of an import: " + e4.zip.getName());
        check(ShaderZip.exportName(ID, "", "v1").equals("swap2-shaders-" + ID + "-any-v-v1.zip") && ShaderZip.exportName(ID, "1/2", "v").contains("-1_2-"), "names");
    }

    /** The exact fully compiled 0.1.2 Ocarina shaders stay importable
     * by 0.1.6. Other versions/ABIs and incomplete hot zips stay rejected.
     * This also guards against accidentally exporting an 6-shader overlay. */
    static void ocarinaBaseline(File t) throws Exception {
        final String oot = "0400486024DEC000";
        final String baseline = "b6b21fb5753a";
        byte[] full = lib(oot, baseline, INPUTS, ABI, 42339, 4096, 149);
        byte[] inputs = stamp(oot, INPUTS).getBytes(StandardCharsets.UTF_8);
        File zip = craft(new File(t, "original.zip"), full, inputs);
        File pack = new File(t, "restored");
        ShaderZip.Target target = new ShaderZip.Target(pack, oot);
        target.inputs = INPUTS;
        ShaderZip.Result result = importFile(zip, target);
        File original = new File(pack, "shaders/v-" + baseline + "/dmsh_vk.lib");
        check(result.version.equals(baseline) && result.from.equals(baseline)
                && Arrays.equals(bytes(original), full), "trusted original stays byte identical and retains version");
        check(!new File(pack, "shaders/v-" + CUR + "/dmsh_vk.lib").exists(), "original import never forges current shader version");
        check(ShaderLibs.trustedOcarinaBase(pack, oot, ABI, INPUTS) != null, "validated original library available");

        // A later accidental hot library under v-current must not be exported
        // in place of the full, known-good original.
        addLib(pack, CUR, lib(oot, CUR, INPUTS, ABI, 6, 4096, 150), stamp(oot, INPUTS));
        check(ShaderZip.chooseExport(pack, oot).equals(original), "export selects complete original rather than six shaders");

        File export = new File(t, "export");
        ShaderZip.Exported e = ShaderZip.export(pack, oot, export, "0.1.6", "src", ShaderZip.QUIET);
        check(e.version.equals(baseline) && e.shaders == 42339, "re-export keeps original version and entries");
        ShaderZip.Target again = new ShaderZip.Target(new File(t, "roundtrip"), oot);
        again.inputs = INPUTS;
        check(importStream(e.zip, again).shaders == 42339, "original can be re-imported via a document stream");

        File incomplete = craft(new File(t, "hot.zip"),
                lib(oot, baseline, INPUTS, ABI, 6, 1000, 151), inputs);
        ShaderZip.Target unsafe = new ShaderZip.Target(new File(t, "incomplete"), oot);
        unsafe.inputs = INPUTS;
        refused("incomplete baseline", ShaderZip.Why.OTHER_VERSION, incomplete, unsafe, false);

        File wrongAbi = craft(new File(t, "wrong_abi.zip"),
                lib(oot, baseline, INPUTS, "ffffffffffff", 42339, 1000, 152), inputs);
        unsafe = new ShaderZip.Target(new File(t, "wrong_abi"), oot);
        unsafe.inputs = INPUTS;
        refused("wrong baseline ABI", ShaderZip.Why.OTHER_VERSION, wrongAbi, unsafe, true);

        File wrongInputs = craft(new File(t, "wrong_inputs.zip"),
                lib(oot, baseline, "ffffffffffff", ABI, 42339, 1000, 153),
                stamp(oot, "ffffffffffff").getBytes(StandardCharsets.UTF_8));
        unsafe = new ShaderZip.Target(new File(t, "wrong_inputs"), oot);
        unsafe.inputs = INPUTS;
        refused("wrong baseline inputs", ShaderZip.Why.OTHER_VERSION, wrongInputs, unsafe, false);
    }

    static void choice(File t) throws Exception {
        byte[] cur = lib(ID, CUR, INPUTS, ABI, 3, 4096, 3), old = lib(ID, OLD, INPUTS, ABI, 3, 4096, 4);
        File both = pack(new File(t, "both"));
        addLib(both, OLD, old, stamp(ID, INPUTS));
        addLib(both, CUR, cur, stamp(ID, INPUTS));
        check(ShaderZip.chooseExport(both, ID).getParentFile().getName().equals("v-" + CUR), "this version first");
        File older = pack(new File(t, "older"));
        addLib(older, OLD, old, stamp(ID, INPUTS));
        check(ShaderZip.chooseExport(older, ID).getParentFile().getName().equals("v-" + OLD), "else the older one Play loads");
        ShaderZip.Exported e = ShaderZip.export(older, ID, new File(t, "out"), "t", "x", ShaderZip.QUIET);
        check(e.version.equals(OLD) && e.zip.getName().endsWith("-v-" + OLD + ".zip"), "its zip carries its version: " + e.zip.getName());
        ShaderZip.Failure f = failure(() -> ShaderZip.chooseExport(pack(new File(t, "none")), ID));
        check(f != null && f.why == ShaderZip.Why.NO_LIBRARY, "no library");
        File other = pack(new File(t, "other"));
        addLib(other, CUR, lib(ID, CUR, "999999999999", ABI, 3, 4096, 5), stamp(ID, "999999999999"));
        f = failure(() -> ShaderZip.chooseExport(other, ID));
        check(f != null && f.why == ShaderZip.Why.OTHER_INPUTS && f.args[0].equals("999999999999") && f.args[1].equals(INPUTS), "other inputs: " + (f == null ? null : f.why));
    }

    static void refusals(File t) throws Exception {
        byte[] lib = lib(ID, CUR, INPUTS, ABI, 4, 1 << 20, 6), in = stamp(ID, INPUTS).getBytes(StandardCharsets.UTF_8);
        File good = craft(new File(t, "good.zip"), lib, in);
        File b = pack(new File(t, "b"));
        byte[] there = lib(ID, CUR, INPUTS, ABI, 4, 1000, 7);
        addLib(b, CUR, there, stamp(ID, INPUTS));
        ShaderZip.Target tb = new ShaderZip.Target(b, ID);

        ShaderZip.Target mkw = new ShaderZip.Target(pack(new File(t, "mkw")), MKW);
        ShaderZip.Failure f = refused("other title", ShaderZip.Why.OTHER_GAME, good, mkw, false);
        check(f.args[0].contains(ID) && f.args[1].contains(MKW), "other title args");

        File oldZip = craft(new File(t, "old.zip"), lib(ID, OLD, INPUTS, ABI, 4, 1000, 8), in);
        f = refused("other version", ShaderZip.Why.OTHER_VERSION, oldZip, tb, false);
        check(f.args[0].equals(OLD) && f.args[1].equals(CUR), "both versions in the message: " + Arrays.toString(f.args));
        refused("other version, stream", ShaderZip.Why.OTHER_VERSION, oldZip, tb, true);

        byte[] otherIn = stamp(ID, "999999999999").getBytes(StandardCharsets.UTF_8);
        File otherInputs = craft(new File(t, "inputs.zip"), lib(ID, CUR, "999999999999", ABI, 4, 1000, 9), otherIn);
        refused("other inputs", ShaderZip.Why.OTHER_INPUTS, otherInputs, tb, false);
        ShaderZip.Target unknown = new ShaderZip.Target(new File(t, "unknown"), ID);
        unknown.inputs = "unknown";
        check(importFile(otherInputs, unknown).shaders == 4, "\"unknown\" profile inputs take any");

        refused("header game", ShaderZip.Why.DAMAGED, craft(new File(t, "hg.zip"), lib(MKW, CUR, INPUTS, ABI, 4, 1000, 10), in, "title_id", ID), tb, false);
        refused("header version", ShaderZip.Why.DAMAGED, craft(new File(t, "hv.zip"), lib(ID, OLD, INPUTS, ABI, 4, 1000, 10), in, "library_version", CUR), tb, false);
        refused("header abi", ShaderZip.Why.DAMAGED, craft(new File(t, "ha.zip"), lib(ID, CUR, INPUTS, "ffffffffffff", 4, 1000, 10), in, "abi", ABI), tb, false);
        refused("abi not this app's", ShaderZip.Why.DAMAGED, craft(new File(t, "ha2.zip"), lib(ID, CUR, INPUTS, "ffffffffffff", 4, 1000, 10), in), tb, false);
        byte[] big = lib(ID, CUR, INPUTS, ABI, 4, 1000, 11);
        u32(big, 72, 1000);
        refused("tables outside the file", ShaderZip.Why.DAMAGED, craft(new File(t, "tables.zip"), big, in), tb, false);
        byte[] blob = lib(ID, CUR, INPUTS, ABI, 4, 1000, 11);
        u64(blob, 104, 1L << 40);
        refused("blob outside the file", ShaderZip.Why.DAMAGED, craft(new File(t, "blob.zip"), blob, in), tb, true);
        refused("inputs.tsv of another game", ShaderZip.Why.DAMAGED, craft(new File(t, "in.zip"), lib, stamp(MKW, INPUTS).getBytes(StandardCharsets.UTF_8)), tb, false);
        refused("lib_sha256 not the library's", ShaderZip.Why.DAMAGED, craft(new File(t, "sha.zip"), lib, in, "lib_sha256", sha(there)), tb, true);
        refused("not a shaders zip", ShaderZip.Why.NOT_SHADER_ZIP, craft(new File(t, "kind.zip"), lib, in, "kind", "pack"), tb, false);

        // one flipped byte of the library inside the zip: CRC (and SHA-256) from a file and from a stream
        byte[] z = bytes(good);
        int at = indexOf(z, Arrays.copyOfRange(lib, lib.length - 64, lib.length - 32));
        check(at > 0, "the library's bytes in the zip");
        z[at + 3] ^= 1;
        File flipped = new File(t, "flipped.zip");
        write(flipped, z);
        refused("a flipped byte", ShaderZip.Why.DAMAGED, flipped, tb, false);
        refused("a flipped byte, stream", ShaderZip.Why.DAMAGED, flipped, tb, true);
        File cut = new File(t, "cut.zip");
        write(cut, Arrays.copyOf(bytes(good), (int) good.length() / 2));
        refused("a truncated zip", ShaderZip.Why.DAMAGED, cut, tb, false);
        refused("a truncated zip, stream", ShaderZip.Why.DAMAGED, cut, tb, true);

        refused("lib_size over the limit", ShaderZip.Why.TOO_BIG, craft(new File(t, "huge.zip"), lib, in, "lib_size", String.valueOf(ShaderZip.MAX_LIB + 1)), tb, false);
        ShaderZip.Target full = new ShaderZip.Target(b, ID);
        full.space = dir -> 1000;
        f = refused("no space", ShaderZip.Why.NO_SPACE, good, full, true);
        check(f.args.length == 3, "space args");

        for (String name : new String[] {"../manifest.tsv", "a/../../dmsh_vk.lib", "/manifest.tsv", "a\\manifest.tsv", "C:manifest.tsv", "x.txt", "a/b/manifest.tsv"}) {
            File bad = new File(t, "slip.zip");
            zip(bad, Arrays.asList(new Object[] {name, new byte[] {1}}, new Object[] {"manifest.tsv", manifest(lib, in)}, new Object[] {"inputs.tsv", in},
                    new Object[] {"dmsh_vk.lib", lib}));
            refused("entry " + name, ShaderZip.Why.UNSAFE_NAME, bad, tb, false);
            refused("entry " + name + ", stream", ShaderZip.Why.UNSAFE_NAME, bad, tb, true);
        }
        File extra = new File(t, "extra.zip");
        zip(extra, Arrays.asList(new Object[] {"manifest.tsv", manifest(lib, in)}, new Object[] {"inputs.tsv", in}, new Object[] {"dmsh_vk.lib", lib}, new Object[] {"x.txt", in}));
        refused("an extra file after the library", ShaderZip.Why.UNSAFE_NAME, extra, tb, false);
        refused("an extra file after the library, stream", ShaderZip.Why.UNSAFE_NAME, extra, tb, true);
        File beside = new File(t, "beside.zip");
        zip(beside, Arrays.asList(new Object[] {"top/manifest.tsv", manifest(lib, in)}, new Object[] {"inputs.tsv", in}, new Object[] {"top/dmsh_vk.lib", lib}));
        refused("a file beside the top folder", ShaderZip.Why.UNSAFE_NAME, beside, tb, false);
        // a duplicate dmsh_vk.lib (ZipOutputStream will not write one: a second name patched in)
        File dup = new File(t, "dup.zip");
        zip(dup, Arrays.asList(new Object[] {"manifest.tsv", manifest(lib, in)}, new Object[] {"inputs.tsv", in}, new Object[] {"dmsh_vk.lib", lib}, new Object[] {"dmsh_vk.liX", lib}));
        byte[] dz = bytes(dup);
        for (int i; (i = indexOf(dz, "dmsh_vk.liX".getBytes(StandardCharsets.US_ASCII))) >= 0; ) dz[i + 10] = 'b';
        write(dup, dz);
        refused("a duplicate library", ShaderZip.Why.UNSAFE_NAME, dup, tb, false);
        refused("a duplicate library, stream", ShaderZip.Why.UNSAFE_NAME, dup, tb, true);

        // the library before the manifest: a stream refuses (ORDER), the file reads it by name
        File order = new File(t, "order.zip");
        zip(order, Arrays.asList(new Object[] {"dmsh_vk.lib", lib}, new Object[] {"inputs.tsv", in}, new Object[] {"manifest.tsv", manifest(lib, in)}));
        refused("library first, stream", ShaderZip.Why.ORDER, order, tb, true);
        File o2 = new File(t, "order-file");
        check(importFile(order, new ShaderZip.Target(o2, ID)).shaders == 4 && ShaderZip.ready(o2, ID), "library first, from the file");
        // a top folder is fine
        File top = new File(t, "top.zip");
        zip(top, Arrays.asList(new Object[] {"x/", new byte[0]}, new Object[] {"x/manifest.tsv", manifest(lib, in)}, new Object[] {"x/inputs.tsv", in}, new Object[] {"x/dmsh_vk.lib", lib}));
        File t2 = new File(t, "top-in");
        check(importStream(top, new ShaderZip.Target(t2, ID)).shaders == 4, "one top folder");

        byte[] huge = new byte[(64 << 10) + 1];
        Arrays.fill(huge, (byte) '#');
        File bigMan = new File(t, "bigman.zip");
        zip(bigMan, Arrays.asList(new Object[] {"manifest.tsv", huge}, new Object[] {"inputs.tsv", in}, new Object[] {"dmsh_vk.lib", lib}));
        refused("a manifest over 64 KiB", ShaderZip.Why.NOT_SHADER_ZIP, bigMan, tb, true);
        File noIn = new File(t, "noinputs.zip");
        zip(noIn, Arrays.asList(new Object[] {"manifest.tsv", manifest(lib, in)}, new Object[] {"dmsh_vk.lib", lib}));
        refused("no inputs.tsv", ShaderZip.Why.NOT_SHADER_ZIP, noIn, tb, true);
        check(Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), there), "the pack's library as it was");
    }

    static int indexOf(byte[] h, byte[] n) {
        outer:
        for (int i = 0; i + n.length <= h.length; i++) {
            for (int k = 0; k < n.length; k++) if (h[i + k] != n[k]) continue outer;
            return i;
        }
        return -1;
    }

    static void cancel(File t) throws Exception {
        byte[] lib = lib(ID, CUR, INPUTS, ABI, 4, 5 << 20, 12), there = lib(ID, CUR, INPUTS, ABI, 4, 1000, 13);
        File zip = craft(new File(t, "c.zip"), lib, stamp(ID, INPUTS).getBytes(StandardCharsets.UTF_8));
        File b = pack(new File(t, "b"));
        addLib(b, CUR, there, stamp(ID, INPUTS));
        ShaderZip.Target tb = new ShaderZip.Target(b, ID);
        long[] seen = {0};
        ShaderZip.Progress stop = new ShaderZip.Progress() {
            @Override public void at(int phase, long done, long total) { seen[0] = done; }
            @Override public boolean cancelled() { return seen[0] >= 2 << 20; }
        };
        ShaderZip.Failure f = failure(() -> { try (InputStream in = new FileInputStream(zip)) { ShaderZip.read(in, zip.getName(), tb, stop); } });
        check(f != null && f.why == ShaderZip.Why.CANCELLED, "cancelled");
        check(Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), there) && noStaging(b), "a cancel leaves the pack as it was");
        File outDir = new File(t, "out");
        f = failure(() -> ShaderZip.export(addLibPack(new File(t, "src"), lib), ID, outDir, "t", "x", stop));
        String[] left = outDir.list();
        check(f != null && f.why == ShaderZip.Why.CANCELLED && (left == null || left.length == 0), "a cancelled export leaves no file");
    }

    static File addLibPack(File dir, byte[] lib) throws IOException {
        pack(dir);
        addLib(dir, CUR, lib, stamp(ID, INPUTS));
        return dir;
    }

    static void replace(File t) throws Exception {
        byte[] lib = lib(ID, CUR, INPUTS, ABI, 4, 70000, 14), there = lib(ID, CUR, INPUTS, ABI, 4, 1000, 15);
        File zip = craft(new File(t, "r.zip"), lib, stamp(ID, INPUTS).getBytes(StandardCharsets.UTF_8));
        File b = pack(new File(t, "b"));
        addLib(b, CUR, there, stamp(ID, INPUTS));
        ShaderZip.Target tb = new ShaderZip.Target(b, ID);
        ShaderZip.Staged st = ShaderZip.read(zip, tb, ShaderZip.QUIET);
        ShaderZip.recover(new File(b.getPath()));   // AppStorage.pack from another thread, between the read and the install
        check(st.dir.isDirectory() && Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), there), "recover leaves a staged import alone");
        ShaderZip.install(st, tb);
        check(Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), lib) && noStaging(b), "the library there is replaced");
        ShaderZip.Staged st2 = ShaderZip.read(zip, tb, ShaderZip.QUIET);
        ShaderZip.unstage(st2);
        check(!st2.dir.exists() && Arrays.equals(bytes(new File(b, "shaders/v-" + CUR + "/dmsh_vk.lib")), lib), "an import not installed after all: unstaged");
        // stopped between the two renames: the old one is aside, v-<V> missing
        File v = new File(b, "shaders/v-" + CUR), aside = new File(b, "shaders/.replaced-" + CUR);
        check(v.renameTo(aside), "set up");
        new File(b, "shaders/.import-" + CUR).mkdirs();
        ShaderZip.recover(b);
        check(Arrays.equals(bytes(new File(v, "dmsh_vk.lib")), lib) && noStaging(b), "recover puts it back and clears a stale import");
        // stopped after the new one has its name: the old one aside goes
        aside.mkdirs();
        write(new File(aside, "dmsh_vk.lib"), there);
        ShaderZip.recover(b);
        check(!aside.exists() && Arrays.equals(bytes(new File(v, "dmsh_vk.lib")), lib), "an old one aside goes when v-<V> is there");
    }

    /** What ShaderLibs.restamp writes: the header's version and abi set */
    static byte[] stamped(byte[] lib, String version, String abi) {
        byte[] b = lib.clone();
        Arrays.fill(b, 24, 40, (byte) 0);
        put(b, 24, version);
        Arrays.fill(b, 116, 128, (byte) 0);
        byte[] a = abi.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(a, 0, b, 116, 12);
        return b;
    }

    static void restamp(File t) throws Exception {
        byte[] old = lib(ID, OLD, INPUTS, ABI, 4, 9000, 16);
        File src = pack(new File(t, "src"));
        addLib(src, OLD, old, stamp(ID, INPUTS));
        ShaderZip.Exported e = ShaderZip.export(src, ID, new File(t, "out"), "t", "x", ShaderZip.QUIET);
        check(e.version.equals(OLD), "an older library exported");
        File d = new File(t, "d");
        ShaderZip.Target td = new ShaderZip.Target(d, ID);
        td.stamps = OLD + ":" + sha(old) + ":" + sha(stamped(old, CUR, ABI));
        ShaderZip.Result r = importFile(e.zip, td);
        check(r.version.equals(CUR) && r.from.equals(OLD) && Arrays.equals(bytes(new File(d, "shaders/v-" + CUR + "/dmsh_vk.lib")), stamped(old, CUR, ABI)), "restamped into this version");
        check(ShaderZip.ready(d, ID) && ShaderZip.imported(d) && noStaging(d), "ready after the restamp");
        File d2 = new File(t, "d2");
        ShaderZip.Target t2 = new ShaderZip.Target(d2, ID);
        t2.stamps = OLD + ":" + sha(new byte[] {1}) + ":" + sha(stamped(old, CUR, ABI));
        ShaderZip.Failure f = failure(() -> importFile(e.zip, t2));
        check(f != null && f.why == ShaderZip.Why.OTHER_VERSION && !new File(d2, "shaders/v-" + OLD).exists() && noStaging(d2), "a row for other bytes: refused, nothing kept");
        File d3 = new File(t, "d3");
        ShaderZip.Target t3 = new ShaderZip.Target(d3, ID);
        t3.stamps = OLD + ":" + sha(old) + ":" + sha(new byte[] {2});   // the restamp's result is not the row's: undone
        f = failure(() -> importFile(e.zip, t3));
        check(f != null && f.why == ShaderZip.Why.OTHER_VERSION && !new File(d3, "shaders/v-" + OLD).exists() && !new File(d3, "shaders/v-" + CUR).exists() && noStaging(d3),
                "a restamp that does not give the row's library: undone");
    }

    static void lists(File t) throws Exception {
        File only = new File(t, "only");
        new File(only, "shaders").mkdirs();
        check(ShaderZip.onlyShaders(only) && !ShaderZip.onlyShaders(pack(new File(t, "p"))) && !ShaderZip.onlyShaders(new File(t, "none")), "onlyShaders");
        File dir = new File(t, "dir"), dl = new File(t, "dl");
        File older = new File(dir, "swap2-shaders-" + ID + "-1-v-a.zip"), newer = new File(dl, "swap2-shaders-" + ID + "-2-v-b.zip");
        write(older, "a");
        write(newer, "b");
        write(new File(dir, "swap2-shaders-" + MKW + "-1-v-a.zip"), "c");
        write(new File(dir, "swap2-pack-" + ID + "-1.zip"), "d");
        write(new File(dir, "swap2-shaders-" + ID + "-1-v-a.txt"), "e");
        older.setLastModified(1_000_000_000_000L);
        newer.setLastModified(1_100_000_000_000L);
        List<File> f = ShaderZip.found(ID, dir, dl, new File(t, "missing"));
        check(f.equals(Arrays.asList(newer, older)), "found: " + f);
        check(ShaderZip.found(ID).isEmpty(), "no folders");
    }

    static InputStream stream(byte[] b) { return new ByteArrayInputStream(b); }
}
