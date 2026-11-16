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

    /** Available before :pack starts; never load its native engine in the launcher. */
    static List<String> vegetationKeys() {
        return OcarinaVegetation.KEYS;
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

    /**
     * Repair ONLY genuine missing playable shader keys. A captured heavy
     * shader, a planned vegetation supplement, or a translator revision does
     * not make a key missing. Those are distinct optimization/update workflows.
     * The same complete base and the currently installed overlay must both
     * be checked before a capture enters this bounded, deterministic job.
     */
    static List<String> keys(Job job) {
        if (job == null || !TITLE.equals(job.titleId())) return List.of();
        Profile profile = Profile.of(TITLE);
        if (profile == null) return List.of();
        File old = ShaderLibs.originalOcarina(job.pack(), TITLE,
                BuildConfig.NX_DMSH_VK_ABI, profile.shaderInputs);
        if (old == null) return List.of();
        ShaderLibs.Header header = ShaderLibs.header(old);
        if (header == null || !header.fits(old.length())
                || !TITLE.equals(header.game) || !profile.shaderInputs.equals(header.inputs)
                || !(BuildConfig.NX_DMSH_VK_ABI.equals(header.abi)
                        || ShaderAbiCert.approved(TITLE, header.vkChain, header.abi, header.inputs)))
            return List.of();

        File hot = overlay(job, false);
        ShaderLibs.Header hotHeader = ShaderLibs.header(hot);
        boolean hotVerified = hotHeader != null && hotHeader.fits(hot.length())
                && TITLE.equals(hotHeader.game)
                && profile.shaderInputs.equals(hotHeader.inputs)
                && BuildConfig.NX_DMSH_VK_CHAIN.equals(hotHeader.vkChain)
                && BuildConfig.NX_DMSH_VK_ABI.equals(hotHeader.abi)
                && hotHeader.entries > 0 && hotHeader.entries <= 1024;

        File captures = new File(job.dir().getParentFile(), "nvn_shdump");
        File[] captureFiles = captures.listFiles((d, name) ->
                name.matches("[0-9a-f]{16}\\.code"));
        if (captureFiles == null || captureFiles.length == 0) return List.of();

        // Filesystem order is not stable across boots or APK updates.
        // A bounded first 128 missing keys always denotes the SAME keys,
        // not a different arbitrary subset after every repair attempt.
        java.util.Arrays.sort(captureFiles,
                java.util.Comparator.comparing(File::getName));
        // A source-verified mesh/task shader can still be impossible to
        // translate without its real draw-time pixel/task association.
        // The compiler records those deferred keys for this toolchain.
        // A NEW source capture or mesh_pairs.tsv update re-enables them;
        // otherwise the UI must not offer the same futile repair forever.
        long newestPairEvidence = new File(captures, "mesh_pairs.tsv").lastModified();
        for (File candidate : captureFiles) {
            newestPairEvidence = Math.max(newestPairEvidence, candidate.lastModified());
            String name = candidate.getName();
            File control = new File(captures, name.substring(0, 16) + ".ctl");
            newestPairEvidence = Math.max(newestPairEvidence, control.lastModified());
        }
        String compilerStamp = BuildConfig.NX_DMSH_CHAIN + "\t"
                + BuildConfig.NX_DMSH_VK_CHAIN;
        int deferred = 0;
        ArrayList<String> missing = new ArrayList<>();
        try {
            for (File f : captureFiles) {
                String key = f.getName().substring(0, 16);
                File ctl = new File(captures, key + ".ctl");
                if (!ctl.isFile() || ctl.length() < 0xd8 || ctl.length() > 65536
                        || f.length() < 4 || f.length() > (1 << 24)) continue;
                if (ShaderLibs.hasKey(old, header, key)) continue;
                if (hotVerified && ShaderLibs.hasKey(hot, hotHeader, key)) continue;
                File blocked = new File(captures, key + ".deferred");
                if (blocked.isFile() && blocked.length() <= 128
                        && blocked.lastModified() >= newestPairEvidence) {
                    List<String> stamp = Files.readAllLines(blocked.toPath(),
                            StandardCharsets.US_ASCII);
                    if (!stamp.isEmpty() && compilerStamp.equals(stamp.get(0))) {
                        deferred++;
                        continue;
                    }
                }
                missing.add(key);
                if (missing.size() == 128) break;
            }
        } catch (IOException e) {
            android.util.Log.w("OcarinaShaderDelta",
                    "Cannot inspect existing shader entries; refusing to guess missing keys", e);
            return List.of();
        }
        if (deferred > 0)
            android.util.Log.i("OcarinaShaderDelta",
                    deferred + " genuinely missing mesh/task shaders waiting "
                    + "for new real draw-time pairing evidence; not reoffering "
                    + "an identical failed preparation");
        if (!missing.isEmpty())
            android.util.Log.i("OcarinaShaderDelta",
                    "Repairing " + missing.size() + " source-captured keys absent from BOTH "
                    + "the complete playable library and verified hot overlay; no "
                    + "vegetation/optimization candidates or full-library rebuild");
        return List.copyOf(missing);
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
