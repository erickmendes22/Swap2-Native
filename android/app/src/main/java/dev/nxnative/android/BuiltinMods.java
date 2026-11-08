package dev.nxnative.android;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;

/**
 * The mods a game's profile ships (dm/games/&lt;title ID&gt;/mods/&lt;folder&gt;/: exefs/&lt;patch files&gt; and mod.tsv), which the APK carries as assets
 * (mods/&lt;title ID&gt;/&lt;folder&gt;/…, build.gradle nxProfileMods) and the game's settings offer as a switch (GameSettings, Graphics). Turned on, the mod's
 * exefs/ is copied into the mods folder as &lt;title ID&gt;/&lt;folder&gt;/exefs/ (where ExefsMods and the rewrite find it, so it is an ordinary mod from then
 * on: the Mods section lists it, its '-' turns it off); turned off, its folder gets the '-'. Either way the next Play or Prepare rewrites the module (PackCheck.mods).
 * A mod whose mod.tsv says android_default on is installed once per game at the launcher's start (applyDefaults), unless the switch was used for it before.
 * Plain Java (no Android classes): the assets come through {@link Source}; dm/tools/tests/test_profile_mods.py checks the profile side.
 */
final class BuiltinMods {
    private BuiltinMods() {}

    /** Where the shipped mods are read from: the APK's assets on the phone, a folder in the JVM test */
    interface Source {
        /** The names in a folder (no '/' at the end), empty when there is none */
        String[] list(String dir) throws IOException;

        InputStream open(String path) throws IOException;
    }

    /** A Source over a folder that holds mods/&lt;title ID&gt;/… (the JVM test; a checkout's dm/games has &lt;title ID&gt;/mods/… instead) */
    static Source folder(File root) {
        return new Source() {
            @Override public String[] list(String dir) {
                String[] l = new File(root, dir).list();
                return l == null ? new String[0] : l;
            }

            @Override public InputStream open(String path) throws IOException { return Files.newInputStream(new File(root, path).toPath()); }
        };
    }

    static final String ASSETS = "mods";

    /** One shipped mod of a title */
    static final class Builtin {
        final String titleId, folder;
        final String label, note;   // string resource names (res/values*/strings.xml), "" when mod.tsv has none
        final boolean defaultOn;
        final List<String> exefs = new ArrayList<>();   // its patch files' names, by name

        Builtin(String titleId, String folder, String label, String note, boolean defaultOn) {
            this.titleId = titleId;
            this.folder = folder;
            this.label = label;
            this.note = note;
            this.defaultOn = defaultOn;
        }

        String asset(String rel) { return ASSETS + "/" + titleId + "/" + folder + "/" + rel; }

        /** The preference that says the switch (or the default) has decided this mod for this game: applyDefaults never installs it again */
        String decidedKey() { return "builtin_mod_" + folder + "@" + titleId; }
    }

    private static byte[] read(Source src, String path) throws IOException {
        try (InputStream in = src.open(path)) {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            byte[] buf = new byte[1 << 14];
            int k;
            while ((k = in.read(buf)) > 0) {
                if (o.size() + k > ExefsMods.MAX_BYTES) throw new IOException(path + ": more than " + (ExefsMods.MAX_BYTES >> 20) + " MB");
                o.write(buf, 0, k);
            }
            return o.toByteArray();
        }
    }

