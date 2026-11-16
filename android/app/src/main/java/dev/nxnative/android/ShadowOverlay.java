package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Shadow BYML overlay independent of scene_720p, built from the active RomFS. */
final class ShadowOverlay {
    static final String MAIN = "gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml";
    private ShadowOverlay() {}
    static File dir(File files, String titleId, int profile) {
        return new File(files, "overlay/" + titleId + "/shadow_" + profile);
    }
    static File stamp(File files, String titleId, int profile) {
        return new File(files, "overlay/" + titleId + "/shadow_" + profile + ".txt");
    }
    static String stampText(int profile, String version) {
        return "profile\t" + profile + "\nversion\t" + version + "\n";
    }
    static boolean current(File files, String titleId, int profile, String version) {
        if (files == null || profile < 1 || profile > 2 || version == null) return false;
        if (!new File(dir(files, titleId, profile), MAIN).isFile()) return false;
        try {
            return new String(Files.readAllBytes(stamp(files, titleId, profile).toPath()),
                    StandardCharsets.UTF_8).equals(stampText(profile, version));
        } catch (IOException e) { return false; }
    }
    static String[] argv(String romfs, int profile, File out) {
        return new String[] {"--romfs", romfs, "--profile", Integer.toString(profile),
                "--out", out.getPath()};
    }
}
