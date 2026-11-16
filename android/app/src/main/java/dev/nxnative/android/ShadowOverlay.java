package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** A single verified BYML combines shadow-map dimensions and opt-in FPS patches. */
final class ShadowOverlay {
    static final String MAIN = "gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml";
    private ShadowOverlay() {}
    static File dir(File files, String titleId, int profile) {
        return dir(files, titleId, profile, 0);
    }
    static File dir(File files, String titleId, int profile, int effect) {
        String name = effect == 0 ? "shadow_" + profile : "shadow_" + profile + "_fps_" + effect;
        return new File(files, "overlay/" + titleId + "/" + name);
    }
    static File stamp(File files, String titleId, int profile) {
        return stamp(files, titleId, profile, 0);
    }
    static File stamp(File files, String titleId, int profile, int effect) {
        return new File(dir(files, titleId, profile, effect).getPath() + ".txt");
    }
    static String stampText(int profile, String version) {
        return stampText(profile, 0, version);
    }
    static String stampText(int profile, int effect, String version) {
        // Existing map-only overlays retain the original stamp and remain valid.
        String head = "profile\t" + profile + "\n";
        if (effect != 0) head += "fps\t" + effect + "\n";
        if (effect == 3) head += "schema\tssao-alchemy-pairs-v3\n";
        if (effect == 4) head += "schema\tshadow-raw-depth-v2\n";
        if (effect == 5) head += "schema\tpost-resource-retained-v2\n";
        return head + "version\t" + version + "\n";
    }
    static boolean current(File files, String titleId, int profile, String version) {
        return current(files, titleId, profile, 0, version);
    }
    static boolean current(File files, String titleId, int profile, int effect, String version) {
        if (files == null || profile < 0 || profile > 2 || effect < 0 || effect > 5 ||
                (profile == 0 && effect == 0) || version == null) return false;
        if (!new File(dir(files, titleId, profile, effect), MAIN).isFile()) return false;
        try {
            return new String(Files.readAllBytes(stamp(files, titleId, profile, effect).toPath()),
                    StandardCharsets.UTF_8).equals(stampText(profile, effect, version));
        } catch (IOException e) { return false; }
    }
    /** A combined experimental profile never reuses an older single-effect overlay. */
    static boolean validMask(int mask) {
        return mask >= 0 && mask <= 63 && (mask & 3) != 3;
    }
    static File dirMask(File files, String titleId, int shadow, int mask) {
        if (mask == 0) return dir(files, titleId, shadow, 0);
        return new File(files, "overlay/" + titleId + "/shadow_" + shadow + "_fps_mask_" + mask);
    }
    static File stampMask(File files, String titleId, int shadow, int mask) {
        return new File(dirMask(files, titleId, shadow, mask).getPath() + ".txt");
    }
    static String stampTextMask(int shadow, int mask, String version) {
        if (mask == 0) return stampText(shadow, 0, version);
        return "profile\t" + shadow + "\nmask\t" + mask
                + "\nschema\tcombined-fps-v2-ssao-blur\nversion\t" + version + "\n";
    }
    static boolean currentMask(File files, String titleId, int shadow, int mask, String version) {
        if (files == null || titleId == null || version == null ||
                shadow < 0 || shadow > 2 || !validMask(mask) ||
                (shadow == 0 && mask == 0)) return false;
        if (!new File(dirMask(files, titleId, shadow, mask), MAIN).isFile()) return false;
        try {
            return new String(Files.readAllBytes(stampMask(files, titleId, shadow, mask).toPath()),
                    StandardCharsets.UTF_8).equals(stampTextMask(shadow, mask, version));
        } catch (IOException e) { return false; }
    }
    static String[] argvMask(String romfs, int shadow, int mask, File out) {
        if (!validMask(mask)) throw new IllegalArgumentException("incompatible FPS patch combination");
        return new String[] {"--romfs", romfs, "--profile", Integer.toString(shadow),
                "--effects-mask", Integer.toString(mask), "--out", out.getPath()};
    }
    static String[] argv(String romfs, int profile, File out) {
        return argv(romfs, profile, 0, out);
    }
    static String[] argv(String romfs, int profile, int effect, File out) {
        return new String[] {"--romfs", romfs, "--profile", Integer.toString(profile),
                "--effect", Integer.toString(effect), "--out", out.getPath()};
    }
}
