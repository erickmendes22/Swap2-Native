package dev.nxnative.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;
import java.util.Locale;

/**
 * The shader libraries of a pack folder (shaders/v-&lt;V&gt;/dmsh_vk.lib) and their delta update (android/SHADERS.md#delta-updates), as the launcher decides them:
 * <ul>
 * <li>{@link #playable}: a library of another version the host plays while this version's library is being made: its header names the game and carries this APK's
 * DMSH_VK_ABI, the rule of the replay's own choice (vka_shader.c lib_load, vka_shlib_check); the newest such one, as the replay takes it.</li>
 * <li>{@link #toTranslate}: how many shaders the update translates from the older libraries the pack has, from the profile's delta manifest "from" rows (Profile.delta),
 * and {@link #minutes} the time that takes on the phone.</li>
 * <li>{@link #restamp}: an older library that is this version's byte for byte but for the header's version and abi (the manifest's "stamp" rows, Profile.stamp) becomes
 * this version's library by rewriting those fields: no update job at all (android/SHADERS.md#restamp).</li>
 * </ul>
 * No Android classes: the JVM test (android/app/src/jvmtest ShaderLibsJvmTest, dm/tools/tests/test_android_shader_delta.py) runs it on the Mac.
 */
final class ShaderLibs {
    private ShaderLibs() {}

    static final int MAGIC = 0x4B56534D;   // dmsh_abi_vk.h DMSH_VK_LIB_MAGIC, DMSH_VK_LIB_VERSION
    static final int VERSION = 1;

    // The first complete Ocarina library (APK run 42917509914, 2026-11-10)
    // used this VK chain and the same audited binary ABI as v0.1.6. Never
    // rename its header to today's tool digest or accept a small hot overlay
    // as the full base merely because its version string is familiar.
    static final String OCARINA_BASE_VK = "b6b21fb5753a";
    static final long OCARINA_BASE_MIN_ENTRIES = 40000;

    static boolean trustedOcarinaBase(String titleId, String vkChain,
                                     String abi, String inputs, long entries,
                                     String expectedAbi, String expectedInputs) {
        return "0400486024DEC000".equals(titleId)
                && OCARINA_BASE_VK.equals(vkChain)
                && expectedAbi != null && expectedAbi.equals(abi)
                && expectedInputs != null && !"unknown".equals(expectedInputs)
                && expectedInputs.equals(inputs)
                && entries >= OCARINA_BASE_MIN_ENTRIES;
    }

    static File trustedOcarinaBase(File pack, String titleId, String abi,
                                  String inputs) {
        File file = new File(pack, "shaders/v-" + OCARINA_BASE_VK + "/dmsh_vk.lib");
        Header h = header(file);
        return h != null && h.fits(file.length())
                && trustedOcarinaBase(titleId, h.vkChain, h.abi, h.inputs,
                                      h.entries, abi, inputs) ? file : null;
    }

    static final int HEADER_SIZE = 128, ENTRY_SIZE = 64, BIND_SIZE = 24, MOD_SIZE = 16;   // dmsh_abi_vk.h DMSH_VK_HEADER_SIZE, _ENTRY_SIZE, _BIND_SIZE, _MOD_SIZE

    /**
     * What the launcher reads of a library's header (dmsh_vk_header: chain at 8, vk_chain at 24, game at 40, inputs at 56, abi at 116, 12 characters; the
     * tables: entry_count/off at 72/76, bind_count/off at 80/84, mod_count/off at 88/92, blob_off at 96 and blob_size at 104, both u64)
     */
    static final class Header {
        String chain, vkChain, game, inputs, abi;
        long entries, entryOff, bindCount, bindOff, modCount, modOff, blobOff, blobSize;

        /** Whether every table and the blob lie inside a file of this size (a library cut short, or a header of another file, does not) */
        boolean fits(long fileSize) {
            return table(entries, entryOff, ENTRY_SIZE, fileSize) && table(bindCount, bindOff, BIND_SIZE, fileSize) && table(modCount, modOff, MOD_SIZE, fileSize)
                    && blobOff >= HEADER_SIZE && blobSize >= 0 && blobOff <= fileSize && blobSize <= fileSize - blobOff;
        }

        private static boolean table(long count, long off, int size, long fileSize) {
            return count == 0 || off >= HEADER_SIZE && off <= fileSize && count * size <= fileSize - off;
        }
    }

    private static String text(byte[] h, int off, int n) {
        int e = off;
        while (e < off + n && h[e] != 0) e++;
        return new String(h, off, e - off, StandardCharsets.US_ASCII);
    }

    private static long u32(byte[] h, int o) { return (h[o] & 0xffL) | (h[o + 1] & 0xffL) << 8 | (h[o + 2] & 0xffL) << 16 | (h[o + 3] & 0xffL) << 24; }

