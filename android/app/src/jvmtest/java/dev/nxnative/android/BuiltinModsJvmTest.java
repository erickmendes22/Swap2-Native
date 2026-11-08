package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * BuiltinMods on a synthetic asset folder (no real game's patch): finding the shipped mods, the switch on (copied in whole), off ('-'), on again (the files
 * brought up to the assets'), and the default applied once. Run by dm/tools/tests/test_profile_mods.py: java BuiltinModsJvmTest &lt;empty work folder&gt;
 */
public final class BuiltinModsJvmTest {
    static final String TITLE = "0400000000ABC000", BID = "0123456789abcdef0011223344556677";

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
    }

    static void write(File f, String s) throws IOException {
        File d = f.getParentFile();
        if (!d.isDirectory() && !d.mkdirs()) throw new IOException("cannot create " + d);
        Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8));
    }

    static String patch(String bytes) { return "@nsobid-" + BID + "\n@flag offset_shift 0x100\n@enabled\n00001000 " + bytes + "\n"; }

    public static void main(String[] args) throws IOException {
        File work = new File(args[0]), assets = new File(work, "assets"), root = new File(work, "Mods");
        File t = new File(assets, "mods/" + TITLE);
        write(new File(t, "plain/mod.tsv"), "# comment\nlabel\ts2_x\nnote\ts2_x_note\nandroid_default\toff\n");
        write(new File(t, "plain/exefs/plain.pchtxt"), patch("09000014"));
        write(new File(t, "auto/mod.tsv"), "label\ts2_y\nandroid_default\ton\n");
        write(new File(t, "auto/exefs/auto.pchtxt"), patch("1f2003d5"));
        write(new File(t, "empty/mod.tsv"), "label\ts2_z\n");   // no patch file: not offered
        BuiltinMods.Source src = BuiltinMods.folder(assets);

        List<BuiltinMods.Builtin> l = BuiltinMods.of(src, TITLE);
        check(l.size() == 2 && l.get(0).folder.equals("auto") && l.get(1).folder.equals("plain"), "of: " + l.size());
        BuiltinMods.Builtin plain = l.get(1), auto = l.get(0);
        check(plain.label.equals("s2_x") && plain.note.equals("s2_x_note") && !plain.defaultOn && auto.defaultOn, "mod.tsv");
        check(BuiltinMods.of(src, "0400000000DEF000").isEmpty(), "another title has none");

        check(!BuiltinMods.isOn(root, plain) && BuiltinMods.set(root, plain, false, src) == null, "off and not there");
        BuiltinMods.set(root, plain, true, src);
        check(BuiltinMods.isOn(root, plain), "on");
        check(ExefsMods.find(root, TITLE, BID).size() == 1, "the rewrite finds it");
        String[] left = root.list((d, n) -> n.startsWith(ExefsMods.STAGING));
        check(left != null && left.length == 0, "no staging folder left");
        BuiltinMods.set(root, plain, false, src);
        check(!BuiltinMods.isOn(root, plain) && new File(root, TITLE + "/-plain/exefs/plain.pchtxt").isFile(), "off: -plain");
        check(ExefsMods.find(root, TITLE, BID).isEmpty(), "off: the rewrite skips it");
        write(new File(t, "plain/exefs/plain.pchtxt"), patch("0a000014"));   // an APK update's new bytes
        BuiltinMods.set(root, plain, true, src);
        check(BuiltinMods.isOn(root, plain), "on again");
        String now = new String(Files.readAllBytes(new File(root, TITLE + "/plain/exefs/plain.pchtxt").toPath()), StandardCharsets.UTF_8);
        check(now.contains("0a000014"), "on again: the assets' bytes");

        List<String> decided = new ArrayList<>(BuiltinMods.applyDefaults(root, TITLE, src, new ArrayList<>()));
        check(decided.size() == 1 && decided.get(0).equals(auto.decidedKey()) && BuiltinMods.isOn(root, auto), "default on: installed once");
        BuiltinMods.set(root, auto, false, src);
        ExefsMods.Mod m = BuiltinMods.installed(root, auto);
        ExefsMods.remove(root, TITLE, m);
        check(BuiltinMods.applyDefaults(root, TITLE, src, decided).isEmpty() && BuiltinMods.installed(root, auto) == null, "a decided default is never put back");
        System.out.println("BuiltinModsJvmTest: ok");
    }
}
