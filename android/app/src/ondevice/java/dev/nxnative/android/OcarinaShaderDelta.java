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
        if (job == null || !TITLE.equals(job.titleId()) || Pack.libraryOf(job.pack()) != null) return List.of();
        File old = Pack.playableLibrary(job.pack(), TITLE);
        if (old == null) return List.of();
        ShaderLibs.Header header = ShaderLibs.header(old);
        Profile profile = Profile.of(TITLE);
        if (header == null || profile == null || !header.fits(old.length())
                || !TITLE.equals(header.game) || !profile.shaderInputs.equals(header.inputs)
                || !(BuildConfig.NX_DMSH_VK_ABI.equals(header.abi)
                        || ShaderAbiCert.approved(TITLE, header.vkChain, header.abi, header.inputs))) return List.of();

        try {
            File manifest = new File(PackNative.repo(), "dm/games/" + TITLE + "/vk_hot_delta.tsv");
            if (!manifest.isFile()) return List.of();
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
        } catch (IOException | RuntimeException e) {
            android.util.Log.w("OcarinaShaderDelta", "Cannot use hot shader delta; full update remains available", e);
        }
        return List.of();
    }
}