    /** The title's shipped mods, by folder name; a folder without mod.tsv or without a patch file in exefs/ is left out */
    static List<Builtin> of(Source src, String titleId) {
        List<Builtin> out = new ArrayList<>();
        String[] folders;
        try { folders = src.list(ASSETS + "/" + titleId); } catch (IOException e) { return out; }
        Arrays.sort(folders);
        for (String f : folders) {
            if (f.isEmpty() || f.startsWith(".") || f.startsWith("-")) continue;
            String label = "", note = "";
            boolean on = false;
            String base = ASSETS + "/" + titleId + "/" + f + "/";
            try {
                for (String ln : new String(read(src, base + "mod.tsv"), StandardCharsets.UTF_8).split("\r?\n")) {
                    if (ln.isEmpty() || ln.startsWith("#")) continue;
                    String[] c = ln.split("\t");
                    if (c.length < 2) continue;
                    if (c[0].equals("label")) label = c[1].trim();
                    else if (c[0].equals("note")) note = c[1].trim();
                    else if (c[0].equals("android_default")) on = c[1].trim().equals("on");
                }
                Builtin b = new Builtin(titleId, f, label, note, on);
                String[] ex = src.list(base + "exefs");
                Arrays.sort(ex);
                for (String x : ex) if (ExefsMods.patch(x)) b.exefs.add(x);
                if (!b.exefs.isEmpty()) out.add(b);
            } catch (IOException e) { /* no mod.tsv: not a shipped mod */ }
        }
        return out;
    }

    /** The mod folder it was installed as (on or off, the yuzu / Eden layout), or null when it is not in the mods folder */
    static ExefsMods.Mod installed(File root, Builtin b) {
        for (ExefsMods.Mod m : ExefsMods.list(root, b.titleId)) if (!m.atmosphere && m.name.equalsIgnoreCase(b.folder)) return m;
        return null;
    }

    /** Whether it is on: installed and its folder has no '-' */
    static boolean isOn(File root, Builtin b) {
        ExefsMods.Mod m = installed(root, b);
        return m != null && m.on;
    }

    /**
     * Turns it on (copied in when it is not there; the files brought up to the APK's when they differ, so an update's bytes reach the mods folder) or off (its
     * folder renamed with '-'; nothing when it is not there). Returns the mod as it is now, null when it is off and not installed
     */
    static ExefsMods.Mod set(File root, Builtin b, boolean on, Source src) throws IOException {
        ExefsMods.Mod m = installed(root, b);
        if (!on) return m == null ? null : ExefsMods.setEnabled(m, false);
        if (m == null) {
            File t = ExefsMods.titleDir(root, b.titleId);
            // written beside the title folders first, where neither the tools nor the launcher look (as Add mod stages), and moved in whole
            File tmp = new File(root, ExefsMods.STAGING + "builtin-" + b.folder + "-" + System.nanoTime());
            File ex = new File(tmp, "exefs");
            if (!ex.mkdirs()) throw new IOException("cannot create " + ex);
            try {
                for (String x : b.exefs) Files.write(new File(ex, x).toPath(), read(src, b.asset("exefs/" + x)));
            } catch (IOException e) {
                ExefsMods.deleteTree(tmp.toPath());
                throw e;
            }
            File to = new File(t, b.folder);
            if (ExefsMods.taken(t, b.folder, null) || !tmp.renameTo(to)) {
                ExefsMods.deleteTree(tmp.toPath());
                throw new IOException("cannot move " + b.folder + " into " + t);
            }
            return new ExefsMods.Mod(to, false);
        }
        m = ExefsMods.setEnabled(m, true);
        File e = m.exefs();
        if (e == null) { e = new File(m.dir, "exefs"); if (!e.mkdirs()) throw new IOException("cannot create " + e); }
        for (String x : b.exefs) {
            byte[] want = read(src, b.asset("exefs/" + x));
            File f = new File(e, x);
            if (!f.isFile() || !Arrays.equals(Files.readAllBytes(f.toPath()), want)) Files.write(f.toPath(), want);
        }
        return m;
    }

    /**
     * The default of each shipped mod of the title that nothing has decided yet (its decidedKey not in decided): installed and on when android_default is on.
     * Returns the keys it decided (the caller keeps them, so a mod the player removed or turned off is never put back)
     */
    static List<String> applyDefaults(File root, String titleId, Source src, Collection<String> decided) throws IOException {
        List<String> out = new ArrayList<>();
        for (Builtin b : of(src, titleId)) {
            if (!b.defaultOn || decided.contains(b.decidedKey())) continue;
            if (installed(root, b) == null) set(root, b, true, src);
            out.add(b.decidedKey());
        }
        return out;
    }

    /** A label for logs and when the resource is missing: the folder's name */
    static String fallbackLabel(Builtin b) { return b.folder; }
}
