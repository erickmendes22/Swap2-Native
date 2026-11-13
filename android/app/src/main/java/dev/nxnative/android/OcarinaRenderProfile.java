package dev.nxnative.android;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Explicit scene/output pairs from Banana's measured handheld scale-2 path.
 * Mode zero preserves the existing user configuration. Does not alter shader
 * libraries or guest texture dimensions; the engine chooses its own sizes.
 */
final class OcarinaRenderProfile {
    private OcarinaRenderProfile() {}
    static int checked(int mode) { return mode >= 0 && mode <= 2 ? mode : 0; }
    static String scale(int mode, String selected) {
        return mode == 1 ? "0.5" : mode == 2 ? "0.75" : selected;
    }
    static List<String> environment(int mode) {
        return checked(mode) == 0 ? Collections.emptyList()
                : Arrays.asList("DM_OPMODE=0", "DM_GRAPHICS_SCALE=2");
    }
}
