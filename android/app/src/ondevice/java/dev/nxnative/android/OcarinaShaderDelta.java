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

    /** Static, additive NVN2 update. This file does not change base inputs. */
    static List<String> vegetationKeys() {
        try {
            File manifest = new File(PackNative.repo(), "dm/games/" + TITLE + "/vegetation_shaders.tsv");
            ArrayList<String> keys = new ArrayList<>();
            for (String row : Files.readAllLines(manifest.toPath(), StandardCharsets.UTF_8)) {
                if (row.isBlank() || row.startsWith("#")) continue;
                String[] c = row.split("\t", -1);
                if (c.length != 4 || !c[0].matches("[0-9a-f]{16}")
                        || !(c[1].equals("task") || c[1].equals("mesh")) || keys.contains(c[0]))
                    throw new IOException("Invalid vegetation manifest");
                keys.add(c[0]);
            }
            if (keys.size() != 508) throw new IOException("Incomplete vegetation manifest");
            java.util.Collections.sort(keys);
            return List.copyOf(keys);
        } catch (IOException | RuntimeException e) {
            android.util.Log.w("OcarinaShaderDelta", "Vegetation manifest unavailable", e);
            return List.of();
        }
    }

    static boolean vegetationJob(Job job) {
        if (job == null || !TITLE.equals(job.titleId()) || job.hotKeys().size() != 508) return false;
        return new HashSet<>(job.hotKeys()).equals(new HashSet<>(vegetationKeys()));
    }

    static File overlay(Job job, boolean vegetation) {
        return new File(job.pack(), "shaders/" + (vegetation ? "vegetation" : "hot")
                + "/v-" + BuildConfig.NX_DMSH_VK_CHAIN + "/dmsh_vk.lib");
    }

    /**
     * GPU bottlenecks confirmed by the 720p Ocarina logs. The full old SPIR-V
     * library predates the already-integrated V21 raw vector / V22 last-range
     * translator. Compile these with the NEW translator only if the real
     * control+code pair was captured in gameplay, and only when its chain
     * differs from the base. Nothing is guessed or extracted from old SPIR-V.
     */
    private static final java.util.Set<String> HEAVY = java.util.Set.of(
            "066f5daf12e43c71", // foliage mesh
            "efaa4fa6a80ba719", // foliage task
            "5ad65c0eefd09c7f", // foliage fragment
            "9e6b00b050e30801"  // heavy compute
    );
    // Release 0.1.6 has actual captured NVN2 source for both profiled
    // 720p scene fragments. These must be eligible for a selective CSE
    // overlay EVEN when the 42k base and APK share the same Vulkan chain.
    // Their source pairing and hash are verified by vk_android_build.py.
    private static final java.util.Set<String> SCENE_FRAGMENTS = java.util.Set.of(
            "1e4d2630d24846d0", "00ce4088af2c8e12"
    );

    static List<String> keys(Job job) {
        if (job == null || !TITLE.equals(job.titleId())) return List.of();
        // Missing shaders can occur even with the current, complete 42k-key
        // library. That is exactly when a per-key repair is needed.
        Profile profile = Profile.of(TITLE);
        if (profile == null) return List.of();
        // The six new shader captures must be compared with the FIRST
        // complete compatible library, never a newer incomplete rebuild.
        File old = ShaderLibs.originalOcarina(job.pack(), TITLE,
                BuildConfig.NX_DMSH_VK_ABI, profile.shaderInputs);
        if (old == null) return List.of();
        ShaderLibs.Header header = ShaderLibs.header(old);
        if (header == null || profile == null || !header.fits(old.length())
                || !TITLE.equals(header.game) || !profile.shaderInputs.equals(header.inputs)
                || !(BuildConfig.NX_DMSH_VK_ABI.equals(header.abi)
                        || ShaderAbiCert.approved(TITLE, header.vkChain, header.abi, header.inputs))) return List.of();

        // First finish the missing original stages from the game's own
        // static containers, independent of captures or prior hot overlays.
        List<String> vegetation = vegetationKeys();
        if (!vegetation.isEmpty() && !alreadyRepaired(job, vegetation)) return vegetation;

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
        File hot = overlay(job, false);
        ShaderLibs.Header hotHeader = ShaderLibs.header(hot);
        boolean hotVerified = hotHeader != null && hotHeader.fits(hot.length())
                && TITLE.equals(hotHeader.game)
                && profile.shaderInputs.equals(hotHeader.inputs)
                && BuildConfig.NX_DMSH_VK_ABI.equals(hotHeader.abi);
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
                    // Repair actual missing keys AND selectively rebuild
                    // captured heavy mesh/task/fragment/compute for the new
                    // translator. Both kinds become the SAME atomic overlay.
                    // A heavy key that was already compiled by this exact
                    // Vulkan chain is not selected again.
                    boolean newSceneCse = SCENE_FRAGMENTS.contains(key) &&
                            (!hotVerified || !ShaderLibs.hasKey(hot, hotHeader, key));
                    if (!ShaderLibs.hasKey(old, header, key) ||
                            (!BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)
                                    && HEAVY.contains(key)) || newSceneCse)
                        missing.add(key);
                }
            } catch (IOException e) {
                android.util.Log.w("OcarinaShaderDelta", "Cannot inspect base shader index; preserving complete library", e);
                return List.of();
            }
            if (!missing.isEmpty()) {
                java.util.Collections.sort(missing);
                long heavy = missing.stream().filter(HEAVY::contains).count();
                android.util.Log.i("OcarinaShaderDelta",
                        "Preparing " + missing.size() + " captured selected shader sources ("
                                + heavy + " GPU-heavy candidates, remainder absent from base); "
                                + "original complete 42k-key library and pipeline cache remain unchanged");
                return List.copyOf(missing);
            }
        }
        return List.of();
    }
    /** The installed overlay already contains every missing captured key. */
    static boolean alreadyRepaired(Job job, List<String> keys) {
        if (job == null || keys.isEmpty()) return false;
        boolean vegetation = keys.size() == 508 && new HashSet<>(keys).equals(new HashSet<>(vegetationKeys()));
        File hot = overlay(job, vegetation);
        ShaderLibs.Header h = ShaderLibs.header(hot);
        Profile p = Profile.of(TITLE);
        if (h == null || p == null || !h.fits(hot.length())
                || vegetation && h.entries != 508
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