    /** The header of a library file; null when it is not one this app reads (short, another magic or format) */
    static Header header(File lib) {
        byte[] h = new byte[HEADER_SIZE];
        try (RandomAccessFile f = new RandomAccessFile(lib, "r")) {
            f.readFully(h);
        } catch (IOException e) {
            return null;
        }
        return header(h);
    }

    /** The same, of a library's first 128 bytes (ShaderZip reads them from a zip before anything is written) */
    static Header header(byte[] h) {
        if (h.length < HEADER_SIZE) return null;
        int magic = (h[0] & 0xff) | (h[1] & 0xff) << 8 | (h[2] & 0xff) << 16 | (h[3] & 0xff) << 24, version = (h[4] & 0xff) | (h[5] & 0xff) << 8 | (h[6] & 0xff) << 16 | (h[7] & 0xff) << 24;
        if (magic != MAGIC || version != VERSION) return null;
        Header r = new Header();
        r.chain = text(h, 8, 16);
        r.vkChain = text(h, 24, 16);
        r.game = text(h, 40, 16);
        r.inputs = text(h, 56, 16);
        String a = text(h, 116, 12);
        r.abi = a.matches("[0-9a-f]{12}") ? a : "";   // zero in a library made before the field: played by its own version only
        r.entries = u32(h, 72);
        r.entryOff = u32(h, 76);
        r.bindCount = u32(h, 80);
        r.bindOff = u32(h, 84);
        r.modCount = u32(h, 88);
        r.modOff = u32(h, 92);
        r.blobOff = u32(h, 96) | u32(h, 100) << 32;   // a u64 above 2^63 reads negative: fits refuses it
        r.blobSize = u32(h, 104) | u32(h, 108) << 32;
        return r;
    }

    /**
     * Binary-search the sorted guest shader keys in a complete or partial Vulkan
     * library without loading its compressed SPIR-V. A captured missing shader
     * must not override a key that the currently playable base already has.
     */
    static boolean hasKey(File lib, Header h, String key) throws IOException {
        if (h == null || !h.fits(lib.length()) || !key.matches("[0-9a-f]{16}")) return false;
        long wanted = Long.parseUnsignedLong(key, 16);
        try (RandomAccessFile f = new RandomAccessFile(lib, "r")) {
            long lo = 0, hi = h.entries;
            while (lo < hi) {
                long mid = lo + ((hi - lo) >>> 1);
                f.seek(h.entryOff + mid * ENTRY_SIZE);
                // Vulkan library fields are little-endian; keys compare as
                // unsigned 64-bit integers, just like vka_shlib_find.
                long found = Long.reverseBytes(f.readLong());
                int cmp = Long.compareUnsigned(found, wanted);
                if (cmp == 0) return true;
                if (cmp < 0) lo = mid + 1;
                else hi = mid;
            }
        }
        return false;
    }

    /** The v-&lt;V&gt; folders of a pack folder that hold a library */
    private static File[] libraries(File packDir) {
        File[] l = new File(packDir, "shaders").listFiles(f -> f.getName().startsWith("v-") && new File(f, "dmsh_vk.lib").isFile());
        return l == null ? new File[0] : l;
    }

    /**
     * The library of another version than current the host plays (the newest one whose header names titleId and carries abi), null when none. current: this APK's
     * DMSH_VK_CHAIN (its own library is the launcher's usual check, not this one); abi: its DMSH_VK_ABI
     */
    static File playable(File packDir, String titleId, String current, String abi) {
        if (abi == null || !abi.matches("[0-9a-f]{12}")) return null;
        File best = null;
        for (File d : libraries(packDir)) {
            if (d.getName().equals("v-" + current)) continue;
            File lib = new File(d, "dmsh_vk.lib");
            Header h = header(lib);
            if (h == null || !h.fits(lib.length()) || !titleId.equals(h.game)) continue;
            // Ocarina hot shader compilations contain only a few entries:
            // they can never be chosen as the mandatory full fallback.
            if (Prefs.OCARINA_TITLE.equals(titleId) && h.entries <= 1024) continue;
            // A different ABI may use the old full library only when both
            // headers were compared at build time and certified additive-safe.
            // An arbitrary ABI/header change is never treated as compatible.
            if (!abi.equals(h.abi) && !ShaderAbiCert.approved(titleId, h.vkChain, h.abi, h.inputs)) continue;
            if (best == null || lib.lastModified() > best.lastModified()) best = lib;
        }
        return best;
    }

