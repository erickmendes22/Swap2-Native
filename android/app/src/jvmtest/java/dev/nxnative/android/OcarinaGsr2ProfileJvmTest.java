package dev.nxnative.android;

/** Checks the actual Java mode predicate, not a source-string approximation. */
public final class OcarinaGsr2ProfileJvmTest {
    private static void check(int mode, boolean eligible) {
        if (OcarinaRenderProfile.temporalGsr2(mode) != eligible)
            throw new AssertionError("Temporal GSR2 eligible=" + eligible + " for mode " + mode);
    }
    public static void main(String[] args) {
        check(0,false); // existing config; not a known 720p destination
        check(1,true);  // Banana 360p->720p
        check(2,true);  // Banana 540p->720p
        check(3,false); // 720p direct has no low-resolution scene to upscale
        check(-1,false);
        check(99,false);
        System.out.println("Ocarina GSR2 profile gating: 6 cases passed");
    }
}
