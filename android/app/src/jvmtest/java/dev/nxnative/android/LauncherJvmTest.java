package dev.nxnative.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * The launcher's pure-Java helpers on the JVM (no Android): SaveStore (save backup, restore, the roll-forward journal, the lock), SaveZip (a save as a .zip: finding
 * this game's save in another emulator's zip, the limits, import and export), SaveMigrate (the one-time copy of the old default save into app storage) and Profile
 * (the APK's game table).
 * Run by dm/tools/tests/test_android_saves.py, which compiles this with SaveStore.java, SaveZip.java, SaveMigrate.java, Profile.java and a stub BuildConfig.
 * <ul>
 * <li>{@code <scratch folder>}: every case; prints "ok <n>" and exits 0, or the first failure and exits 1</li>
 * <li>{@code recover <save>}: SaveStore.recover on that save, printing "recovered", "nothing" or "refused: …" (the journal cross-check against plat_swap_recover)</li>
 * <li>{@code hold <save>}: takes the save's lock, prints "held" and keeps it until stdin closes (another process holding it); {@code holdtwice <save>} asks for it
 *     again and checks inUse while holding it first (the one-channel rule: neither may drop the lock)</li>
 * <li>{@code locked <save>}: expects backup, restore and recover of that save to be refused while another process holds its lock; prints "refused 3"</li>
 * </ul>
 */
public final class LauncherJvmTest {
    private static int n;

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        n++;
    }

    static void write(File f, String s) throws IOException {
        f.getParentFile().mkdirs();
        Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8));
    }

    /** A save like the host's: the files the game writes, in DM_SAVE */
    static File save(File root, String tag) throws IOException {
        File s = new File(root, "saves/040074A01BF12000");
        write(new File(s, "slot0.bin"), "slot0 " + tag);
        write(new File(s, "common/common.bin"), "common " + tag);
        new File(s, "empty").mkdirs();
        return s;
    }

    public static void main(String[] args) throws Exception {
        if (args[0].equals("recover")) {
            try { System.out.println(SaveStore.recover(new File(args[1])) ? "recovered" : "nothing"); } catch (IOException e) { System.out.println("refused: " + e.getMessage()); }
            return;
        }
        if (args[0].equals("hold") || args[0].equals("holdtwice")) {
            try (SaveStore.Lock l = SaveStore.lock(new File(args[1]))) {
                if (args[0].equals("holdtwice") && (SaveStore.tryLock(new File(args[1])) != null || !SaveStore.inUse(new File(args[1])))) throw new AssertionError("held twice");
                System.out.println("held");
                System.out.flush();
                while (System.in.read() >= 0) { /* until stdin closes */ }
            }
            return;
        }
        if (args[0].equals("locked")) { locked(new File(args[1])); return; }
        File t = new File(args[0]);
        profiles();
        upscalerScene(new File(t, "scene"));
        backup(new File(t, "backup"));
        restore(new File(t, "restore"));
        device(new File(t, "device"));
        damaged(new File(t, "damaged"));
        crash(new File(t, "crash"));
        markers(new File(t, "markers"));
        lockSameProcess(new File(t, "lock"));
        edges(new File(t, "edges"));
        review3(new File(t, "review3"));
        migrate(new File(t, "migrate"));
        saveZip(new File(t, "savezip"));
        System.out.println("ok " + n);
    }

    /** A zip of these entries (name → content; a name ending in / is a folder) */
    static File zip(File f, String... nameContent) throws IOException {
        f.getParentFile().mkdirs();
        try (ZipOutputStream z = new ZipOutputStream(new FileOutputStream(f))) {
            for (int i = 0; i < nameContent.length; i += 2) {
                z.putNextEntry(new ZipEntry(nameContent[i]));
                if (nameContent[i + 1] != null) z.write(nameContent[i + 1].getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        return f;
    }

    static SaveZip.Why why(SaveZip.Source s, String tid) {
        try { SaveZip.plan(s, tid); return null; } catch (SaveZip.Failure f) { return f.why; } catch (IOException e) { return null; }
    }

    /** SaveZip: names, finding the save in other emulators' layouts, the limits, import into a save (verified restore) and export read back by the importer */
    static void saveZip(File t) throws Exception {
        String tid = "040074A01BF12000", eden = "nand/user/save/0000000000000000/0123456789ABCDEF0123456789ABCDEF/";
        // names
        check("a/b".equals(SaveZip.clean("a\\b")) && "a/b".equals(SaveZip.clean("./a//b/")), "clean: backslashes, dots and empty segments");
        check(SaveZip.clean("__MACOSX/x") == null && SaveZip.clean("a/.DS_Store") == null && SaveZip.clean("./") == null, "clean: junk and the top itself left out");
        for (String bad : new String[] {"../x", "a/../../x", "/etc/x", "C:/x", "a/b:c"})
            try { SaveZip.clean(bad); check(false, "unsafe name taken: " + bad); } catch (SaveZip.Failure f) { check(f.why == SaveZip.Why.UNSAFE_NAME, "unsafe: " + bad); }
        // Eden / Lichii / yuzu: the title ID folder under nand/user/save, any case; a mod folder and a shader cache named by title ID are not the save
        File ez = zip(new File(t, "eden.zip"), "load/" + tid + "/mod/exefs/x.ips", "ips", "shader/" + tid.toLowerCase() + "/cache.bin", "cache",
                eden + tid.toLowerCase() + "/", null, eden + tid.toLowerCase() + "/account.sav", "acct", eden + tid.toLowerCase() + "/slot_00", "slot zero",
                "config/qt-config.ini", "ini");
        List<SaveZip.Part> ps = SaveZip.plan(new SaveZip.Source(ez), tid);
        check(ps.size() == 1 && ps.get(0).prefix.equals(eden + tid.toLowerCase()) && ps.get(0).files == 2 && ps.get(0).device == null, "Eden layout: the save folder only, " + ps.size());
        // the same zip read as a stream (a document without a path)
        List<SaveZip.Part> pss = SaveZip.plan(new SaveZip.Source(() -> new FileInputStream(ez), "eden.zip"), tid);
        check(pss.size() == 1 && pss.get(0).prefix.equals(ps.get(0).prefix) && pss.get(0).bytes == ps.get(0).bytes, "the stream finds the same part with its sizes");
        // the save's own files at the top; or its one top folder (a Ryujinx 0/ folder zipped)
        check(SaveZip.plan(new SaveZip.Source(zip(new File(t, "top.zip"), "slot_00", "s", "sub/x", "x")), tid).get(0).prefix.isEmpty(), "files at the top: the whole zip");
        List<SaveZip.Part> one = SaveZip.plan(new SaveZip.Source(zip(new File(t, "one.zip"), "0/", null, "0/ExtraData0", "e", "0/data/slot", "s")), tid);
        check(one.size() == 1 && one.get(0).prefix.equals("0") && one.get(0).files == 2, "one top folder: that folder");
        // two users with this game's save: both offered, the newest first
        File two = new File(t, "two.zip");
        try (ZipOutputStream z = new ZipOutputStream(new FileOutputStream(two))) {
            String[] users = {"nand/user/save/0000000000000000/AAAA/", "nand/user/save/0000000000000000/BBBB/"};
            long[] times = {1_600_000_000_000L, 1_700_000_000_000L};
            for (int i = 0; i < 2; i++) {
                ZipEntry e = new ZipEntry(users[i] + tid + "/slot_00");
                e.setTime(times[i]);
                z.putNextEntry(e);
                z.write(("user " + i).getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        List<SaveZip.Part> tw = SaveZip.plan(new SaveZip.Source(two), tid);
        check(tw.size() == 2 && tw.get(0).prefix.contains("BBBB"), "two saves: the newest first");
        // refused: no save, an unsafe name, a name twice in two cases, a part over the limits
        check(why(new SaveZip.Source(zip(new File(t, "none.zip"), "a/x", "x", "b/y", "y")), tid) == SaveZip.Why.NONE_FOUND, "no save in the zip");
        check(why(new SaveZip.Source(zip(new File(t, "slip.zip"), tid + "/ok", "o", "../../evil", "e")), tid) == SaveZip.Why.UNSAFE_NAME, "zip-slip refused");
        check(why(new SaveZip.Source(zip(new File(t, "dup.zip"), tid + "/Slot", "a", tid + "/slot", "b")), tid) == SaveZip.Why.DUPLICATE, "a name twice in two cases");
        check(why(new SaveZip.Source(write2(new File(t, "notzip.zip"), "not a zip")), tid) == SaveZip.Why.NOT_ZIP, "not a zip");
        List<SaveZip.Item> big = new ArrayList<>();
        big.add(new SaveZip.Item(tid + "/a", false, SaveStore.MAX_SAVE_BYTES, 0));
        big.add(new SaveZip.Item(tid + "/b", false, 1, 0));
        SaveZip.Failure fb = SaveZip.refuse(SaveZip.find(big, tid).get(0), big);
        check(fb != null && fb.why == SaveZip.Why.FILE_TOO_BIG, "a file over the limit refused before anything is written");
        big.clear();
        for (int i = 0; i < 3; i++) big.add(new SaveZip.Item(tid + "/f" + i, false, SaveStore.MAX_SAVE_BYTES / 2, 0));
        fb = SaveZip.refuse(SaveZip.find(big, tid).get(0), big);
        check(fb != null && fb.why == SaveZip.Why.TOO_BIG, "a part over the total refused before anything is written");
        // the yuzu family's device save (the all-zero user) is the device save of the user's save beside it, never a save of its own
        String zero = "nand/user/save/0000000000000000/" + SaveZip.ZERO_USER + "/";
        File zd = new File(t, "zerodev.zip");
        try (ZipOutputStream z = new ZipOutputStream(new FileOutputStream(zd))) {
            String[][] es = {{eden + tid + "/slot_00", "user save"}, {zero + tid + "/device.bin", "device save"}};
            long[] times = {1_600_000_000_000L, 1_700_000_000_000L};   // the device save newer: it was ranked first before
            for (int i = 0; i < 2; i++) {
                ZipEntry e = new ZipEntry(es[i][0]);
                e.setTime(times[i]);
                z.putNextEntry(e);
                z.write(es[i][1].getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        List<SaveZip.Part> zp = SaveZip.plan(new SaveZip.Source(zd), tid);
        check(zp.size() == 1 && zp.get(0).prefix.equals(eden + tid) && (zero + tid).equals(zp.get(0).device) && zp.get(0).files == 2, "the all-zero user: the device save");
        check(why(new SaveZip.Source(zip(new File(t, "zeroonly.zip"), zero + tid + "/device.bin", "d")), tid) == SaveZip.Why.NONE_FOUND, "a device save alone is not the save");
        // an emulator's folder zipped without this game's save: refused, not taken whole (its keys, another game's save)
        check(why(new SaveZip.Source(zip(new File(t, "emu.zip"), "qt-config.ini", "ini", "keys/prod.keys", "k", eden + "0100000000010000/slot", "s")), tid)
                == SaveZip.Why.NONE_FOUND, "an emulator's folder at the top refused");
        check(why(new SaveZip.Source(zip(new File(t, "emu1.zip"), "yuzu/qt-config.ini", "ini", "yuzu/" + eden + "0100000000010000/slot", "s")), tid)
                == SaveZip.Why.NONE_FOUND, "an emulator's folder as the one top folder refused");
        check(why(new SaveZip.Source(zip(new File(t, "keys.zip"), "prod.keys", "k", "title.keys", "t")), tid) == SaveZip.Why.NONE_FOUND, "keys are no save");
        check(why(new SaveZip.Source(zip(new File(t, "other.zip"), "0100000000010000/slot", "s")), tid) == SaveZip.Why.NONE_FOUND, "a folder named by another ID refused");
        // Ryujinx's save folder (bis/user/save/<number>/ with 0/ and 1/): its committed 0/, zipped as that folder or as its contents
        List<SaveZip.Part> ry = SaveZip.plan(new SaveZip.Source(zip(new File(t, "ryu.zip"), "0000000000000001/0/slot", "committed", "0000000000000001/1/slot", "working",
                "0000000000000001/.lock", "")), tid);
        check(ry.size() == 1 && ry.get(0).prefix.equals("0000000000000001/0") && ry.get(0).files == 1, "Ryujinx's save folder: its 0/");
        ry = SaveZip.plan(new SaveZip.Source(zip(new File(t, "ryu2.zip"), "0/slot", "committed", "1/slot", "working")), tid);
        check(ry.size() == 1 && ry.get(0).prefix.equals("0"), "Ryujinx's save folder's contents: its 0/");

        // import: the save becomes the zip's part, the old one is backed up first, nothing is left beside the save
        File s = save(new File(t, "imp"), "old"), bk = new File(t, "imp/save-backups/" + tid);
        SaveStore.Manifest old = SaveStore.scan(s);
        SaveStore.Restored r = SaveZip.importZip(new SaveZip.Source(ez), ps.get(0), s, bk, "20261108-100000");
        check(text(new File(s, "account.sav")).equals("acct") && text(new File(s, "slot_00")).equals("slot zero") && !new File(s, "slot0.bin").exists(), "imported: only the save's files");
        check(r.before != null && SaveStore.scan(new File(r.before.dir, "main")).diff(old) == null, "the old save backed up first");
        check(!SaveZip.staging(s).exists() && !new File(s.getPath() + SaveStore.RESTORE_SUFFIX).exists() && !SaveStore.pending(s), "no staging, copy or marker left");
        // the stream path imports the same
        File s2 = new File(t, "imp2/saves/" + tid);
        SaveZip.importZip(new SaveZip.Source(() -> new FileInputStream(ez), "eden.zip"), pss.get(0), s2, new File(t, "imp2/bk"), "20261108-100001");
        check(SaveStore.scan(s2).diff(SaveStore.scan(s)) == null, "the stream imports the same files");
        // a staging folder left by a stopped import is cleared (launcher start, game start)
        write(new File(SaveZip.staging(s), "x.bin"), "left");
        check(SaveStore.clearLeftovers(s) > 0 && !SaveZip.staging(s).exists(), "a stopped import's staging folder is removed");

        // export: TITLE ID/ and TITLE ID_device/, read back; a re-import on another phone gives the same save (both parts)
        File es = save(new File(t, "exp"), "mine");
        write(new File(SaveStore.device(es), "dev.bin"), "device");
        SaveStore.Manifest want = SaveStore.scanParts(SaveStore.parts(es));
        File out = new File(t, "exp/Switch2");
        SaveZip.Exported ex = SaveZip.export(es, tid.toLowerCase(), out, "20261108-110000");
        check(ex.zip.getName().equals("swap2-save-" + tid + "-20261108-110000.zip") && ex.device && ex.files == want.files && ex.bytes == want.bytes, "exported: " + ex.zip.getName());
        check(!new File(ex.zip.getPath() + SaveZip.PARTIAL).exists() && SaveStore.scanParts(SaveStore.parts(es)).diff(want) == null, "no .partial left; the save only read");
        check(SaveZip.export(es, tid, out, "20261108-110000").zip.getName().endsWith("-110000-2.zip"), "a second export in the same second gets -2");
        check(SaveZip.found(tid, out, new File(t, "nothing")).size() == 2, "found: the exported zips of the title");
        List<SaveZip.Part> ep = SaveZip.plan(new SaveZip.Source(ex.zip), tid);
        check(ep.size() == 1 && ep.get(0).prefix.equals(tid) && (tid + SaveStore.DEVICE_SUFFIX).equals(ep.get(0).device), "the export's layout is the importer's");
        File other = save(new File(t, "phone2"), "theirs");
        write(new File(SaveStore.device(other), "theirs.bin"), "their device");
        SaveStore.Restored r3 = SaveZip.importZip(new SaveZip.Source(ex.zip), ep.get(0), other, new File(t, "phone2/bk"), "20261108-120000");
        check(r3.parts.contains(SaveStore.DEVICE) && SaveStore.scanParts(SaveStore.parts(other)).diff(want) == null, "re-imported: both parts as exported");
        try { SaveZip.export(new File(t, "nosave/saves/" + tid), tid, out, "x"); check(false, "export without a save"); } catch (SaveZip.Failure f) { check(f.why == SaveZip.Why.NO_SAVE, "no save to export"); }
        // the yuzu family's device save imported as the device save
        File zs = save(new File(t, "zimp"), "old");
        SaveStore.Restored rz = SaveZip.importZip(new SaveZip.Source(zd), zp.get(0), zs, new File(t, "zimp/bk"), "20261108-130000");
        check(rz.parts.contains(SaveStore.DEVICE) && text(new File(SaveStore.device(zs), "device.bin")).equals("device save") && text(new File(zs, "slot_00")).equals("user save"),
                "the all-zero user's save became the device save");
        // an empty device save folder (the host makes it when the game mounts it) is exported as it is, and read back
        File em = save(new File(t, "expempty"), "mine");
        SaveStore.device(em).mkdirs();
        File out2 = new File(t, "expempty/Switch2");
        write(new File(out2, "swap2-save-" + tid + "-20261108-090000.zip" + SaveZip.PARTIAL), "a stopped export's zip");
        write(new File(out2, "swap2-save-0100000000010000-20261108-090000.zip" + SaveZip.PARTIAL), "another game's");
        SaveZip.Exported ee = SaveZip.export(em, tid, out2, "20261108-140000");
        check(ee.device && ee.zip.isFile(), "exported with an empty device save");
        check(!new File(out2, "swap2-save-" + tid + "-20261108-090000.zip" + SaveZip.PARTIAL).exists()
                && new File(out2, "swap2-save-0100000000010000-20261108-090000.zip" + SaveZip.PARTIAL).exists(), "a stopped export's .partial of this game is removed, only");
        List<SaveZip.Part> eep = SaveZip.plan(new SaveZip.Source(ee.zip), tid);
        check(eep.size() == 1 && (tid + SaveStore.DEVICE_SUFFIX).equals(eep.get(0).device), "the empty device save read back");
        // the first difference's path alone (for the messages in the user's language)
        SaveStore.Manifest m1 = SaveStore.scan(em), m2 = SaveStore.scan(em);
        m2.entries.put("slot0.bin", "f 00 1");
        check(m1.diffAt(m2).equals("slot0.bin") && m1.diff(m2).equals("slot0.bin differs") && m1.diffAt(m1) == null, "diffAt: the path alone");
    }

    static File write2(File f, String s) throws IOException { write(f, s); return f; }

    static void profiles() {
        List<Profile> l = Profile.parse("040074A01BF12000\tDonkey Kong Bananza\t22852\tabcdef012345\t458752 main=aa sdk=BB;0 main=cc\nbad line\n"
                + "0400C3F00006E000\t\t0\tunknown\t");
        check(l.size() == 2, "two profiles, the bad line skipped");
        check(l.get(0).name.equals("Donkey Kong Bananza") && l.get(0).shaderTotal == 22852 && l.get(0).shaderInputs.equals("abcdef012345"), "the first profile's fields");
        check(l.get(1).name.equals("0400C3F00006E000"), "a profile without a name is named by its title ID");
        Map<Long, Map<String, String>> b = l.get(0).buildMap();
        check(b.size() == 2 && b.get(458752L).get("sdk").equals("bb") && b.get(0L).get("main").equals("cc"), "the builds, lower case");
        check(l.get(1).buildMap().isEmpty(), "no builds");
        // The versions a refused dump is told about (DumpCheck): version 0 is the base game itself, whose supported build needs no update (Mario Kart World 1.8.0)
        check(l.get(0).supported().equals("This app supports Donkey Kong Bananza (040074A01BF12000) as the base game (no update) or update 458752 only: dump the game with that update installed."),
                "supported, base and an update: " + l.get(0).supported());
        Profile mkw = Profile.parse("0400C3F00006E000\tMario Kart World\t11604\tabcdef012345\t0 main=d00e4f39").get(0);
        check(mkw.supported().equals("This app supports Mario Kart World (0400C3F00006E000) as the base game (no update) only: dump the game without an update."),
                "supported, the base only: " + mkw.supported());
        // Game resolution (build.gradle resolutionOf, the 10th column): the window size for a window_fn game, the graphics scale and operation mode for a graphics_scale one
        check(!l.get(0).hasResolution() && l.get(0).resolutionEnv("1920x1080").isEmpty(), "no column: no Game resolution");
        Profile win = Profile.parse("040074A01BF12000\tD\t0\tx\t\t\t\t\t\twindow").get(0);
        check(win.hasResolution() && win.resolutionEnv("1280x720").equals(List.of("DM_WINDOW_SIZE=1280x720"))
                && win.resolutionEnv("original").equals(List.of("DM_WINDOW_SIZE=original")), "window_fn: DM_WINDOW_SIZE as before: " + win.resolutionEnv("original"));
        Profile sc = Profile.parse("0400C3F00006E000\tM\t0\tx\t\t\t\t\t\tscale:1920x1080=0/handheld,1280x720=2/handheld").get(0);
        check(sc.hasResolution() && sc.resolutionEnv("1920x1080").equals(List.of("DM_GRAPHICS_SCALE=0", "DM_OPMODE=0"))
                && sc.resolutionEnv("1280x720").equals(List.of("DM_GRAPHICS_SCALE=2", "DM_OPMODE=0")), "graphics_scale rows: " + sc.resolutionEnv("1280x720"));
        check(sc.resolutionEnv("original").isEmpty() && sc.resolutionEnv("2560x1440").isEmpty(), "a choice without a row: the game's own");
        check(Profile.parse("0400C3F00006E000\tM\t0\tx\t\t\t\t\t\tscale:original=1/console").get(0).resolutionEnv("original").equals(List.of("DM_GRAPHICS_SCALE=1", "DM_OPMODE=1")), "console");
        check(Profile.versionName(0).equals("the base game") && Profile.versionName(458752).equals("update 458752"), "versionName");
        check(Profile.of("040074A01BF12000") != null && Profile.of("0100000000010000") == null, "Profile.of over BuildConfig.NX_PROFILES");
        check(Profile.missing("0100000000010000", "Mario").contains("has no game profile") && Profile.missing("040074A01BF12000", null) == null, "Profile.missing");
    }

    /** The Upscaler and Scene resolution options (build.gradle ndsrOf / sceneOf, the 11th and 12th columns; Profile.user's own reading of a folder) and SceneOverlay */
    static void upscalerScene(File t) throws Exception {
        String expect = "0.75,0.71112,0.66667,0.62223,0.58334,0.53334,0.5,0.4445,0.37223,0.33334";
        Profile z = Profile.parse("0400486024DEC000\tZ\t0\tx\t\t\t\t\t\t\tsqrt\t0.6135/" + expect).get(0);
        check(z.hasNdsr() && z.ndsrEnv("fsr").equals(List.of("DM_VK_NDSR_INPUT=sqrt", "DM_VK_NDSR=fsr")) && z.ndsrEnv("net").equals(List.of("DM_VK_NDSR_INPUT=sqrt")),
                "Upscaler: FSR with the profile's input, the input alone for the network: " + z.ndsrEnv("fsr"));
        check(z.hasScene() && z.sceneScale().equals("0.6135") && z.sceneExpect().equals(expect), "Scene resolution: the scale and the originals");
        check(z.ndsrDefault().equals("net") && Profile.parse("0400486024DEC000\tZ\t0\tx\t\t\t\t\t\t\tsqrt\t\tfsr").get(0).ndsrDefault().equals("fsr")
                && Profile.parse("040074A01BF12000\tD\t0\tx\t\t\t\t\t\t\t\t\tfsr").get(0).ndsrDefault().equals("net"), "Upscaler default: ndsr_default fsr, only with the networks");
        Profile none = Profile.parse("040074A01BF12000\tD\t0\tx\t\t\t\t\t\twindow").get(0);
        check(!none.hasNdsr() && none.ndsrEnv("fsr").isEmpty() && !none.hasScene() && none.sceneScale() == null, "no columns: neither option");
        Profile bad = Profile.parse("040074A01BF12000\tD\t0\tx\t\t\t\t\t\t\tcubic\t7/x,y").get(0);
        check(!bad.hasNdsr() && !bad.hasScene() && Profile.parse("040074A01BF12000\tD\t0\tx\t\t\t\t\t\t\tlinear\t0.5").get(0).sceneExpect().isEmpty(), "malformed columns: not offered");
        // A profile folder (Profile.user): the networks from its shader map, ndsr_input and scene_scale_palette from game.tsv; linear without ndsr_input
        write(new File(t, "profiles/0400486024DEC000/game.tsv"), "name\tZ\nndsr_input\tsqrt\nndsr_default\tfsr\nscene_scale_palette\t0.6135\t" + expect + "\n");
        write(new File(t, "profiles/0400486024DEC000/shader_map.tsv"), "cs_other.bin\t165\tcompute\tfa3033d05c0a41d6\t/Lib/agl/agl_resource.Nin_Ounce_NVN2.release.sarc.zs/agl_ndsr_vr_light.pck#NDSR@0x84910\n");
        write(new File(t, "profiles/0400C3F00006E000/game.tsv"), "name\tM\n");
        write(new File(t, "profiles/0400C3F00006E000/shader_map.tsv"), "vs.bin\t1\tvertex\t00\t/Lib/agl/agl_resource.Nin_Ounce_NVN2.release.sarc.zs/agl_ndsr.pck#NDSR@0x10\n");
        write(new File(t, "profiles/040074A01BF12000/game.tsv"), "name\tD\n");
        List<Profile> u = Profile.user(new File(t, "profiles"));
        check(u.size() == 3 && u.get(1).titleId.equals("040074A01BF12000") && !u.get(1).hasNdsr() && !u.get(1).hasScene(), "a folder without the networks: neither option");
        check(u.get(0).hasNdsr() && u.get(0).ndsrDefault().equals("fsr") && !u.get(2).ndsrDefault().equals("fsr") && u.get(0).ndsrEnv("fsr").get(0).equals("DM_VK_NDSR_INPUT=sqrt") && u.get(0).sceneScale().equals("0.6135") && u.get(0).sceneExpect().equals(expect),
                "a folder with both: " + u.get(0).ndsr + " " + u.get(0).scene);
        check(u.get(2).hasNdsr() && u.get(2).ndsrEnv("fsr").get(0).equals("DM_VK_NDSR_INPUT=linear") && !u.get(2).hasScene(), "the networks without ndsr_input: linear");
        // SceneOverlay: current only with files in the folder and the same stamp
        File files = new File(t, "files");
        check(!SceneOverlay.current(files, "0400486024DEC000", "0.6135", expect, "131072"), "no overlay yet");
        write(new File(SceneOverlay.dir(files, "0400486024DEC000"), "Pack/Bootup.Nin_Ounce_NVN2.pack.zs"), "x");
        check(!SceneOverlay.current(files, "0400486024DEC000", "0.6135", expect, "131072"), "no stamp: not taken");
        write(SceneOverlay.stamp(files, "0400486024DEC000"), SceneOverlay.stampText("0.6135", expect, "131072"));
        check(SceneOverlay.current(files, "0400486024DEC000", "0.6135", expect, "131072"), "made from these inputs");
        check(!SceneOverlay.current(files, "0400486024DEC000", "0.6135", expect, "196608") && !SceneOverlay.current(files, "0400486024DEC000", "0.625", expect, "131072"),
                "another version or scale: made again");
        check(String.join(" ", SceneOverlay.argv("/g.nup:update/131072/romfs", "0.6135", "", new File("o"))).equals("--romfs /g.nup:update/131072/romfs --scale 0.6135 --out o")
                && SceneOverlay.argv("r", "0.6135", expect, new File("/o")).length == 8, "the tool's arguments");
        check("gsys_dynres: no .bgyml file".equals(SceneOverlay.why(List.of("== head", "reading", "gsys_dynres: no .bgyml file", ""))), "why: the tool's error line");
        check("ValueError: bad".equals(SceneOverlay.why(List.of("Traceback (most recent call last):", "  File x", "ValueError: bad"))), "why: an exception's last line");
        check(SceneOverlay.why(List.of("== head")) == null, "why: nothing");
    }

    static void backup(File t) throws Exception {
        File s = save(t, "v1"), bk = new File(t, "save-backups/040074A01BF12000");
        SaveStore.Manifest before = SaveStore.scan(s);
        SaveStore.Backup b = SaveStore.backup(s, bk, "20261103-140000");
        check(b.dir.equals(new File(bk, "20261103-140000")) && b.files == 2 && !b.device, "the backup's folder and file count, no device save");
        check(SaveStore.scan(new File(b.dir, "main")).diff(before) == null, "the backup holds the save in main/");
        check(SaveStore.scan(s).diff(before) == null, "the save is untouched");
        check(new File(bk, "20261103-140000" + SaveStore.MANIFEST).isFile() && new File(b.dir, "main/empty").isDirectory(), "the manifest beside it; empty folders kept");
        SaveStore.Backup b2 = SaveStore.backup(s, bk, "20261103-140000");
        check(b2.name.equals("20261103-140000-2"), "a second backup in the same second gets -2");
        new File(bk, SaveStore.PARTIAL + "20261103-150000").mkdirs();   // a backup stopped while it copied (fresh: kept)
        new File(bk, "loose").mkdirs();                                 // a folder without a manifest
        List<SaveStore.Backup> l = SaveStore.list(bk);
        check(l.size() == 2 && l.get(0).name.equals("20261103-140000-2"), "list: the two backups, newest first, nothing else");
        check(l.get(0).source.equals(s.getAbsolutePath()) && l.get(0).bytes == before.bytes, "list: source and size from the manifest");
        try { SaveStore.backup(s, new File(s, "inside"), "x"); check(false, "a backups folder inside the save is refused"); } catch (IOException e) { n++; }
        try { SaveStore.backup(new File(t, "nothing"), bk, "x"); check(false, "no save folder is refused"); } catch (IOException e) { n++; }
    }

    static void restore(File t) throws Exception {
        File s = save(t, "old"), bk = new File(t, "save-backups/040074A01BF12000");
        write(new File(s, "extra.bin"), "only in the old save");
        SaveStore.Manifest old = SaveStore.scan(s);
        File other = save(new File(t, "other"), "new");
        new File(other, "empty").delete();
        write(new File(other, "device-ish/settings.bin"), "settings");
        SaveStore.Backup b = SaveStore.backup(other, bk, "20261101-090000");
        SaveStore.Manifest want = SaveStore.scan(other);
        SaveStore.Restored r = SaveStore.restore(b.dir, s, bk, "20261103-160000");
        check(SaveStore.scan(s).diff(want) == null, "the save is the backup's");
        check(!new File(s, "extra.bin").exists() && !new File(s, "empty").exists(), "what the backup lacks is gone");
        check(r.before != null && r.before.name.equals("20261103-160000" + SaveStore.BEFORE_RESTORE), "the automatic backup first");
        check(SaveStore.scan(new File(r.before.dir, "main")).diff(old) == null, "the automatic backup holds the old save");
        check(!SaveStore.pending(s) && !new File(s.getPath() + SaveStore.RESTORE_SUFFIX).exists(), "no marker, set file or copy left");
        // import from a folder without a manifest, into a save folder that does not exist yet: no automatic backup (nothing to keep)
        File fresh = new File(t, "saves/0400C3F00006E000");
        SaveStore.Restored r2 = SaveStore.restore(other, fresh, new File(t, "save-backups/0400C3F00006E000"), "20261103-170000");
        check(r2.before == null && SaveStore.scan(fresh).diff(SaveStore.scan(other)) == null, "import into a new save folder");
        try { SaveStore.restore(new File(s, "common"), s, bk, "x"); check(false, "a source inside the save is refused"); } catch (IOException e) { n++; }
    }

    /** A game with a device save (<DM_SAVE>_device, hle_fs.c): one backup holds both, a restore swaps both */
    static void device(File t) throws Exception {
        File s = save(t, "a"), d = SaveStore.device(s), bk = new File(t, "save-backups/040074A01BF12000");
        write(new File(d, "island.dat"), "device a");
        SaveStore.Backup b = SaveStore.backup(s, bk, "20261103-100000");
        check(b.device && new File(b.dir, "device/island.dat").isFile() && new File(b.dir, "main/slot0.bin").isFile(), "the backup holds main/ and device/");
        SaveStore.Manifest wantMain = SaveStore.scan(s), wantDev = SaveStore.scan(d);
        write(new File(s, "slot0.bin"), "slot0 b");
        write(new File(d, "island.dat"), "device b");
        write(new File(d, "new.dat"), "only in b");
        SaveStore.Restored r = SaveStore.restore(b.dir, s, bk, "20261103-110000");
        check(r.parts.contains(SaveStore.DEVICE) && SaveStore.scan(s).diff(wantMain) == null && SaveStore.scan(d).diff(wantDev) == null, "both parts restored");
        check(r.before.device && new File(r.before.dir, "device/new.dat").isFile(), "the automatic backup holds the device save too");
        check(!new File(d.getPath() + SaveStore.RESTORE_SUFFIX).exists() && !SaveStore.pending(s), "nothing left beside the device save");
        // stopped after the set file, before the device part got its marker: recover gives it one and finishes both
        write(new File(s, "slot0.bin"), "slot0 c");
        write(new File(d, "island.dat"), "device c");
        File am = new File(s.getPath() + SaveStore.RESTORE_SUFFIX), ad = new File(d.getPath() + SaveStore.RESTORE_SUFFIX);
        SaveStore.copyTree(new File(b.dir, "main"), am);
        SaveStore.copyTree(new File(b.dir, "device"), ad);
        write(SaveStore.setFile(s), s.getAbsolutePath() + "\t" + am.getAbsolutePath() + "\n" + d.getAbsolutePath() + "\t" + ad.getAbsolutePath() + "\n");
        write(SaveStore.marker(s, 1), am.getAbsolutePath());
        check(SaveStore.recover(s), "recover finds the set file");
        check(SaveStore.scan(s).diff(wantMain) == null && SaveStore.scan(d).diff(wantDev) == null && !SaveStore.pending(s) && !am.exists() && !ad.exists(), "both parts finished");
        // a set file naming another folder is refused
        write(SaveStore.setFile(s), new File(t, "elsewhere").getAbsolutePath() + "\t" + am.getAbsolutePath() + "\n");
        try { SaveStore.recover(s); check(false, "a set file naming another folder is refused"); } catch (IOException e) { n++; }
        SaveStore.setFile(s).delete();
    }

    static void damaged(File t) throws Exception {
        File s = save(t, "cur"), bk = new File(t, "save-backups/040074A01BF12000");
        SaveStore.Backup b = SaveStore.backup(s, bk, "20261101-000000");
        write(new File(b.dir, "main/slot0.bin"), "bit rot");
        write(new File(s, "slot0.bin"), "progress since");
        SaveStore.Manifest cur = SaveStore.scan(s);
        try { SaveStore.restore(b.dir, s, bk, "20261103-180000"); check(false, "a damaged backup is refused"); } catch (IOException e) { check(e.getMessage().contains("damaged"), "says damaged"); }
        check(SaveStore.scan(s).diff(cur) == null, "the save is untouched");
        check(SaveStore.list(bk).size() == 1, "no automatic backup was made for a refused restore");
    }

    static void crash(File t) throws Exception {
        // stopped after the marker, before stage 1: recover finishes it
        File s = save(t, "old");
        write(new File(s, "stale.bin"), "stale");
        File a = new File(s.getPath() + SaveStore.RESTORE_SUFFIX);
        write(new File(a, "slot0.bin"), "slot0 new");
        write(new File(a, "x/x.bin"), "x");
        SaveStore.Manifest want = SaveStore.scan(a);
        write(SaveStore.marker(s, 1), a.getAbsolutePath());
        check(SaveStore.recover(s), "recover finds the marker");
        check(SaveStore.scan(s).diff(want) == null && !SaveStore.pending(s) && !a.exists(), "the swap was finished");
        check(!SaveStore.recover(s), "nothing left to recover");
        // stopped in stage 2 of a host commit (b.new): pend2 there, some files moved already
        File nw = new File(s.getPath() + ".new");
        write(new File(nw, "slot0.bin"), "slot0 newer");
        write(new File(nw, "common.bin"), "common newer");
        want = SaveStore.scan(nw);
        SaveStore.deleteTree(new File(s, "x"));
        write(SaveStore.marker(s, 2), nw.getAbsolutePath());
        check(new File(nw, "common.bin").renameTo(new File(s, "common.bin")), "a file moved before the stop");
        SaveStore.recover(s);
        check(SaveStore.scan(s).diff(want) == null && !SaveStore.pending(s), "stage 2 finished");
    }

    /** The journal's rules (the same as plat_swap_recover's): which markers run, which are refused */
    static void markers(File t) throws Exception {
        File s = save(t, "cur"), foreign = new File(t, "foreign");
        write(new File(foreign, "keep.bin"), "not a save");
        SaveStore.Manifest cur = SaveStore.scan(s), fk = SaveStore.scan(foreign);
        // a marker naming anything but <save>.new / .re / .restore
        write(SaveStore.marker(s, 1), foreign.getAbsolutePath());
        try { SaveStore.recover(s); check(false, "a marker naming a foreign folder is refused"); } catch (IOException e) { n++; }
        check(SaveStore.scan(s).diff(cur) == null && SaveStore.scan(foreign).diff(fk) == null, "the save and the foreign folder are untouched");
        write(SaveStore.marker(s, 1), new File(foreign, s.getName() + ".new").getAbsolutePath());   // the right name in another folder
        try { SaveStore.recover(s); check(false, "a sibling's name in another folder is refused"); } catch (IOException e) { n++; }
        // .pend1 whose folder is gone
        write(SaveStore.marker(s, 1), new File(s.getPath() + ".new").getAbsolutePath());
        try { SaveStore.recover(s); check(false, ".pend1 with its folder gone is refused"); } catch (IOException e) { n++; }
        check(SaveStore.scan(s).diff(cur) == null, "and the save is untouched");
        try { SaveStore.backup(s, new File(t, "bk"), "x"); check(false, "no backup while the journal cannot be finished"); } catch (IOException e) { n++; }
        // an empty .pend2 is dropped and .pend1 is still looked at
        File a = new File(s.getPath() + SaveStore.RESTORE_SUFFIX);
        write(new File(a, "only.bin"), "only");
        SaveStore.Manifest want = SaveStore.scan(a);
        write(SaveStore.marker(s, 1), a.getAbsolutePath());
        write(SaveStore.marker(s, 2), "");
        check(SaveStore.recover(s) && SaveStore.scan(s).diff(want) == null && !SaveStore.pending(s), "empty .pend2 dropped, .pend1 finished");
        // .pend2 with its folder gone: stage 2 has nothing left to move, the markers go
        write(SaveStore.marker(s, 2), a.getAbsolutePath());
        check(SaveStore.recover(s) && !SaveStore.pending(s) && SaveStore.scan(s).diff(want) == null, ".pend2 with its folder gone is finished");
        // a legacy <save>.old with no save: it comes back (the host's rule), and then backs up like any save
        File s2 = new File(t, "saves2/0100000000010000"), old = new File(s2.getPath() + ".old");
        write(new File(old, "slot.bin"), "legacy");
        SaveStore.Backup b = SaveStore.backup(s2, new File(t, "bk2"), "20261103-120000");
        check(new File(s2, "slot.bin").isFile() && !old.exists() && new File(b.dir, "main/slot.bin").isFile(), "<save>.old with no save came back and was backed up");
        write(new File(old, "slot.bin"), "stale old");
        SaveStore.recover(s2);
        check(!old.exists() && SaveStore.sha256(new File(s2, "slot.bin")).equals(SaveStore.sha256(new File(b.dir, "main/slot.bin"))), "<save>.old beside a save goes");
    }

    /** Within one process the lock is taken once */
    static void lockSameProcess(File t) throws Exception {
        File s = save(t, "x");
        try (SaveStore.Lock l = SaveStore.lock(s)) {
            check(SaveStore.inUse(s), "inUse while held");
            try { SaveStore.backup(s, new File(t, "bk"), "x"); check(false, "a backup while the lock is held is refused"); } catch (IOException e) { check(e.getMessage().contains("in use"), "says in use"); }
        }
        check(!SaveStore.inUse(s), "free after close");
        SaveStore.backup(s, new File(t, "bk"), "20261103-130000");
        n++;
    }

    /** Another process holds the lock (dm/tools/tests/test_android_saves.py runs "hold" first) */
    static void locked(File s) throws Exception {
        int k = 0;
        try { SaveStore.backup(s, new File(s.getParentFile(), "bk-locked"), "x"); } catch (IOException e) { if (e.getMessage().contains("in use")) k++; }
        try { SaveStore.restore(new File(s.getParentFile(), "src"), s, new File(s.getParentFile(), "bk-locked"), "x"); } catch (IOException e) { if (e.getMessage().contains("in use")) k++; }
        try { SaveStore.recover(s); } catch (IOException e) { if (e.getMessage().contains("in use")) k++; }
        System.out.println("refused " + k + (SaveStore.inUse(s) ? " inUse" : ""));
    }

    /** The re-review's cases: the crash between .pend2 and .pend1's delete, the set phase's empty marker, a restore that would mix device saves, a .partial finished */
    static void review3(File t) throws Exception {
        // both markers (a stop after .pend2 was written, before .pend1 went): .pend1 goes first, then stage 2
        File s = save(t, "old"), a = new File(s.getPath() + ".new");
        write(new File(a, "slot0.bin"), "new");
        SaveStore.Manifest want = SaveStore.scan(a);
        SaveStore.deleteTree(new File(s, "common"));
        SaveStore.deleteTree(new File(s, "empty"));   // stage 1 had run: what a lacks is gone
        write(SaveStore.marker(s, 1), a.getAbsolutePath());
        write(SaveStore.marker(s, 2), a.getAbsolutePath());
        check(SaveStore.recover(s) && SaveStore.scan(s).diff(want) == null && !SaveStore.pending(s) && !a.exists(), "both markers: finished from .pend2");
        // the state an older recovery left by stopping after its stage 2 and before deleting .pend1: .pend1 naming an a of empty folders. Stage 1 would empty the save
        write(new File(s, "more.bin"), "more");
        want = SaveStore.scan(s);
        new File(a, "x/y").mkdirs();
        write(SaveStore.marker(s, 1), a.getAbsolutePath());
        check(SaveStore.recover(s) && SaveStore.scan(s).diff(want) == null && !SaveStore.pending(s) && !a.exists(), ".pend1 naming an emptied copy: the save kept, the marker gone");
        // the set phase: the set file there, main's .pend1 written but empty, the device part without one
        File s2 = save(new File(t, "set"), "old"), d2 = SaveStore.device(s2);
        write(new File(d2, "dev.bin"), "dev old");
        File am = new File(s2.getPath() + SaveStore.RESTORE_SUFFIX), ad = new File(d2.getPath() + SaveStore.RESTORE_SUFFIX);
        write(new File(am, "slot0.bin"), "main new");
        write(new File(ad, "dev.bin"), "dev new");
        SaveStore.Manifest wm = SaveStore.scan(am), wd = SaveStore.scan(ad);
        write(SaveStore.setFile(s2), s2.getAbsolutePath() + "\t" + am.getAbsolutePath() + "\n" + d2.getAbsolutePath() + "\t" + ad.getAbsolutePath() + "\n");
        write(SaveStore.marker(s2, 1), "");
        check(SaveStore.recover(s2) && SaveStore.scan(s2).diff(wm) == null && SaveStore.scan(d2).diff(wd) == null && !SaveStore.pending(s2), "set phase with an empty .pend1: both parts restored");
        // a backup without a device save into a save that has one: refused
        File s3 = save(new File(t, "mix"), "cur"), bk = new File(t, "mix/bk");
        SaveStore.Backup noDev = SaveStore.backup(s3, bk, "20261101-000000");
        write(new File(SaveStore.device(s3), "dev.bin"), "dev");
        SaveStore.Manifest cur = SaveStore.scanParts(SaveStore.parts(s3));
        try { SaveStore.restore(noDev.dir, s3, bk, "20261103-000000"); check(false, "a restore that would mix device saves is refused"); } catch (IOException e) { check(e.getMessage().contains("device save"), "says device save"); }
        check(SaveStore.scanParts(SaveStore.parts(s3)).diff(cur) == null, "and nothing changed");
        // a .partial whose manifest is beside it (stopped before the rename) gets its name; one without goes
        SaveStore.Backup b = SaveStore.backup(s3, bk, "20250101-000000");
        File partial = new File(bk, SaveStore.PARTIAL + b.name);
        check(b.dir.renameTo(partial), "made a stopped rename");
        File broken = new File(bk, SaveStore.PARTIAL + "20250102-000000");
        write(new File(broken, "main/x"), "x");
        long old = System.currentTimeMillis() - 2 * SaveStore.STALE_MS;
        partial.setLastModified(old); broken.setLastModified(old);
        SaveStore.cleanStale(bk, System.currentTimeMillis());
        check(b.dir.isDirectory() && !partial.exists() && !broken.exists() && SaveStore.list(bk).stream().anyMatch(x -> x.name.equals(b.name)), "the verified .partial finished, the other removed");
    }

    static void edges(File t) throws Exception {
        File s = save(t, "cur"), bk = new File(t, "save-backups/040074A01BF12000");
        File a = new File(s.getPath() + SaveStore.RESTORE_SUFFIX);
        write(new File(a, "x.bin"), "x");
        try { SaveStore.restore(a, s, bk, "x"); check(false, "import from <save>.restore is refused"); } catch (IOException e) { n++; }
        try { SaveStore.restore(new File(s.getPath() + ".work"), s, bk, "x"); check(false, "import from <save>.work is refused"); } catch (IOException e) { n++; }
        // a path through a link to the save is the save (canonical paths)
        File link = new File(t, "link");
        Files.createSymbolicLink(link.toPath(), s.getParentFile().toPath());
        check(SaveStore.inside(new File(link, s.getName() + "/common"), s), "inside() by canonical paths");
        check(SaveStore.refuseSource(new File(link, s.getName()), s) != null, "the save through a link is refused as a source");
        // stale leftovers: old .partial-* and orphan manifests go, a finished backup (however old) and fresh leftovers stay
        SaveStore.Backup b = SaveStore.backup(s, bk, "20250101-000000");
        File partial = new File(bk, SaveStore.PARTIAL + "20250102-000000"), orphan = new File(bk, "20250103-000000" + SaveStore.MANIFEST), fresh = new File(bk, SaveStore.PARTIAL + "now");
        write(new File(partial, "main/x"), "x");
        write(orphan, "# nxnative save backup 1\n");
        fresh.mkdirs();
        long old = System.currentTimeMillis() - 2 * SaveStore.STALE_MS;
        for (File f : new File[] {partial, orphan, b.dir, new File(bk, b.name + SaveStore.MANIFEST)}) f.setLastModified(old);
        List<File> gone = SaveStore.cleanStale(bk, System.currentTimeMillis());
        check(gone.size() == 2 && !partial.exists() && !orphan.exists(), "stale .partial and orphan manifest removed");
        check(b.dir.isDirectory() && new File(bk, b.name + SaveStore.MANIFEST).isFile() && fresh.isDirectory(), "the finished backup and fresh leftovers stay");
        // the post-restore comparison ignores case (shared storage keeps a file's old case when a rename only changes it)
        SaveStore.Manifest x = new SaveStore.Manifest(), y = new SaveStore.Manifest();
        x.entries.put("Slot.bin", "f aa 1");
        y.entries.put("slot.bin", "f aa 1");
        check(x.diff(y) != null && x.diff(y, true) == null, "case-insensitive comparison");
    }

    /** Everything under a folder (path → hash, size and time, "d" for a folder), lock files left out: the old save's folder before and after */
    static Map<String, String> snapshot(File root) throws IOException {
        Map<String, String> m = new java.util.TreeMap<>();
        if (!root.exists()) return m;
        try (java.util.stream.Stream<java.nio.file.Path> w = Files.walk(root.toPath())) {
            for (java.nio.file.Path p : (Iterable<java.nio.file.Path>) w::iterator) {
                if (p.toString().endsWith(SaveStore.LOCK_SUFFIX)) continue;
                m.put(root.toPath().relativize(p).toString(), Files.isDirectory(p) ? "d" : SaveStore.sha256(p.toFile()) + " " + Files.size(p) + " " + Files.getLastModifiedTime(p));
            }
        }
        return m;
    }

    static String text(File f) throws IOException { return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8); }

    static void migrate(File t) throws Exception {
        // the old default beside the game (<Switch2>/saves/<id>, with its device save) and the app's save (Android/data/<pkg>/files/saves/<id>)
        File old = save(new File(t, "Switch2"), "old"), app = new File(t, "appdata/saves/040074A01BF12000");
        write(new File(SaveStore.device(old), "dev.bin"), "device old");
        File oldRoot = old.getParentFile();
        Map<String, String> before = snapshot(oldRoot);
        check(SaveMigrate.needed(old, app), "needed: the app save is empty, the old one has a save");
        SaveMigrate.Result r = SaveMigrate.migrate(old, app);
        check(r.state == SaveMigrate.State.COPIED, "copied: " + r);
        check(SaveStore.scanParts(SaveStore.parts(app)).diff(SaveStore.scanParts(SaveStore.parts(old))) == null, "the app save (main and device) is the old one, file by file");
        check(new File(app, "empty").isDirectory() && r.copied.files == 3, "empty folders kept; three files copied");
        check(snapshot(oldRoot).equals(before), "the old folder is untouched (files, sizes, hashes, times)");
        check(!SaveMigrate.staging(app).exists(), "no staging folder left");
        check(!SaveMigrate.needed(old, app), "not needed again");
        // never over a save: the app's own save stays as it is, however the old one changes
        write(new File(app, "slot0.bin"), "slot0 played in the app");
        write(new File(old, "slot0.bin"), "slot0 played by an older version");
        before = snapshot(oldRoot);
        Map<String, String> appBefore = snapshot(app.getParentFile());
        r = SaveMigrate.migrate(old, app);
        check(r.state == SaveMigrate.State.APP_HAS_SAVE, "a non-empty app save is never copied over: " + r);
        check(snapshot(app.getParentFile()).equals(appBefore) && snapshot(oldRoot).equals(before), "neither save changed");

        // an app save with only empty folders (the host made them) takes the copy
        File t2 = new File(t, "emptyapp"), old2 = save(new File(t2, "Switch2"), "two"), app2 = new File(t2, "appdata/saves/040074A01BF12000");
        new File(app2, "sub/deeper").mkdirs();
        r = SaveMigrate.migrate(old2, app2);
        check(r.state == SaveMigrate.State.COPIED && SaveStore.scan(app2).diff(SaveStore.scan(old2)) == null, "empty folders only: copied, " + r);
        check(!SaveStore.device(app2).exists(), "no device save made when the old one has none");
        // no old save: nothing
        File t3 = new File(t, "none"), old3 = new File(t3, "Switch2/saves/040074A01BF12000"), app3 = new File(t3, "appdata/saves/040074A01BF12000");
        old3.mkdirs();
        r = SaveMigrate.migrate(old3, app3);
        check(r.state == SaveMigrate.State.NO_OLD_SAVE && !app3.exists(), "no old save: nothing copied, " + r);

        // an old save with an unfinished commit: not copied (the host finishes it in the old folder this start), the old folder untouched
        File t4 = new File(t, "pending"), old4 = save(new File(t4, "Switch2"), "four"), app4 = new File(t4, "appdata/saves/040074A01BF12000");
        write(new File(old4.getPath() + ".new/slot0.bin"), "newer");
        write(SaveStore.marker(old4, 2), old4.getPath() + ".new");
        before = snapshot(old4.getParentFile());
        r = SaveMigrate.migrate(old4, app4);
        check(r.state == SaveMigrate.State.FAILED && r.message.contains("unfinished"), "an old save with a journal is not copied: " + r);
        check(!SaveMigrate.hasSave(app4) && snapshot(old4.getParentFile()).equals(before), "nothing in the app, the old folder untouched");

        // a copy that fails part way leaves no save to play from, and the next start copies it whole
        File t5 = new File(t, "fail"), old5 = save(new File(t5, "Switch2"), "five"), app5 = new File(t5, "appdata/saves/040074A01BF12000");
        write(new File(SaveStore.device(old5), "dev.bin"), "device five");
        before = snapshot(old5.getParentFile());
        new File(app5, "stuck").mkdirs();
        check(app5.setWritable(false), "set up: a folder that cannot be cleared");   // the move of the main save fails after the device save went in
        r = SaveMigrate.migrate(old5, app5);
        app5.setWritable(true);
        check(r.state == SaveMigrate.State.FAILED, "the failed move is reported: " + r);
        check(SaveStore.hasFiles(SaveStore.device(app5)), "set up: the failure came after the device save went in");
        check(!SaveStore.hasFiles(app5) && SaveMigrate.needed(old5, app5), "no main save in the app: the old folder is played, and the copy is needed still");
        check(!SaveMigrate.staging(app5).exists() && snapshot(old5.getParentFile()).equals(before), "no staging left; the old folder untouched");
        r = SaveMigrate.migrate(old5, app5);
        check(r.state == SaveMigrate.State.COPIED && SaveStore.scanParts(SaveStore.parts(app5)).diff(SaveStore.scanParts(SaveStore.parts(old5))) == null,
                "the next start copies it whole (the device save left in the app was the old one's copy): " + r);
        // a device save in the app that is not the old one's copy: not played as half a save
        File t6 = new File(t, "foreigndevice"), old6 = save(new File(t6, "Switch2"), "six"), app6 = new File(t6, "appdata/saves/040074A01BF12000");
        write(new File(SaveStore.device(old6), "dev.bin"), "device six");
        write(new File(SaveStore.device(app6), "dev.bin"), "another device save");
        r = SaveMigrate.migrate(old6, app6);
        check(r.state == SaveMigrate.State.FAILED && !SaveStore.hasFiles(app6) && text(new File(SaveStore.device(app6), "dev.bin")).equals("another device save"),
                "a foreign device save: refused, kept, nothing copied: " + r);
        // the old save in use (a backup of it works in this process): refused, nothing copied
        File t7 = new File(t, "locked"), old7 = save(new File(t7, "Switch2"), "seven"), app7 = new File(t7, "appdata/saves/040074A01BF12000");
        try (SaveStore.Lock l = SaveStore.lock(old7)) {
            r = SaveMigrate.migrate(old7, app7);
        }
        check(r.state == SaveMigrate.State.FAILED && !SaveMigrate.hasSave(app7), "the old save in use: not copied, " + r);
    }
}
