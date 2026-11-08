package dev.nxnative.android;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * ExefsMods on the JVM, driven by dm/tools/tests/test_exefs_patches.py: arguments are a mods folder, a title ID and build IDs; for each build ID it prints
 * "find &lt;build ID&gt; &lt;label&gt;|&lt;label&gt;… &lt;digest&gt;" (labels and digest as exefs_patches.find and digest make them, "-" for none), then for each
 * .pchtxt file below the title folder "pchtxt &lt;path below the mods folder&gt; &lt;its build ID or -&gt;", and the key part of a sample key, which the test
 * compares with the Python side's.
 * <p>
 * With --install (javac + java, no Gradle runner: {@code javac -d out ExefsMods.java ExefsModsJvmTest.java && java -cp out dev.nxnative.android.ExefsModsJvmTest --install}):
 * the settings page's helpers (GameSettings' Mods section) on a temporary folder: a zip installed with traversal, absolute, hidden and stray entries left out and
 * reported, its layouts and Atmosphere's; a single .ips; on and off (find follows) with the clash rule; replace and keep both; remove (a mod folder only); the size
 * limit, a damaged zip and a file that is no mod refused with an IOException and no staging folder left; a picked folder. Prints "ok &lt;n&gt;" and exits 0, or throws.
 */
public final class ExefsModsJvmTest {
    private static int n;

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        n++;
    }

    static byte[] zip(String[][] entries) throws IOException {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(o)) {
            for (String[] e : entries) {
                z.putNextEntry(new ZipEntry(e[0]));
                z.write(e[1].getBytes(StandardCharsets.ISO_8859_1));
                z.closeEntry();
            }
        }
        return o.toByteArray();
    }

    static InputStream in(byte[] b) { return new ByteArrayInputStream(b); }

    static InputStream in(String s) { return in(s.getBytes(StandardCharsets.ISO_8859_1)); }

    static boolean noStaging(File root) {
        String[] l = root.list();
        if (l != null) for (String s : l) if (s.startsWith(ExefsMods.STAGING)) return false;
        return true;
    }

    static ExefsMods.Mod mod(File root, String t, String name) {
        for (ExefsMods.Mod m : ExefsMods.list(root, t)) if (m.name.equals(name)) return m;
        throw new AssertionError("no mod " + name);
    }

    static String placed(String entry) {
        String[] at = ExefsMods.place(entry, new String[1]);
        return at == null ? null : at[0] + "|" + at[1];
    }

    static void refused(File root, InputStream s, String name, String what) {
        try {
            ExefsMods.stage(root, s, name);
            throw new AssertionError(what + ": not refused");
        } catch (IOException e) {
            check(e.getMessage() != null && !e.getMessage().isEmpty() && noStaging(root), what + ": " + e.getMessage());
        }
    }

    static void install() throws Exception {
        File tmp = Files.createTempDirectory("exefsmods").toFile(), root = new File(tmp, "mods");
        String t = "0100000000010000", bid = "aa" + "0".repeat(38);
        String ips = "PATCH\0\0\0\0\1AEOF";
        String[] why = new String[1];
        for (String e : new String[] {"../x.ips", "a/../../x.ips", "/x.ips", "C:\\x.ips", "m/romfs/x.ips", "m/exefs/x.txt", "m/exefs/a?b.ips"})
            check(ExefsMods.place(e, why) == null && why[0] != null, "place refuses " + e);
        check(ExefsMods.place("__MACOSX/exefs/._x.ips", why) == null && why[0] == null, "place: hidden, quietly");
        check("m|x.IPS".equals(placed("m/ExeFS/x.IPS")), "place <mod>/exefs");
        check("m|x.pchtxt".equals(placed("0100/m/exefs/x.pchtxt")), "place deeper");
        check("|x.ips".equals(placed("./exefs/x.ips")) && "|x.ips".equals(placed("x.ips")), "place exefs/ and bare: the zip's name");
        check("atmo|x.ips".equals(placed("exefs_patches/atmo/x.ips")), "place Atmosphere's");
        check(ExefsMods.cleanName("-.My: mod. ").equals("My_ mod") && ExefsMods.stem("dir/My Mod.v2.zip").equals("My Mod.v2"), "cleanName, stem");

        byte[] z = zip(new String[][] {
            {"exefs/" + bid + ".ips", ips}, {"../evil.ips", ips}, {"/abs.ips", ips}, {"a/../../evil2.ips", ips}, {"exefs/readme.txt", "hi"},
            {"__MACOSX/exefs/._" + bid + ".ips", "x"}, {"Other/exefs/b.pchtxt", "@nsobid-" + bid + "\n@flag offset_shift 0x100\n"},
            {"x/exefs_patches/Atmo/" + bid + ".ips", ips}, {"m/notexefs/" + bid + ".ips", ips}, {"exefs/bad.ips", "NOTIPS"}, {"EXEFS/" + bid.toUpperCase() + ".ips", ips}});
        ExefsMods.Staged st = ExefsMods.stage(root, in(z), "My Mod.zip");
        check(st.names().equals(Arrays.asList("My Mod", "Other", "Atmo")), "staged mods " + st.names());
        String sk = String.join(";", st.skipped);
        for (String e : new String[] {"../evil.ips", "/abs.ips", "a/../../evil2.ips", "exefs/readme.txt", "m/notexefs/", "exefs/bad.ips", "EXEFS/"})
            check(sk.contains(e), "reported " + e + ": " + sk);
        check(!sk.contains("MACOSX") && st.files == 3, "hidden left out quietly; three files");
        check(ExefsMods.clashes(root, t, st).isEmpty(), "no clash yet");
        check(ExefsMods.commit(root, t, st, false).equals(Arrays.asList("My Mod", "Other", "Atmo")), "committed");
        check(noStaging(root), "staging gone");
        try (Stream<Path> w = Files.walk(tmp.toPath())) {
            check(w.noneMatch(p -> p.getFileName().toString().startsWith("evil") || p.getFileName().toString().equals("abs.ips")), "nothing written outside the mods");
        }
        check(new File(root, t + "/My Mod/exefs/" + bid + ".ips").isFile() && new File(root, t + "/Other/exefs/b.pchtxt").isFile()
                && new File(root, t + "/Atmo/exefs/" + bid + ".ips").isFile(), "files in place");
        check(ExefsMods.list(root, t).size() == 3 && mod(root, t, "My Mod").patches().size() == 1 && mod(root, t, "My Mod").matching(bid).size() == 1, "list, patches, matching");
        check(mod(root, t, "Other").matching(bid).size() == 1 && mod(root, t, "Other").matching("bb").isEmpty(), "pchtxt matching");
        check(ExefsMods.find(root, t, bid).size() == 3, "find: three mods");

        ExefsMods.Mod off = ExefsMods.setEnabled(mod(root, t, "My Mod"), false);
        check(!off.on && off.dir.getName().equals("-My Mod") && off.name.equals("My Mod"), "off");
        check(ExefsMods.find(root, t, bid).size() == 2, "find leaves out the mod that is off");
        ExefsMods.Staged again = ExefsMods.stage(root, in(zip(new String[][] {{bid + ".ips", ips}})), "my mod.zip");
        check(ExefsMods.clashes(root, t, again).equals(Arrays.asList("my mod")), "a mod that is off clashes too, in any case");
        check(ExefsMods.commit(root, t, again, false).equals(Arrays.asList("my mod (2)")), "keep both");
        check(new File(root, t + "/-My Mod").isDirectory(), "keep both keeps the old one");
        check(new File(root, t + "/My Mod").mkdirs(), "a clashing folder");
        ExefsMods.Mod on = ExefsMods.setEnabled(off, true);
        check(on.on && on.dir.getName().equals("My Mod (3)") && on.dir.isDirectory() && !off.dir.exists(), "on with a clash: the first free name, " + on.dir.getName());

        check(ExefsMods.install(root, t, in(ips), bid + ".ips", false).equals(Arrays.asList(bid)), "a single .ips");
        check(new File(root, t + "/" + bid + "/exefs/" + bid + ".ips").isFile(), "a single .ips in <its name>/exefs");
        ExefsMods.Staged rep = ExefsMods.stage(root, in(zip(new String[][] {{"exefs/cc.ips", ips}})), "OTHER.zip");
        check(ExefsMods.clashes(root, t, rep).equals(Arrays.asList("OTHER")), "replace: the clash");
        check(ExefsMods.commit(root, t, rep, true).equals(Arrays.asList("OTHER")), "replaced");
        File[] oth = new File(root, t).listFiles(f -> f.getName().equalsIgnoreCase("other"));
        check(oth != null && oth.length == 1 && new File(oth[0], "exefs/cc.ips").isFile() && !new File(oth[0], "exefs/b.pchtxt").exists(), "replace drops the old one");

        File atmo = new File(root, t + "/exefs_patches/A2");
        check(atmo.mkdirs() && new File(atmo, bid + ".ips").createNewFile(), "an Atmosphere mod");
        ExefsMods.Mod a2 = mod(root, t, "A2");
        check(a2.atmosphere && a2.exefs().equals(atmo) && a2.patches().size() == 1, "Atmosphere's listed");
        a2 = ExefsMods.setEnabled(a2, false);
        check(a2.dir.getName().equals("-A2") && a2.dir.getParentFile().getName().equals("exefs_patches"), "Atmosphere's off in its folder");
        ExefsMods.remove(root, t, a2);
        check(!a2.dir.exists() && new File(root, t + "/exefs_patches").isDirectory(), "remove: the mod only");
        for (File not : new File[] {new File(root, t), new File(root, t + "/exefs_patches"), root, tmp}) {
            try {
                ExefsMods.remove(root, t, new ExefsMods.Mod(not, false));
                throw new AssertionError("removed " + not);
            } catch (IOException e) { check(not.isDirectory(), "remove refuses " + not); }
        }
        int before = ExefsMods.list(root, t).size();
        ExefsMods.remove(root, t, mod(root, t, bid));
        check(ExefsMods.list(root, t).size() == before - 1 && !new File(root, t + "/" + bid).exists(), "remove a mod");

        int size = ExefsMods.list(root, t).size();
        refused(root, in(zip(new String[][] {{"exefs/big.pchtxt", "x".repeat((int) ExefsMods.MAX_BYTES + 1)}})), "big.zip", "the size limit");
        refused(root, in("PK\3\4garbage that is no zip"), "bad.zip", "a damaged zip");
        refused(root, in("hello"), "notes.txt", "not a mod");
        refused(root, in(zip(new String[][] {{"romfs/x.bin", "x"}, {"../../x.ips", ips}})), "romfs.zip", "a zip with no patch to take");
        check(ExefsMods.list(root, t).size() == size, "refusals change nothing");

        ExefsMods.Staged mm = ExefsMods.stage(root, in(ips), bid + ".ips");
        mm.mods.clear();
        mm.mods.put("my mod", "My Mod");   // as a "My Mod.zip" would stage it: the names Keep both would give, without unpacking one
        check(ExefsMods.keepBothNames(root, t, mm).equals(Arrays.asList("My Mod (4)")), "keep both names the free one: " + ExefsMods.keepBothNames(root, t, mm));
        ExefsMods.discard(mm);
        File grp = new File(root, t + "/-exefs_patches");   // Atmosphere's folder off as a whole
        for (String g : new String[] {"G1", "G2"})
            check(new File(grp, g).mkdirs() && new File(grp, g + "/" + bid + ".ips").createNewFile(), "a mod in -exefs_patches");
        int found = ExefsMods.find(root, t, bid).size();
        ExefsMods.Mod g1 = mod(root, t, "G1");
        check(g1.atmosphere && g1.groupOff && !g1.on && mod(root, t, "G2").groupOff, "-exefs_patches: its mods, off");
        for (ExefsMods.Mod m : ExefsMods.list(root, t)) check(!ExefsMods.atmosphereGroup(m.dir.getName()), "-exefs_patches is not a mod itself");
        g1 = ExefsMods.setEnabled(g1, true);
        check(g1.on && !g1.groupOff && g1.dir.equals(new File(root, t + "/exefs_patches/G1")) && !new File(grp, "G1").exists(), "on: into exefs_patches");
        check(ExefsMods.find(root, t, bid).size() == found + 1 && !mod(root, t, "G2").on && new File(grp, "G2").isDirectory(), "on: that one only");
        ExefsMods.Staged g2 = ExefsMods.stage(root, in(zip(new String[][] {{bid + ".ips", ips}})), "g2.zip");
        check(ExefsMods.clashes(root, t, g2).equals(Arrays.asList("g2")), "a clash with an Atmosphere mod");
        check(ExefsMods.keepBothNames(root, t, g2).equals(Arrays.asList("g2 (2)")), "keep both: not the Atmosphere mod's name");
        check(ExefsMods.commit(root, t, g2, false).equals(Arrays.asList("g2 (2)")) && new File(grp, "G2").isDirectory(), "keep both with an Atmosphere mod");
        ExefsMods.Staged g1z = ExefsMods.stage(root, in(zip(new String[][] {{"exefs/dd.ips", ips}})), "g1.zip");
        check(ExefsMods.commit(root, t, g1z, true).equals(Arrays.asList("g1")), "replace an Atmosphere mod");
        check(!new File(root, t + "/exefs_patches/G1").exists() && new File(root, t + "/exefs_patches").isDirectory() && new File(root, t + "/g1/exefs/dd.ips").isFile(),
                "replace: the Atmosphere mod only, its folder kept");
        ExefsMods.remove(root, t, mod(root, t, "G2"));
        check(!new File(grp, "G2").exists() && grp.isDirectory(), "remove a mod of -exefs_patches, not the folder");

        File src = new File(tmp, "pick/Folder Mod");
        check(new File(src, "exefs").mkdirs() && new File(src, "romfs").mkdirs(), "a picked folder");
        Files.write(new File(src, "exefs/" + bid + ".ips").toPath(), ips.getBytes(StandardCharsets.ISO_8859_1));
        Files.write(new File(src, "romfs/x.bin").toPath(), new byte[] {1});
        ExefsMods.Staged fs = ExefsMods.stage(root, src);
        check(fs.names().equals(Arrays.asList("Folder Mod")) && String.join(";", fs.skipped).contains("romfs/x.bin"), "folder staged " + fs.names() + " " + fs.skipped);
        ExefsMods.commit(root, t, fs, false);
        check(new File(root, t + "/Folder Mod/exefs/" + bid + ".ips").isFile() && new File(src, "exefs/" + bid + ".ips").isFile(), "folder copied, the source kept");
        ExefsMods.Staged ex = ExefsMods.stage(root, new File(src, "exefs"));
        check(ex.names().equals(Arrays.asList("Folder Mod")), "a picked exefs folder is named after its mod");
        ExefsMods.discard(ex);
        check(noStaging(root), "discard");
        ExefsMods.deleteTree(tmp.toPath());
        check(!tmp.exists(), "deleteTree");
        System.out.println("ok " + n);
    }

    public static void main(String[] a) throws Exception {
        if (a.length == 1 && a[0].equals("--install")) { install(); return; }
        File root = new File(a[0]);
        for (int i = 2; i < a.length; i++) {
            List<ExefsMods.Entry> fs = ExefsMods.find(root, a[1], a[i]);
            StringBuilder s = new StringBuilder();
            for (ExefsMods.Entry e : fs) s.append(s.length() == 0 ? "" : "|").append(e.label);
            String d = ExefsMods.digest(fs);
            System.out.println("find " + a[i] + " " + (s.length() == 0 ? "-" : s) + " " + (d.isEmpty() ? "-" : d));
        }
        try (java.util.stream.Stream<java.nio.file.Path> w = Files.walk(root.toPath())) {
            for (java.nio.file.Path p : (Iterable<java.nio.file.Path>) w.sorted()::iterator) {
                if (!p.toString().toLowerCase(java.util.Locale.ROOT).endsWith(".pchtxt") || !Files.isRegularFile(p)) continue;
                String id = ExefsMods.pchtxtBuildId(Files.readAllBytes(p));
                System.out.println("pchtxt " + root.toPath().relativize(p).toString().replace('\\', '/') + " " + (id == null ? "-" : id));
            }
        }
        System.out.println("key " + ExefsMods.keyPart("abc target=android mods=0123") + "|" + ExefsMods.keyPart("abc target=android"));
    }
}
