package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * Switch2Layout on the JVM, driven by dm/tools/tests/test_android_switch2_layout.py: argument a temporary folder. The one-time move of the Switch2 folder
 * (games into Games/, &lt;id&gt;-work into Work/&lt;ID&gt;, mods/ into Mods/), what it leaves alone (app data, unknown files and folders, a title whose job runs,
 * an entry whose target exists), a failed rename, a second run, an interrupted one finished from move.log, and the repointing of saved paths and job.json.
 * Prints "ok &lt;checks&gt;" or throws.
 */
public final class Switch2LayoutJvmTest {
    private static int checks;
    private static final String MKW = "0400C3F00006E000", DKB = "040074A01BF12000", OOT = "0400486024DEC000", POKO = "0400A3A01EE4C000";

    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        checks++;
    }

    /** A game the test's identify knows: a folder with TITLE, or a .nup holding its title ID */
    private static File game(File dir, String id) throws IOException {
        dir.mkdirs();
        write(new File(dir, "TITLE"), id);
        write(new File(dir, "base/exefs/main.npdm"), "npdm");
        return dir;
    }

    private static File nup(File f, String id) throws IOException { write(f, id); return f; }

    private static void write(File f, String s) throws IOException {
        f.getParentFile().mkdirs();
        Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8));
    }

    private static String read(File f) throws IOException { return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8); }

    private static final Switch2Layout.Identify ID = f -> {
        try {
            if (f.isFile()) { String s = read(f).trim(); return s.matches("[0-9A-F]{16}") ? s : null; }
            File t = new File(f, "TITLE");
            return t.isFile() ? read(t).trim() : null;
        } catch (IOException e) {
            return null;
        }
    };

    /** A job.json as Android's org.json writes it ("/" escaped as "\/"), with a step whose own state is not the job's */
    private static File job(File work, String id, String state, String stepState, File dump, File pack) throws IOException {
        String j = "{\"format\":2,\"title_id\":\"" + id + "\",\"steps\":{\"split\":{\"state\":\"" + stepState + "\",\"done\":3}},\"dump\":\"" + Switch2Layout.jsonEscape(dump.getPath(), true)
                + "\",\"work\":\"" + Switch2Layout.jsonEscape(work.getPath(), true) + "\",\"pack\":\"" + Switch2Layout.jsonEscape(pack.getPath(), true)
                + "\",\"shader_cache\":\"" + Switch2Layout.jsonEscape(new File(pack, "shaders").getPath(), true) + "\",\"note\":\"" + Switch2Layout.jsonEscape(dump.getPath() + "-copy", true)
                + "\",\"state\":\"" + state + "\"}";
        File f = Switch2Layout.jobFile(work);
        write(f, j);
        return f;
    }

    private static String unescape(String json) { return json.replace("\\/", "/").replace("\\\\", "\\"); }

    private static String[] names(File d) { String[] l = d.list(); if (l == null) return new String[0]; Arrays.sort(l); return l; }

    private static int lines(File log, String verb) throws IOException {
        int n = 0;
        for (String l : Files.readAllLines(log.toPath(), StandardCharsets.UTF_8)) if (l.split("\t").length > 1 && l.split("\t")[1].equals(verb)) n++;
        return n;
    }

    public static void main(String[] args) throws IOException {
        File t = new File(args[0]).getAbsoluteFile(), root = new File(t, "Switch2");
        root.mkdirs();

        // The top level of a job.json, not a step's own "state"
        check(Switch2Layout.topLevelString("{\"steps\":{\"a\":{\"state\":\"running\"}},\"state\":\"paused\"}", "state").equals("paused"), "top-level state, not a step's");
        check(Switch2Layout.topLevelString("{\"state\":\"run\\\"x\",\"n\":1}", "state").equals("run\"x"), "escapes in a value");
        check(Switch2Layout.topLevelString("{\"n\":1}", "state").isEmpty(), "no state");

        // The old layout: games in the root, work folders beside them, mods/, the app's data and things that are not games
        File mkw = game(new File(root, "Mario Kart World"), MKW), dkb = game(new File(root, "Donkey Kong Bananza"), DKB);
        File oot = nup(new File(root, "The Legend of Zelda Ocarina of Time.nup"), OOT), poko = game(new File(root, "Pokemon Pokopia"), POKO);
        game(new File(root, "Games/Pokemon Pokopia"), POKO);   // already in Games/: the root's one stays
        File notes = new File(root, "notes");
        write(new File(notes, "readme.txt"), "not a game");
        write(new File(root, "Lossless.dll"), "dll");
        write(new File(root, "unknown.nup"), "not a nup");
        for (String d : new String[] {"profiles/" + MKW + "/game.tsv", "covers/" + MKW + ".png", "drivers/x/meta.json", "Config/a.txt", "saves/" + DKB + "/s.bin", "saves-test/" + DKB + "/s.bin",
                "Shaders/swap2-shaders-" + DKB + "-458752-v-0123456789ab.zip"})
            write(new File(root, d), "data");
        write(new File(root, "save-backups/" + DKB + "/b/main/s.bin"), "backup");
        write(new File(root, Switch2Layout.LOG), "an older line, in another form\n");
        File mkwWork = new File(root, MKW + "-work"), dkbWork = new File(root, DKB.toLowerCase() + "-work"), ootWork = new File(root, OOT + "-work");
        File mkwPack = new File(mkwWork, "android-pack");
        write(new File(mkwPack, "pack.tsv"), "format\t2\n");
        job(mkwWork, MKW, "done", "done", mkw, mkwPack);
        job(dkbWork, DKB, "paused", "running", dkb, new File(t, "appdata/packs/" + DKB));   // a paused job whose split step still says running: not a running job
        File ootJob = job(ootWork, OOT, "running", "running", oot, new File(t, "appdata/packs/" + OOT));
        write(new File(ootWork, "nvn_shdump/a.bin"), "dump");
        write(new File(root, "mods/" + MKW + "/My Mod/exefs/aa.ips"), "PATCH");

        // The paths saved before the move (the launcher's preferences, as strings)
        String list = "[{\"title_id\":\"" + MKW + "\",\"game\":\"" + Switch2Layout.jsonEscape(mkw.getPath(), true) + "\",\"pack\":\"" + Switch2Layout.jsonEscape(mkwPack.getPath(), true)
                + "\"},{\"title_id\":\"" + OOT + "\",\"game\":\"" + Switch2Layout.jsonEscape(oot.getPath(), false) + "\",\"pack\":\"x\"}]";

        // First run: the Zelda job runs, so its .nup, its work folder and mods/ stay
        Switch2Layout.Report r1 = Switch2Layout.migrate(root, ID);
        File games = new File(root, "Games"), work = new File(root, "Work");
        check(new File(games, "Mario Kart World/TITLE").isFile() && !mkw.exists(), "a game folder moved into Games/");
        check(new File(games, "Donkey Kong Bananza").isDirectory() && !dkb.exists(), "another game folder moved");
        check(oot.isFile() && !new File(games, oot.getName()).exists(), "the .nup of a running job stays");
        check(ootWork.isDirectory() && !new File(work, OOT).exists(), "the running job's work folder stays");
        check(read(ootJob).contains("\"state\":\"running\""), "the running job's file is left alone");
        check(new File(work, MKW + "/android-pack/pack.tsv").isFile() && !mkwWork.exists(), "an <id>-work into Work/<id>");
        check(new File(work, DKB).isDirectory() && !dkbWork.exists(), "a lower-case <id>-work into Work/<ID>");
        check(poko.isDirectory() && new File(games, "Pokemon Pokopia/TITLE").isFile(), "a game whose Games/ name is taken stays in the root");
        check(notes.isDirectory() && new File(root, "Lossless.dll").isFile() && new File(root, "unknown.nup").isFile(), "not games: left alone");
        for (String d : new String[] {"profiles", "covers", "drivers", "Config", "saves", "saves-test", "save-backups", "Shaders"}) check(new File(root, d).isDirectory(), "app data stays: " + d);
        check(Switch2Layout.shadersDir(root).equals(new File(root, "Shaders")) && Switch2Layout.RESERVED.contains("shaders"), "the folder of Export shaders: Switch2/Shaders");
        check(new File(root, "mods/" + MKW + "/My Mod/exefs/aa.ips").isFile(), "mods/ waits while a job runs");
        check(r1.moved == 4 && r1.kept == 1 && r1.skipped == 3 && r1.failed == 0 && r1.pending(), "first report: " + r1);
        File log = new File(root, Switch2Layout.LOG);
        check(read(log).startsWith("an older line, in another form\n"), "the older log is kept");
        check(lines(log, "moved") == 4 && lines(log, "move") == 4 && lines(log, "kept") == 1 && lines(log, "skipped") == 3, "move.log: " + read(log));

        // Repointing what was saved
        Map<String, String> ren = Switch2Layout.renames(root);
        check(ren.size() == 4, "four moves hold: " + ren);
        File mkwNew = new File(games, "Mario Kart World"), mkwWorkNew = new File(work, MKW);
        check(Switch2Layout.repoint(mkw.getPath(), ren).equals(mkwNew.getPath()), "a game folder repointed");
        check(Switch2Layout.repoint(new File(mkwPack, "shaders").getPath(), ren).equals(new File(mkwWorkNew, "android-pack/shaders").getPath()), "a path inside a moved folder");
        check(Switch2Layout.repoint(mkw.getPath() + " 2", ren).equals(mkw.getPath() + " 2"), "a sibling with a longer name is not repointed");
        check(Switch2Layout.repoint(Switch2Layout.jobFile(mkwWork).getPath() + "@123", ren).equals(Switch2Layout.jobFile(mkwWorkNew).getPath() + "@123"), "the \"added\" mark");
        check(Switch2Layout.repoint(oot.getPath(), ren).equals(oot.getPath()), "what did not move is not repointed");
        String l2 = unescape(Switch2Layout.repointJson(list, ren));
        check(l2.contains("\"game\":\"" + mkwNew.getPath() + "\"") && l2.contains("\"pack\":\"" + new File(mkwWorkNew, "android-pack").getPath() + "\""), "the game list repointed: " + l2);
        check(l2.contains("\"game\":\"" + oot.getPath() + "\""), "the game list's unmoved game kept");
        check(Switch2Layout.repointJobs(root, ren) == 2, "two job files repointed (the running one not)");
        String mj = unescape(read(Switch2Layout.jobFile(mkwWorkNew)));
        check(mj.contains("\"dump\":\"" + mkwNew.getPath() + "\"") && mj.contains("\"work\":\"" + mkwWorkNew.getPath() + "\"")
                && mj.contains("\"pack\":\"" + new File(mkwWorkNew, "android-pack").getPath() + "\"") && mj.contains("\"shader_cache\":\"" + new File(mkwWorkNew, "android-pack/shaders").getPath() + "\""),
                "job.json: dump, work, pack, shader_cache repointed: " + mj);
        check(mj.contains("\"note\":\"" + mkw.getPath() + "-copy\""), "a string that only starts like a moved path is kept");
        check(!new File(Switch2Layout.jobFile(mkwWorkNew).getPath() + ".tmp").exists(), "no .tmp left");
        check(Switch2Layout.repointJobs(root, ren) == 0, "repointing again changes nothing");
        check(Switch2Layout.jobState(new File(work, DKB)).equals("paused"), "the paused job read through its new folder");

        // Where things are now
        check(Switch2Layout.workOf(root, mkwNew, MKW).equals(mkwWorkNew), "a game in Games/ has Work/<id>");
        check(Switch2Layout.workOf(root, oot, OOT).equals(ootWork), "an old <id>-work beside the dump while there is no new one");
        File fresh = game(new File(games, "New Game"), "0100000000010000");
        check(Switch2Layout.workOf(root, fresh, "0100000000010000").equals(new File(work, "0100000000010000")), "a new game's work folder is Work/<id>");
        File elsewhere = nup(new File(t, "other/x.nup"), MKW);
        check(Switch2Layout.workOf(root, elsewhere, MKW).equals(new File(t, "other/Work/" + MKW)), "a dump outside the Switch2 folder: Work/ beside it");
        check(Switch2Layout.rootOf(mkwNew).equals(root) && Switch2Layout.rootOf(poko).equals(root), "the root of a game in Games/ and in the root");
        check(Switch2Layout.moved(root, mkw).equals(mkwNew), "a frontend's old path found in Games/");
        check(Switch2Layout.moved(root, new File(root, "gone")).equals(new File(root, "gone")), "a path that is nowhere stays");
        check(Switch2Layout.modsDir(root).getName().equals("mods"), "mods/ read while it is the only one");

        // Second run, the Zelda job finished: what waited moves; what is kept is not logged again
        String ojs = read(ootJob).replace("\"state\":\"running\"}", "\"state\":\"done\"}").replace("\"split\":{\"state\":\"running\"", "\"split\":{\"state\":\"done\"");
        write(ootJob, ojs);
        Switch2Layout.Report r2 = Switch2Layout.migrate(root, ID);
        check(new File(games, oot.getName()).isFile() && !oot.exists() && new File(work, OOT + "/nvn_shdump/a.bin").isFile(), "the finished job's .nup and work folder moved");
        List<String> top = Arrays.asList(names(root));
        check(top.contains("Mods") && !top.contains("mods") && new File(root, "Mods/" + MKW + "/My Mod/exefs/aa.ips").isFile(), "mods/ into Mods/: " + top);
        check(r2.moved == 3 && r2.kept == 1 && r2.skipped == 0 && r2.failed == 0 && !r2.pending(), "second report: " + r2);
        check(lines(log, "kept") == 1, "a kept entry is logged once");
        Map<String, String> ren2 = Switch2Layout.renames(root);
        check(Switch2Layout.repointJobs(root, ren2) == 1, "the Zelda job repointed");
        String oj = unescape(read(Switch2Layout.jobFile(new File(work, OOT))));
        check(oj.contains("\"dump\":\"" + new File(games, oot.getName()).getPath() + "\"") && oj.contains("\"work\":\"" + new File(work, OOT).getPath() + "\""), "the .nup job: " + oj);
        check(Switch2Layout.modsDir(root).getName().equals("Mods"), "Mods/ after the move");

        // Third run: nothing more
        Switch2Layout.Report r3 = Switch2Layout.migrate(root, ID);
        check(r3.moved == 0 && r3.kept == 1 && !r3.pending(), "third report: " + r3);

        // An interrupted run: a "move" line without its result counts when the move happened; a new game at an old path keeps its own path
        File r4 = new File(t, "interrupted"), a = game(new File(r4, "A"), MKW), b = new File(r4, "Games/A");
        Switch2Layout.log(r4, "move", a, b, "");
        b.getParentFile().mkdirs();
        check(a.renameTo(b), "the test's own rename");
        check(Switch2Layout.renames(r4).containsKey(a.getPath()), "an unfinished log line whose move happened counts");
        game(a, MKW);   // the user puts a game at the old path again
        check(Switch2Layout.renames(r4).isEmpty(), "an old path that holds something again is not repointed");

        // A rename that cannot happen: Games is a file here
        File r5 = new File(t, "failing"), g5 = game(new File(r5, "Game"), MKW);
        write(new File(r5, "Games"), "a file");
        Switch2Layout.Report rep5 = Switch2Layout.migrate(r5, ID);
        check(g5.isDirectory() && !rep5.pending() && rep5.failed == 1 && rep5.moved == 0, "a failed move leaves the game where it is and is not retried: " + rep5);
        Switch2Layout.Report rep5b = Switch2Layout.migrate(r5, ID);
        File log5 = new File(r5, Switch2Layout.LOG);
        check(!rep5b.pending() && rep5b.failed == 1 && lines(log5, "failed") == 1, "a failure tried again by hand is logged once: " + read(log5));
        // The storage service reported the rename as failed and finished it later: the folder turns up at its new path, and the saved paths follow it
        check(new File(r5, "Games").delete() && new File(r5, "Games").mkdirs() && g5.renameTo(new File(r5, "Games/Game")), "the late rename is set up");
        check(new File(r5, "Games/Game").getPath().equals(Switch2Layout.renames(r5).get(g5.getPath())), "a failed rename finished later counts as moved: " + Switch2Layout.renames(r5));

        // A rename that fails (a file held open in the folder: Windows refuses to rename it; elsewhere the rename succeeds and this is not checked)
        File r6 = new File(t, "held"), g6 = game(new File(r6, "Game"), MKW);
        try (java.io.FileInputStream held = new java.io.FileInputStream(new File(g6, "TITLE"))) {
            check(held.available() >= 0, "the held file reads");
            Switch2Layout.migrate(r6, ID);
            if (g6.isDirectory()) {
                Switch2Layout.Report rep6 = Switch2Layout.migrate(r6, ID);
                File log6 = new File(r6, Switch2Layout.LOG);
                check(!rep6.pending() && lines(log6, "move") == 1 && lines(log6, "failed") == 1, "a rename that keeps failing: one move and one failed line: " + read(log6));
            }
        }
        {
            Switch2Layout.Report rep6c = Switch2Layout.migrate(r6, ID);   // the file closed: the retry moves it, and its earlier "move" line is not written again
            File log6 = new File(r6, Switch2Layout.LOG);
            check(!g6.exists() && new File(r6, "Games/Game").isDirectory() && rep6c.failed == 0 && lines(log6, "move") == 1 && lines(log6, "moved") == 1,
                    "the retry that succeeds: " + read(log6));
            check(Switch2Layout.renames(r6).size() == 1, "the retried move holds");
        }

        // Paths in another alias form (an adb-started job's /sdcard/... dump), slash escaped or not
        Map<String, String> al = new java.util.LinkedHashMap<>();
        al.put("/storage/emulated/0/Switch2/Mario Kart World", "/storage/emulated/0/Switch2/Games/Mario Kart World");
        al.put("/storage/emulated/0/Switch2/" + MKW + "-work", "/storage/emulated/0/Switch2/Work/" + MKW);
        String aj = "{\"dump\":\"/sdcard/Switch2/Mario Kart World\",\"work\":\"\\/sdcard\\/Switch2\\/" + MKW + "-work\",\"pack\":\"/mnt/sdcard/Switch2/" + MKW
                + "-work/android-pack\",\"note\":\"/sdcard/Switch2/Mario Kart World 2\",\"state\":\"paused\",\"q\":\"a \\\"quoted\\\" \\u00e9\"}";
        String ar = Switch2Layout.repointJson(aj, al);
        check(ar.contains("\"dump\":\"/storage/emulated/0/Switch2/Games/Mario Kart World\""), "an alias dump repointed: " + ar);
        check(ar.contains("\"work\":\"\\/storage\\/emulated\\/0\\/Switch2\\/Work\\/" + MKW + "\""), "an escaped alias work folder repointed, still escaped: " + ar);
        check(ar.contains("\"pack\":\"/storage/emulated/0/Switch2/Work/" + MKW + "/android-pack\""), "a path inside an alias folder: " + ar);
        check(ar.contains("\"note\":\"/sdcard/Switch2/Mario Kart World 2\"") && ar.contains("\"q\":\"a \\\"quoted\\\" \\u00e9\""), "other strings kept as written: " + ar);
        check(Switch2Layout.repointJson(ar, al).equals(ar), "repointing again changes nothing");

        // An empty or missing root
        check(Switch2Layout.migrate(new File(t, "none"), ID).moved == 0, "no Switch2 folder: nothing");
        System.out.println("ok " + checks);
    }
}
