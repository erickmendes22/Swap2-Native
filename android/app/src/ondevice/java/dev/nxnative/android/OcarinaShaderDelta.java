package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

/**
 * Explicitly scoped Vulkan shader updates for Ocarina. A change to the shader
 * translator alone does NOT prove that an old shader would produce the same
 * SPIR-V with the new tools. Only a reviewed manifest of affected shader keys
 * authorizes the small overlay; everything else follows the proven full/delta
 * manifest flow in vk_android_build.py.
 *
 * Manifest: dm/games/0400486024DEC000/vk_hot_delta.tsv
 * Each non-comment row is:
 * old Vulkan chain TAB new Vulkan chain TAB game inputs TAB ABI TAB key,key,...
 *
 * The old full library is never deleted, relabelled or modified. The runtime
 * checks the ABI and chooses overlaid keys, then falls back to that full lib.
 */
final class OcarinaShaderDelta {
    private OcarinaShaderDelta() {}

    private static final String TITLE = "0400486024DEC000";

    static List<String> keys(Job job) {
        if (job == null || !TITLE.equals(job.titleId())) return List.of();
        // Missing shaders can occur even with the current, complete 42k-key
        // library. That is exactly when a per-key repair is needed.
        File old = Pack.libraryOf(job.pack());
        if (old == null) old = Pack.playableLibrary(job.pack(), TITLE);
        if (old == null) return List.of();
        ShaderLibs.Header header = ShaderLibs.header(old);
        Profile profile = Profile.of(TITLE);
        if (header == null || profile == null || !header.fits(old.length())
                || !TITLE.equals(header.game) || !profile.shaderInputs.equals(header.inputs)
                || !(BuildConfig.NX_DMSH_VK_ABI.equals(header.abi)
                        || ShaderAbiCert.approved(TITLE, header.vkChain, header.abi, header.inputs))) return List.of();

        try {
            File manifest = new File(PackNative.repo(), "dm/games/" + TITLE + "/vk_hot_delta.tsv");
            if (manifest.isFile() && !BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)) {
                for (String line : Files.readAllLines(manifest.toPath(), StandardCharsets.UTF_8)) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] columns = line.split("\\t", -1);
                if (columns.length != 5 || !header.vkChain.equals(columns[0])
                        || !BuildConfig.NX_DMSH_VK_CHAIN.equals(columns[1])
                        || !profile.shaderInputs.equals(columns[2])
                        || !BuildConfig.NX_DMSH_VK_ABI.equals(columns[3])) continue;
                String[] parts = columns[4].split(",");
                ArrayList<String> keys = new ArrayList<>();
                HashSet<String> unique = new HashSet<>();
                for (String part : parts) {
                    String k = part.trim().toLowerCase(java.util.Locale.ROOT);
                    if (!k.matches("[0-9a-f]{16}") || !unique.add(k)) return List.of();
                    keys.add(k);
                }
                // This is a deliberate partial translation, not a manifest
                // pretending the entire 42k full library was rebuilt.
                if (!keys.isEmpty() && keys.size() <= 1024) return List.copyOf(keys);
                }
            }
        } catch (IOException | RuntimeException e) {
            android.util.Log.w("OcarinaShaderDelta", "Cannot use hot shader delta; full update remains available", e);
        }
        // The runtime records only shaders that were NOT found in the old
        // complete library. They are real guest control/code pairs, not
        // guessed SPIR-V. A new APK may translate just those captures
        // against its current translator while leaving 42k base entries
        // and the old Vulkan pipeline cache undisturbed. Python validates
        // every content hash, stage and source size before any compilation.
        File captures = new File(job.dir().getParentFile(), "nvn_shdump");
        File[] captureFiles = captures.listFiles((d, name) ->
                name.matches("[0-9a-f]{16}\\.code"));
        if (captureFiles != null && captureFiles.length > 0 && captureFiles.length <= 128) {
            ArrayList<String> missing = new ArrayList<>();
            try {
                for (File f : captureFiles) {
                    String key = f.getName().substring(0, 16);
                    File ctl = new File(captures, key + ".ctl");
                    if (!ctl.isFile() || ctl.length() < 0xd8 || ctl.length() > 65536
                            || f.length() < 4 || f.length() > (1 << 24)) continue;
                    // Captures may survive an APK update: only keys genuinely
                    // absent from the playable FULL library need translation.
                    // Keep all missing captures in each overlay rebuild, so
                    // new keys do not displace old hot-only keys.
                    if (!ShaderLibs.hasKey(old, header, key)) missing.add(key);
                }
            } catch (IOException e) {
                android.util.Log.w("OcarinaShaderDelta", "Cannot inspect base shader index; preserving complete library", e);
                return List.of();
            }
            if (!missing.isEmpty()) {
                java.util.Collections.sort(missing);
                android.util.Log.i("OcarinaShaderDelta",
                        "Preparing exactly " + missing.size() + " genuinely absent shaders as a partial overlay; 42k-key base unchanged");
                return List.copyOf(missing);
            }
        }
        return List.of();
    }
    /** The installed overlay already contains every missing captured key. */
    static boolean alreadyRepaired(Job job, List<String> keys) {
        if (job == null || keys.isEmpty()) return false;
        File hot = new File(job.pack(), "shaders/hot/v-" + BuildConfig.NX_DMSH_VK_CHAIN + "/dmsh_vk.lib");
        ShaderLibs.Header h = ShaderLibs.header(hot);
        Profile p = Profile.of(TITLE);
        if (h == null || p == null || !h.fits(hot.length())
                || !TITLE.equals(h.game) || !p.shaderInputs.equals(h.inputs)
                || !BuildConfig.NX_DMSH_VK_CHAIN.equals(h.vkChain)
                || !BuildConfig.NX_DMSH_VK_ABI.equals(h.abi)) return false;
        try {
            for (String key : keys) if (!ShaderLibs.hasKey(hot, h, key)) return false;
            return true;
        } catch (IOException e) {
            return false;
        }
    }

}