    /**
     * Stable Ocarina base: the earliest verified complete 40k+ library
     * matching the installed game's shader inputs and a certified GPU ABI.
     * Partial new compilations belong in shaders/hot/ and never displace it.
     * Selection reads headers only; it never copies or invalidates shaders.
     */
    static File originalOcarina(File packDir, String titleId, String abi, String inputs) {
        if (!Prefs.OCARINA_TITLE.equals(titleId)) return null;
        File oldest = null;
        for (File d : libraries(packDir)) {
            File lib = new File(d, "dmsh_vk.lib");
            Header h = header(lib);
            if (h == null || !h.fits(lib.length()) || h.entries < 40000
                    || !titleId.equals(h.game) || !inputs.equals(h.inputs)
                    || !(abi.equals(h.abi) || ShaderAbiCert.approved(titleId, h.vkChain, h.abi, h.inputs)))
                continue;
            if (oldest == null || lib.lastModified() < oldest.lastModified())
                oldest = lib;
        }
        return oldest;
    }

    /**
     * A library of another version made before the header's abi field (no ABI: whether the host reads it the same is not known), the newest; null when none. The host plays
     * it as a last resort, after any library of its ABI (vka_shader.c lib_load), with a warning instead of drawing nothing; the launcher does not block Play on it and
     * suggests one more shader update, after which updates are deltas of the same ABI
     */
    static File legacy(File packDir, String titleId, String current) {
        File best = null;
        for (File d : libraries(packDir)) {
            if (d.getName().equals("v-" + current)) continue;
            File lib = new File(d, "dmsh_vk.lib");
            Header h = header(lib);
            if (h == null || !titleId.equals(h.game) || !h.abi.isEmpty()) continue;
            if (best == null || lib.lastModified() > best.lastModified()) best = lib;
        }
        return best;
    }

    /** The warning for a game played on such a library */
    static final String LEGACY_WARNING = "This game's shaders were made before versioned shader updates, so this app version cannot update them in part. "
            + "You can keep playing on them, but updating the shaders once more with Prepare shaders is suggested: after that, shader fixes arrive as small incremental updates.";

    /** The versions of the libraries of titleId's game a pack folder has, other than current (what a delta update can start from) */
    static List<String> older(File packDir, String titleId, String current) {
        List<String> out = new java.util.ArrayList<>();
        for (File d : libraries(packDir)) {
            String v = d.getName().substring(2);
            Header h = header(new File(d, "dmsh_vk.lib"));
            if (!v.equals(current) && h != null && titleId.equals(h.game)) out.add(v);
        }
        return out;
    }

    /**
     * How many shaders a delta update translates when the pack has the older versions given: the fewest of the profile's "from" rows (delta: "version=count,…", from the
     * manifest's from rows) for those versions; -1 when the manifest has none of them (the update then translates as many as a full build, or more as the tool finds)
     */
    static int toTranslate(String delta, List<String> versions) {
        int best = -1;
        if (delta == null) return -1;
        for (String row : delta.split(",")) {
            int eq = row.indexOf('=');
            if (eq <= 0 || !versions.contains(row.substring(0, eq).trim())) continue;
            try {
                int n = Integer.parseInt(row.substring(eq + 1).trim());
                if (n >= 0 && (best < 0 || n < best)) best = n;
            } catch (NumberFormatException e) {
                // a malformed row is not a measurement
            }
        }
        return best;
    }

    /**
     * The phone's time for a shaders step that translates n shaders, as "a-b" minutes: the split of the dump (4-8 min, android/ONDEVICE.md "Time and power"), each shader
     * translated (45-80 ms: the step's 20-35 min for DKB's 22,852 less the split), and the library written and checked (about 1 min)
     */
    static int[] minutes(int n) {
        int lo = 4 + 1 + (int) Math.round(n * 0.045 / 60), hi = 8 + 1 + (int) Math.ceil(n * 0.080 / 60);
        return new int[] {lo, Math.max(hi, lo + 1)};
    }

    // ---- Restamp: the manifest's "stamp" rows (vk_android_delta.py STAMP_FIELDS, restamped_header) ----

    static final int STAMP_VERSION_AT = 24, STAMP_VERSION_LEN = 16, STAMP_ABI_AT = 116, STAMP_ABI_LEN = 12;
    private static final Object RESTAMP = new Object();   // one restamp at a time (two cards may name the same pack)

