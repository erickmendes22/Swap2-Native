package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * A game this APK runs: its profile (dm/games/&lt;title ID&gt;) was compiled into a host of its own, libnxhost_&lt;title ID&gt;.so (build.gradle nxGames,
 * src/main/cpp/CMakeLists.txt), and what the launcher needs of it comes from build.gradle as BuildConfig.NX_PROFILES: one line per game, tab-separated: title ID,
 * name, the shader count Prepare translates, the shader inputs digest, the builds (game.tsv build rows, "version module=build ID …", ';' between builds), and, when the APK has them, the readiness rows (the profile's readiness.tsv: "level|fact|min|what", ';' between rows: Readiness.parseReqs), its status row (playable or bring-up; dm/games/README.md "Readiness rows"), the shader delta rows (vk_delta.tsv's "from" rows: "version=count", ',' between them), its "stamp" rows ("version:old SHA-256:new SHA-256", ';' between them), what Game resolution sets (resolutionEnv), the NDSR input encoding when the shader map has agl's NDSR networks (the Upscaler option, ndsrEnv) and the Scene resolution's palette scale (scene_scale_palette: sceneScale).
 * Swap2-Native: one host runs every game (the profile comes with the pack), so a game whose profile is not built in runs from a profile folder in
 * /sdcard/Switch2/profiles/&lt;title ID&gt;/ (game.tsv and its tables, as in dm/games: {@link #userDir}), read here and handed to the packer (DM_GAMES_DIR). A built-in
 * profile wins over a folder of the same title ID. A game with neither cannot run: the launcher says so instead of starting it.
 * No Android classes: the JVM test (android/app/src/jvmtest) runs it on the Mac.
 */
final class Profile {
    final String titleId, name, shaderInputs, builds, reqs, status;
    final int shaderTotal;
    String delta = "";   // the shader delta manifest's "from" rows: "version=shaders to translate", ',' between them (ShaderLibs.toTranslate)
    String stamp = "";   // its "stamp" rows: "version:old SHA-256:new SHA-256", ';' between them (ShaderLibs.restamp)
    String resolution = "";   // what Game resolution sets (build.gradle resolutionOf): "window", "scale:<choice>=<scale>/<console|handheld>,…" or "" (nothing: not offered)
    String ndsr = "";    // agl's NDSR networks (build.gradle ndsrOf): the FSR stand-in's input encoding (profile ndsr_input: sqrt or linear) when the shader map has them, else ""
    String scene = "";   // the Scene resolution's 720p (build.gradle sceneOf): "<scale>/<expected original scales, ','>" from scene_scale_palette, or "" (not offered)

    /** Whether Game resolution does something for this game (its profile has window_fn or graphics_scale rows) */
    boolean hasResolution() { return resolution.equals("window") || resolution.startsWith("scale:"); }

    /** Whether the Upscaler option does something for this game: its shader map has agl's NDSR upscaler networks (agl_ndsr*.pck), which DM_VK_NDSR=fsr replaces */
    boolean hasNdsr() { return ndsr.equals("sqrt") || ndsr.equals("linear"); }

    String upscaler = "";   // the Upscaler's default (build.gradle ndsrDefaultOf; the profile's ndsr_default row): "fsr", or "" (the network)

    /** The Upscaler's choice when the player has made none (Prefs.ndsr): "fsr" where the profile says so and the game has the networks, else "net" */
    String ndsrDefault() { return hasNdsr() && upscaler.equals("fsr") ? "fsr" : "net"; }

    /**
     * The host's lines for an Upscaler choice (Prefs.ndsr), for a game with agl's NDSR networks: DM_VK_NDSR_INPUT with the profile's encoding of the network's
     * input (ndsr_input; vka_ndsr.c, docs/reference/rendering.md "agl's NDSR upscaler network replaced by FSR 1 EASU on the Vulkan replay") whatever the choice, so
     * a DM_VK_NDSR=fsr line of env.txt or a live control line takes the right one too (the host reads it only for the stand-in), and DM_VK_NDSR=fsr for "fsr"
     * ("net": the network runs). None for a game without the networks
     */
    List<String> ndsrEnv(String choice) {
        List<String> env = new ArrayList<>();
        if (!hasNdsr()) return env;
        env.add("DM_VK_NDSR_INPUT=" + ndsr);
        // Preserve previous SGSR1 presentation as a reproducible baseline.
        // Only the new explicit sg sr-compute choice runs the 12-tap SGSR1
        // in the NDSR compute operation at the game's existing output size.
        if (Prefs.NDSR_SGSR_COMPUTE.equals(choice) &&
                Prefs.OCARINA_TITLE.equals(titleId))
            env.add("DM_VK_NDSR=sgsr");
        else if ("fsr".equals(choice) || "sgsr".equals(choice) ||
                 Prefs.NDSR_SGSR_COMPUTE.equals(choice))
            env.add("DM_VK_NDSR=fsr");
        return env;
    }

    /** The scale the Scene resolution's 720p writes into every level of the game's dynamic resolution palette (gsys_dynres.py --scale), null when it has none */
    String sceneScale() {
        int sl = scene.indexOf('/');
        String s = sl < 0 ? scene : scene.substring(0, sl);
        if (!s.matches("\\d*\\.\\d+|\\d+")) return null;
        double v = Double.parseDouble(s);
        return v >= 0.05 && v <= 2 ? s : null;
    }

    /** The palette's original scales the tool checks before it writes (gsys_dynres.py --expect, ',' between them), "" when the profile names none */
    String sceneExpect() {
        int sl = scene.indexOf('/');
        String e = sl < 0 ? "" : scene.substring(sl + 1);
        return e.matches("[0-9.]+(,[0-9.]+)*") ? e : "";
    }

    /** Whether the Scene resolution option does something for this game: its profile has a scene_scale_palette row */
    boolean hasScene() { return sceneScale() != null; }

    /**
     * The host's environment lines for a Game resolution choice (Prefs.WINDOWS: "1920x1080", "original", "1280x720"): DM_WINDOW_SIZE=&lt;choice&gt; for a game with
     * window_fn rows; DM_GRAPHICS_SCALE and DM_OPMODE from the choice's graphics_scale row for a game that sizes its scenes by the graphics scale (none for a choice
     * without a row: the game's own); none for a game with neither.
     */
    List<String> resolutionEnv(String choice) {
        List<String> env = new ArrayList<>();
        if (resolution.equals("window")) env.add("DM_WINDOW_SIZE=" + choice);
        else if (resolution.startsWith("scale:")) {
            for (String r : resolution.substring(6).split(",")) {
                int eq = r.indexOf('='), sl = r.indexOf('/');
                if (eq <= 0 || sl < eq || !r.substring(0, eq).equals(choice)) continue;
                env.add("DM_GRAPHICS_SCALE=" + r.substring(eq + 1, sl));
                env.add("DM_OPMODE=" + (r.substring(sl + 1).equals("handheld") ? 0 : 1));
                break;
            }
        }
        return env;
    }

    /** Whether any game of this APK has Game resolution (Settings shows its default only then) */
    static boolean anyResolution() { for (Profile p : all()) if (p.hasResolution()) return true; return false; }

    Profile(String titleId, String name, int shaderTotal, String shaderInputs, String builds, String reqs, String status) {
        this.reqs = reqs;
        this.status = status;
        this.titleId = titleId;
        this.name = name;
        this.shaderTotal = shaderTotal;
        this.shaderInputs = shaderInputs;
        this.builds = builds;
    }

    /** The profiles of a BuildConfig.NX_PROFILES table; a malformed line is skipped */
    static List<Profile> parse(String table) {
        List<Profile> out = new ArrayList<>();
        for (String line : table.split("\n")) {
            String[] c = line.split("\t", -1);
            if (c.length < 5 || !c[0].matches("[0-9A-F]{16}")) continue;
            int total;
            try { total = Integer.parseInt(c[2]); } catch (NumberFormatException e) { total = 0; }
            Profile p = new Profile(c[0], c[1].isEmpty() ? c[0] : c[1], total, c[3], c[4], c.length > 5 ? c[5] : "", c.length > 6 ? c[6] : "");
            p.delta = c.length > 7 ? c[7] : "";
            p.stamp = c.length > 8 ? c[8] : "";
            p.resolution = c.length > 9 ? c[9] : "";
            p.ndsr = c.length > 10 ? c[10] : "";
            p.scene = c.length > 11 ? c[11] : "";
            p.upscaler = c.length > 12 ? c[12] : "";
            out.add(p);
        }
        return Collections.unmodifiableList(out);
    }

    private static List<Profile> all;

    /** The games this APK runs: its built-in profiles in build.gradle's order (the first is the default), then the profile folders of {@link #userDir} */
    static synchronized List<Profile> all() {
        if (all == null) {
            List<Profile> l = new ArrayList<>(parse(BuildConfig.NX_PROFILES));
            for (Profile u : user(userDir())) {
                boolean built = false;
                for (Profile p : l) built |= p.titleId.equals(u.titleId);
                if (!built) l.add(u);
            }
            all = Collections.unmodifiableList(l);
        }
        return all;
    }

    /** Reads the profile folders again (a folder added while the app runs: Add game, Refresh) */
    static synchronized void reload() { all = null; }

    /** Where profile folders of games not built into the APK go: &lt;shared storage&gt;/Switch2/profiles (the folder the games are in, MainActivity.SWITCH2_URI) */
    static File userDir() {
        String s = System.getenv("EXTERNAL_STORAGE");
        return new File(s != null && !s.isEmpty() ? s : "/storage/emulated/0", "Switch2/profiles");
    }

    /**
     * The profiles of a folder of profile folders (&lt;title ID&gt;/game.tsv), as build.gradle makes a built-in one: the name, the shader count (shader_map.tsv's rows),
     * the builds ("version module=build ID …" from the build rows) and what Game resolution sets (window_fn or graphics_scale rows). Its shader inputs digest is
     * "unknown" (dmsh_chain.py computes it from Python; the launcher then checks a library by its path only), and it has no readiness rows or shader delta
     */
    static List<Profile> user(File dir) {
        List<Profile> out = new ArrayList<>();
        File[] ds = dir.listFiles();
        if (ds == null) return out;
        java.util.Arrays.sort(ds);
        for (File d : ds) {
            if (!d.getName().matches("[0-9A-F]{16}")) continue;
            List<String[]> rows = new ArrayList<>();
            try {
                for (String line : Files.readAllLines(new File(d, "game.tsv").toPath(), StandardCharsets.UTF_8)) {
                    if (line.trim().isEmpty() || line.trim().startsWith("#")) continue;
                    String[] c = line.split("\t");
                    for (int i = 0; i < c.length; i++) c[i] = c[i].trim();
                    rows.add(c);
                }
            } catch (IOException e) { continue; }
            String name = d.getName(), ndsrInput = "linear", scene = "", upscaler = "";
            List<String> builds = new ArrayList<>(), scale = new ArrayList<>();
            boolean window = false;
            for (String[] c : rows) {
                if (c[0].equals("ndsr_input") && c.length > 1) ndsrInput = c[1];
                if (c[0].equals("ndsr_default") && c.length > 1 && c[1].equals("fsr")) upscaler = "fsr";
                if (c[0].equals("scene_scale_palette") && c.length > 1 && scene.isEmpty()) scene = c[1] + (c.length > 2 ? "/" + c[2] : "");
                if (c[0].equals("name") && c.length > 1) name = c[1].replaceAll("[\\t\\n\\\\\"]", " ");
                else if (c[0].equals("build") && c.length > 3) {
                    java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\d+").matcher(c[1]);
                    StringBuilder b = new StringBuilder(m.find() ? m.group() : c[1]);
                    for (int i = 3; i < c.length; i++) b.append(' ').append(c[i]);
                    builds.add(b.toString());
                } else if (c[0].equals("window_fn")) window = true;
                else if (c[0].equals("graphics_scale") && c.length > 3) scale.add(c[1] + "=" + c[2] + "/" + c[3]);
            }
            int shaders = 0;
            boolean ndsr = false;
            try {
                for (String line : Files.readAllLines(new File(d, "shader_map.tsv").toPath(), StandardCharsets.UTF_8))
                    if (!line.isEmpty() && !line.startsWith("#") && !line.startsWith("package\t")) { shaders++; ndsr |= line.contains("/agl_ndsr"); }
            } catch (IOException e) { /* no shader map yet: Prepare counts what the split finds */ }
            Profile p = new Profile(d.getName(), name, shaders, "unknown", String.join(";", builds), "", "bring-up");
            p.resolution = window ? "window" : scale.isEmpty() ? "" : "scale:" + String.join(",", scale);
            p.ndsr = ndsr ? ndsrInput : "";
            p.scene = scene;
            p.upscaler = upscaler;
            out.add(p);
        }
        return out;
    }

    /** This APK's profile of a title ID, null when it has none */
    static Profile of(String titleId) {
        for (Profile p : all()) if (p.titleId.equals(titleId)) return p;
        return null;
    }

    /** The default game (the first): the graphics self-test runs its host */
    static Profile first() { return all().get(0); }

    /** Why this APK cannot run a title, in a sentence (null when it has its profile) */
    static String missing(String titleId, String what) {
        if (of(titleId) != null) return null;
        // The title IDs this APK runs, so a user with another game sees it is not supported (rather than a broken dump); IDs only, no game names
        List<String> ids = new ArrayList<>();
        for (Profile p : all()) ids.add(p.titleId);
        return (what == null ? titleId : what + " (" + titleId + ")") + " has no game profile, so it cannot run here: put one in " + userDir() + "/" + titleId
                + " (game.tsv and its tables, as in the repository's dm/games). Profiles here: " + String.join(", ", ids) + ".";
    }

    /** A version of a dump in words: 0 is the base game itself (no update installed; Mario Kart World 1.8.0's supported build), any other an update */
    static String versionName(long version) { return version == 0 ? "the base game" : "update " + version; }

    /** Which versions of this game the APK supports, as a sentence for a dump it refuses (DumpCheck): its builds' versions (buildMap) */
    String supported() {
        List<String> all = new ArrayList<>();
        int ups = 0;
        for (Long v : buildMap().keySet()) {
            if (v == 0) all.add(0, "the base game (no update)");
            else { all.add("update " + v); ups++; }
        }
        return "This app supports " + name + " (" + titleId + ") as " + String.join(" or ", all) + " only: "
                + (ups == 0 ? "dump the game without an update." : "dump the game with " + (ups == 1 ? "that update" : "one of those updates") + " installed.");
    }

    /** The profile's builds: version → module → build ID (the first 16 bytes, lower case, as game.tsv writes them) */
    Map<Long, Map<String, String>> buildMap() {
        Map<Long, Map<String, String>> out = new LinkedHashMap<>();
        for (String b : builds.split(";")) {
            String[] c = b.trim().split(" ");
            if (c.length < 2 || !c[0].matches("\\d+")) continue;
            Map<String, String> m = new LinkedHashMap<>();
            for (int i = 1; i < c.length; i++) {
                int eq = c[i].indexOf('=');
                if (eq > 0) m.put(c[i].substring(0, eq), c[i].substring(eq + 1).toLowerCase(Locale.ROOT));
            }
            out.put(Long.parseLong(c[0]), m);
        }
        return out;
    }
}
