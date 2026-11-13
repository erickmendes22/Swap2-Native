package dev.nxnative.android;

import java.util.Arrays;

public final class OcarinaRenderProfileJvmTest {
    private static void check(boolean b) { if (!b) throw new AssertionError("render profile mapping"); }
    public static void main(String[] args) {
        check(OcarinaRenderProfile.environment(0).isEmpty());
        check(OcarinaRenderProfile.scale(0,"0.3125").equals("0.3125"));
        for (int mode=1;mode<=2;mode++) {
            check(OcarinaRenderProfile.environment(mode).equals(Arrays.asList("DM_OPMODE=0","DM_GRAPHICS_SCALE=2")));
            double scale=Double.parseDouble(OcarinaRenderProfile.scale(mode,"unused"));
            check(1280*scale==(mode==1?640:960));
            check(720*scale==(mode==1?360:540));
        }
        check(OcarinaRenderProfile.checked(3)==3);
        check(OcarinaRenderProfile.direct720(3));
        check(!OcarinaRenderProfile.direct720(2));
        check(OcarinaRenderProfile.scale(3,"unused").equals("1.0"));
        check(OcarinaRenderProfile.environment(3).equals(Arrays.asList("DM_OPMODE=0","DM_GRAPHICS_SCALE=2")));
        check(1280*Double.parseDouble(OcarinaRenderProfile.scale(3,"unused"))==1280);
        check(720*Double.parseDouble(OcarinaRenderProfile.scale(3,"unused"))==720);
        for(int mode:new int[]{-1,4,Integer.MAX_VALUE}) {
            check(OcarinaRenderProfile.checked(mode)==0);
            check(OcarinaRenderProfile.environment(mode).isEmpty());
            check(OcarinaRenderProfile.scale(mode,"legacy").equals("legacy"));
        }
        System.out.println("render profiles: exact handheld/output/scene mapping and legacy preservation passed");
    }
}