    /**
     * Writes this version's library (shaders/v-&lt;current&gt;/) from an older one of the pack that a "stamp" row names, when the pack has none of its own: the older file's
     * SHA-256 must be the row's first hash; it is copied with its header's version set to current and its abi to abi, into shaders/.restamp-&lt;current&gt;/ with the
     * older folder's inputs.tsv, and moved in by rename only when the copy's SHA-256 is the row's second hash (the Mac's library of this version, byte for byte). The
     * older library stays. stamps: "version:old SHA-256:new SHA-256", ';' between them. → the older version taken over, null when none was (nothing changed then)
     */
    static String restamp(File packDir, String titleId, String current, String abi, String stamps) {
        if (stamps == null || stamps.isEmpty() || current == null || !current.matches("[0-9a-f]{12}") || abi == null || !abi.matches("[0-9a-f]{12}")) return null;
        File sh = new File(packDir, "shaders"), want = new File(sh, "v-" + current), tmp = new File(sh, ".restamp-" + current);
        synchronized (RESTAMP) {
            if (new File(want, "dmsh_vk.lib").isFile()) return null;
            for (String row : stamps.split(";")) {
                String[] c = row.trim().split(":");
                if (c.length != 3 || !c[0].matches("[0-9a-f]{12}") || c[0].equals(current) || !c[1].matches("[0-9a-f]{64}") || !c[2].matches("[0-9a-f]{64}")) continue;
                File from = new File(sh, "v-" + c[0]), lib = new File(from, "dmsh_vk.lib");
                Header h = header(lib);
                if (h == null || !titleId.equals(h.game)) continue;
                try {
                    if (!c[1].equals(sha256(lib))) continue;   // not the library the Mac compared (damaged, or made by other tools)
                    if (sh.getUsableSpace() < lib.length() + (64L << 20)) return null;
                    deleteTree(tmp);
                    if (!tmp.mkdirs()) continue;
                    if (!c[2].equals(copyStamped(lib, new File(tmp, "dmsh_vk.lib"), current, abi))) { deleteTree(tmp); continue; }
                    File in = new File(from, "inputs.tsv");
                    if (in.isFile()) Files.copy(in.toPath(), new File(tmp, "inputs.tsv").toPath());
                    if (want.isDirectory()) want.delete();   // an empty folder of this version (a stopped job's): only an empty one goes
                    if (!tmp.renameTo(want)) { deleteTree(tmp); continue; }
                    return c[0];
                } catch (IOException | NoSuchAlgorithmException e) {
                    deleteTree(tmp);
                }
            }
        }
        return null;
    }

    private static String hex(byte[] d) {
        StringBuilder b = new StringBuilder();
        for (byte x : d) b.append(String.format(Locale.ROOT, "%02x", x & 0xff));
        return b.toString();
    }

    static String sha256(File f) throws IOException, NoSuchAlgorithmException {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] buf = new byte[1 << 20];
        try (InputStream in = new FileInputStream(f)) {
            for (int n; (n = in.read(buf)) > 0; ) md.update(buf, 0, n);
        }
        return hex(md.digest());
    }

    /** Copies a library with its version and abi fields set (as vk_android_delta.py restamped_header), synced; → the copy's SHA-256 */
    private static String copyStamped(File src, File dst, String version, String abi) throws IOException, NoSuchAlgorithmException {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] buf = new byte[1 << 20];
        try (InputStream in = new FileInputStream(src); FileOutputStream out = new FileOutputStream(dst)) {
            byte[] h = new byte[128];
            for (int got = 0, n; got < h.length; got += n) if ((n = in.read(h, got, h.length - got)) < 0) throw new IOException("short library");
            java.util.Arrays.fill(h, STAMP_VERSION_AT, STAMP_VERSION_AT + STAMP_VERSION_LEN, (byte) 0);
            byte[] v = version.getBytes(StandardCharsets.US_ASCII);
            System.arraycopy(v, 0, h, STAMP_VERSION_AT, Math.min(v.length, STAMP_VERSION_LEN));
            java.util.Arrays.fill(h, STAMP_ABI_AT, STAMP_ABI_AT + STAMP_ABI_LEN, (byte) 0);
            byte[] a = abi.getBytes(StandardCharsets.US_ASCII);
            System.arraycopy(a, 0, h, STAMP_ABI_AT, Math.min(a.length, STAMP_ABI_LEN));
            out.write(h); md.update(h);
            for (int n; (n = in.read(buf)) > 0; ) { out.write(buf, 0, n); md.update(buf, 0, n); }
            out.getFD().sync();
        }
        return hex(md.digest());
    }

    private static void deleteTree(File f) {
        File[] l = f.listFiles();
        if (l != null) for (File x : l) deleteTree(x);
        f.delete();
    }

    static String minutesText(int n) {
        int[] m = minutes(n);
        return String.format(Locale.ROOT, "about %d-%d minutes", m[0], m[1]);
    }

    /**
     * A whole Prepare (the code rewritten, then every shader of the game's map, n: Profile.shaderTotal) as "a-b" minutes: the rewrite's 2-5 minutes on the phone
     * (Donkey Kong Bananza 74 s, ONDEVICE.md "Phone test status") and the shaders step as {@link #minutes}. DKB (22,852 shaders) 24-45, Mario Kart World (11,604) 16-30
     */
    static String jobMinutesText(int n) {
        int[] m = minutes(n);
        return String.format(Locale.ROOT, "about %d-%d minutes", m[0] + 2, m[1] + 5);
    }
}
