package dev.nxnative.android;

import java.util.Arrays;
import java.util.Locale;

/** Game-specific presentation of the existing host controller ABI. No timed macros or inferred game state. */
final class TouchProfile {
    static final String AUTO = "auto", CLASSIC = "classic", BANANZA = "bananza", RACING = "racing", ZELDA = "zelda-oot";
    static final String DK = "040074A01BF12000";
    static final String MKW = "0400C3F00006E000";
    static final String OOT = "0400486024DEC000";

    static String gameKey(String id) {
        return id != null && id.matches("(?i)[0-9a-f]{16}") ? id.toUpperCase(Locale.ROOT) : "generic";
    }

    static String resolve(String id, String choice) {
        if (CLASSIC.equals(choice)) return CLASSIC;
        return DK.equals(gameKey(id)) ? BANANZA : MKW.equals(gameKey(id)) ? RACING : OOT.equals(gameKey(id)) ? ZELDA : CLASSIC;
    }

    static String[] choices(String id) {
        String specific = resolve(id, AUTO);
        return CLASSIC.equals(specific) ? new String[] {AUTO, CLASSIC} : new String[] {AUTO, specific, CLASSIC};
    }

    static Control[] racing(boolean autoAccelerate) {
        java.util.ArrayList<Control> c = new java.util.ArrayList<>();
        c.add(new Control("steering", "", 1, 0, 0, -1, .14f, .76f, 52));
        c.add(new Control("camera", "", 1, 0, 1, -1, .62f, .82f, 34));
        if (!autoAccelerate) c.add(button("accelerate", "A", 1, -1, .93f, .79f, 30));
        c.add(button("brake", "B", 2, -1, .79f, .82f, 28));
        c.add(button("drift", "R", 128, -1, .92f, .55f, 30));
        c.add(button("jump", "R", 128, -1, .78f, .55f, 24));
        c.add(button("item", "L", 64, -1, .12f, .46f, 30));
        c.add(button("rear_view", "X", 4, -1, .28f, .49f, 24));
        c.add(button("map", "Y", 8, -1, .32f, .12f, 24));
        c.add(button("pause", "+", 1024, -1, .94f, .12f, 24));
        c.add(button("minus", "\u2212", 2048, -1, .80f, .12f, 24));
        c.add(button("rewind", "\u2193", 32768, -1, .14f, .23f, 24));
        return c.toArray(new Control[0]);
    }

    static String layoutKey(String id, String profile, String screen) {
        return "v1/" + gameKey(id) + "/" + profile + "/" + screen;
    }

    /** The Zelda profile's controls and stable IDs in their old placement: landscape layouts customized before the anniversary skin (ZELDA40) keep it until Reset. The icon indices address only the old s2_zelda_controls atlas, never the anniversary one. */
    static Control[] zelda() {
        return new Control[] {
            new Control("move", "", 1, 0, 0, -1, .13f, .78f, 48),
            new Control("camera", "", 1, 0, 1, -1, .64f, .80f, 40),
            button("face_b", "B", 2, 0, .80f, .68f, 29),
            button("face_a", "A", 1, 2, .94f, .68f, 29),
            button("slot_x", "X", 4, 5, .87f, .48f, 24),
            button("slot_y", "Y", 8, 10, .87f, .88f, 24),
            button("trigger_right", "ZR", 512, 1, .90f, .28f, 28),
            button("trigger_left", "ZL", 256, 3, .08f, .47f, 24),
            button("shoulder_right", "R", 128, 4, .23f, .55f, 24),
            button("shoulder_left", "L", 64, 8, .08f, .28f, 24),
            button("minus", "\u2212", 2048, 9, .32f, .10f, 24),
            button("plus", "+", 1024, 14, .94f, .09f, 24),
            new Control("directions", "", 2, 0xf000, 0, -1, .23f, .28f, 34),
            button("left_click", "L3", 16, -1, .27f, .88f, 24),
            button("right_click", "R3", 32, -1, .74f, .94f, 24),
        };
    }

    // ---- The sprite renderer's skins: the standard skin v2 (docs/SWAP2-NATIVE-STANDARD-TOUCH-v2.md; Classic) and Zelda's 40th anniversary skin
    // (docs/SWAP2-NATIVE-ZELDA40-TOUCH-v1.md; the Zelda profile). A Skin holds what differs between them: atlas size, measured rectangles, landscape placement,
    // stick and D-pad geometry and palette. TouchControls holds the decoded bitmaps and draws every skin through the same path ----
    /** Sprite IDs of every skin's atlas, in the order of its manifest (standard-touch-v2/sprites-v2.json, zelda-40/sprites-v1.json; the touch test compares both). */
    private static final String[] SPRITE_IDS = {
        "x", "y", "a", "b", "plus", "minus", "l", "zl", "r", "zr", "l3", "r3", "up", "down", "left", "right",
        "capture", "home", "c", "visibility", "left_stick_base", "left_stick_cap", "right_stick_base", "right_stick_cap", "settings",
    };
    /** drawable-nodpi/s2_standard_controls_v2.png: measured source rectangles (left, top, right exclusive, bottom exclusive: android.graphics.Rect), copied from sprites-v2.json. */
    private static final int[][] STANDARD_SPRITE_RECTS = {
        {59, 55, 231, 231},
        {299, 56, 471, 231},
        {538, 55, 710, 231},
        {778, 55, 950, 231},
        {1040, 74, 1179, 215},
        {82, 316, 207, 442},
        {265, 319, 495, 433},
        {505, 319, 738, 433},
        {747, 319, 980, 433},
        {990, 319, 1224, 433},
        {61, 561, 230, 671},
        {301, 561, 469, 671},
        {538, 526, 712, 703},
        {775, 525, 950, 703},
        {1014, 525, 1190, 703},
        {61, 762, 236, 939},
        {298, 762, 471, 939},
        {536, 762, 710, 939},
        {772, 762, 947, 939},
        {1010, 762, 1185, 939},
        {30, 979, 265, 1224},
        {303, 1022, 467, 1189},
        {503, 979, 743, 1224},
        {777, 1022, 944, 1189},
        {1022, 1023, 1179, 1184},
    };
    static final int STANDARD_ATLAS_SIZE = 1254;
    /** drawable-nodpi/s2_zelda40_controls.png: the same convention, copied from zelda-40/sprites-v1.json. The atlas is not square and not a uniform grid. */
    private static final int[][] ZELDA40_SPRITE_RECTS = {
        {53, 63, 242, 255},
        {294, 63, 483, 255},
        {535, 63, 724, 255},
        {777, 63, 967, 255},
        {1019, 63, 1207, 254},
        {47, 304, 231, 491},
        {264, 337, 497, 459},
        {508, 337, 743, 459},
        {755, 337, 992, 459},
        {1005, 337, 1240, 459},
        {48, 564, 242, 677},
        {290, 563, 485, 677},
        {534, 526, 723, 717},
        {778, 526, 967, 717},
        {1022, 526, 1211, 717},
        {44, 745, 235, 940},
        {287, 745, 478, 941},
        {532, 745, 723, 940},
        {775, 745, 967, 942},
        {1023, 745, 1215, 941},
        {26, 968, 266, 1207},
        {288, 988, 486, 1190},
        {509, 968, 750, 1208},
        {774, 988, 976, 1193},
        {1013, 985, 1222, 1195},
    };
    static final int ZELDA40_ATLAS_W = 1263, ZELDA40_ATLAS_H = 1245;

    /** The sprite ID that draws a control (a button's single guest bit, a stick's base), null for the D-pad (four sprites) or an unknown combination. */
    static String spriteIdFor(int kind, long buttons, int stick) {
        if (kind == 1) return stick == 0 ? "left_stick_base" : "right_stick_base";
        if (kind != 0) return null;
        switch ((int) buttons) {
            case 1: return "a";
            case 2: return "b";
            case 4: return "x";
            case 8: return "y";
            case 16: return "l3";
            case 32: return "r3";
            case 64: return "l";
            case 128: return "r";
            case 256: return "zl";
            case 512: return "zr";
            case 1024: return "plus";
            case 2048: return "minus";
            case 4096: return "left";
            case 8192: return "up";
            case 16384: return "right";
            case 32768: return "down";
            default: return null;
        }
    }

    static final int STANDARD_APP = 3;   // drawn and handled by the launcher, never sent to the host's layout
    static final float STANDARD_REF_W = 1913, STANDARD_REF_H = 822;
    static final int ANCHOR_LEFT = 0, ANCHOR_RIGHT = 1, ANCHOR_CENTER = 2;
    /** Cap travel over its base, as a fraction of the base's half extent: 26 of 110 reference px (left), 22 of 93 (right). */
    static final float STANDARD_STICK_TRAVEL = 26f / 110f, STANDARD_RIGHT_STICK_TRAVEL = 22f / 93f;
    /** Cap size against its base: 145 of 220 (left), 122 of 186 (right). */
    static final float STANDARD_CAP = 145f / 220f, STANDARD_RIGHT_CAP = 122f / 186f;
    /** D-pad: four 84px sprites 79px from the diamond's centre, inside a 121px half extent (layout-reference-v2.json). */
    static final float STANDARD_DPAD_OFFSET = 79f / 121f, STANDARD_DPAD_SPRITE = 42f / 121f;

    /** One placed element of a skin's landscape layout, from its layout reference (centre and half extents in reference px). The action is the control's stable ID. */
    static final class StandardItem {
        final String action, sprite;
        final int kind, stick, anchor;
        final long buttons;
        final float x, y, halfW, halfH;
        StandardItem(String action, String sprite, int kind, long buttons, int stick, int anchor, float x, float y, float halfW, float halfH) {
            this.action = action; this.sprite = sprite; this.kind = kind; this.buttons = buttons; this.stick = stick; this.anchor = anchor;
            this.x = x; this.y = y; this.halfW = halfW; this.halfH = halfH;
        }
    }

    private static StandardItem std(String sprite, long bit, int anchor, float x, float y, float w, float h) {
        return new StandardItem(sprite, sprite, 0, bit, 0, anchor, x, y, w / 2, h / 2);
    }

    /** Capture, Home and C are left out: the 16-button guest ABI (dm_input.h) has no bits for them; their sprites stay unused. */
    private static final StandardItem[] STANDARD = {
        std("zl", 256, ANCHOR_LEFT, 133, 86, 162, 72),
        std("l", 64, ANCHOR_LEFT, 316, 86, 162, 72),
        std("minus", 2048, ANCHOR_LEFT, 477, 90, 54, 54),
        std("r", 128, ANCHOR_RIGHT, 1596, 86, 162, 72),
        std("zr", 512, ANCHOR_RIGHT, 1780, 86, 162, 72),
        std("plus", 1024, ANCHOR_RIGHT, 1435, 90, 54, 54),
        new StandardItem("left_stick", "left_stick_base", 1, 0, 0, ANCHOR_LEFT, 166, 285, 110, 110),
        std("l3", 16, ANCHOR_LEFT, 343, 300, 82, 50),
        new StandardItem("dpad", "", 2, 0xf000, 0, ANCHOR_LEFT, 181.5f, 541, 121, 121),
        std("x", 4, ANCHOR_RIGHT, 1716, 201, 90, 90),
        std("y", 8, ANCHOR_RIGHT, 1631, 283, 90, 90),
        std("a", 1, ANCHOR_RIGHT, 1801, 283, 90, 90),
        std("b", 2, ANCHOR_RIGHT, 1716, 365, 90, 90),
        new StandardItem("right_stick", "right_stick_base", 1, 0, 1, ANCHOR_RIGHT, 1745, 542, 93, 93),
        std("r3", 32, ANCHOR_RIGHT, 1585, 543, 82, 50),
        new StandardItem("visibility", "visibility", STANDARD_APP, 0, 0, ANCHOR_CENTER, 956.5f, 125, 28, 28),
        new StandardItem("settings", "settings", STANDARD_APP, 0, 0, ANCHOR_CENTER, 956.5f, 755, 24, 24),
    };

    // Zelda 40th anniversary: zelda-40/layout-reference-v1.json at 1912x823, with the Zelda profile's own control IDs (zelda()) and bits
    static final float ZELDA40_REF_W = 1912, ZELDA40_REF_H = 823;
    /** Both bases are 244 reference units across and both caps 162; a cap travels up to 28 units, which keeps it inside its base. */
    static final float ZELDA40_CAP = 162f / 244f, ZELDA40_STICK_TRAVEL = 28f / 122f;
    /** The four D-pad sprites' measured centres (up, right, down, left) and their 90-unit size; the D-pad region is their bounding box's centre and half extent. */
    private static final float[][] ZELDA40_DPAD = {{185, 462}, {266, 540}, {185, 619}, {101, 540}};
    static final float ZELDA40_DPAD_SIZE = 90;

    private static StandardItem zb(String action, String sprite, long bit, int anchor, float x, float y, float w, float h) {
        return new StandardItem(action, sprite, 0, bit, 0, anchor, x, y, w / 2, h / 2);
    }

    /** Capture, Home and C stay hidden (enabled_initially false): no guest bits. */
    private static final StandardItem[] ZELDA40 = {
        zb("trigger_left", "zl", 256, ANCHOR_LEFT, 131, 71, 192, 72),
        zb("shoulder_left", "l", 64, ANCHOR_LEFT, 334, 71, 176, 72),
        zb("minus", "minus", 2048, ANCHOR_LEFT, 485, 74, 60, 60),
        zb("shoulder_right", "r", 128, ANCHOR_RIGHT, 1578, 71, 176, 72),
        zb("trigger_right", "zr", 512, ANCHOR_RIGHT, 1780, 71, 192, 72),
        zb("plus", "plus", 1024, ANCHOR_RIGHT, 1425, 74, 60, 60),
        new StandardItem("move", "left_stick_base", 1, 0, 0, ANCHOR_LEFT, 155, 270, 122, 122),
        zb("left_click", "l3", 16, ANCHOR_LEFT, 343, 273, 100, 54),
        new StandardItem("directions", "", 2, 0xf000, 0, ANCHOR_LEFT, 183.5f, 540.5f, 127.5f, 127.5f),
        zb("slot_x", "x", 4, ANCHOR_RIGHT, 1693, 187, 90, 90),
        zb("slot_y", "y", 8, ANCHOR_RIGHT, 1607, 268, 90, 90),
        zb("face_a", "a", 1, ANCHOR_RIGHT, 1778, 268, 90, 90),
        zb("face_b", "b", 2, ANCHOR_RIGHT, 1693, 350, 90, 90),
        new StandardItem("camera", "right_stick_base", 1, 0, 1, ANCHOR_RIGHT, 1621, 541, 122, 122),
        zb("right_click", "r3", 32, ANCHOR_RIGHT, 1815, 541, 102, 54),
        new StandardItem("visibility", "visibility", STANDARD_APP, 0, 0, ANCHOR_CENTER, 956, 118, 22, 22),
        new StandardItem("settings", "settings", STANDARD_APP, 0, 0, ANCHOR_CENTER, 956, 751, 32, 32),
    };

    /** One skin of the sprite renderer. Its bitmap is decoded once by TouchControls (skin resource by id); everything here is immutable. */
    static final class Skin {
        final String id;             // also its layout namespace: v2/<title ID>/<id>/<screen>
        final int width, height;     // the atlas's real size, checked against the decoded bitmap
        final float refW, refH;      // the layout reference canvas
        final float opacity;         // suggested fresh-install opacity
        final float cap, rightCap, travel, rightTravel;   // cap half extent and cap travel, in fractions of its base's half extent (left, right)
        final float[] dpadDx, dpadDy;   // up, right, down, left sprite centres from the D-pad region's centre, in fractions of its half extent
        final float dpadSprite;          // a direction sprite's half extent, in the same fraction
        final int[] pressed;             // held highlight (ARGB, drawn over the sprite's own alpha): left half, right half, centre
        final float pressedAlpha;
        final int strike;                // the stroke across the visibility sprite while the controls are hidden
        final int visibility, settings, leftCap, rightCapSprite;
        final int[] dpad = new int[4];   // up, right, down, left
        private final int[][] rects;
        private final StandardItem[] items;

        Skin(String id, int width, int height, int[][] rects, StandardItem[] items, float refW, float refH, float opacity,
             float cap, float rightCap, float travel, float rightTravel, float[] dpadDx, float[] dpadDy, float dpadSprite,
             int[] pressed, float pressedAlpha, int strike) {
            this.id = id; this.width = width; this.height = height; this.rects = rects; this.items = items; this.refW = refW; this.refH = refH;
            this.opacity = opacity; this.cap = cap; this.rightCap = rightCap; this.travel = travel; this.rightTravel = rightTravel;
            this.dpadDx = dpadDx; this.dpadDy = dpadDy; this.dpadSprite = dpadSprite; this.pressed = pressed; this.pressedAlpha = pressedAlpha; this.strike = strike;
            visibility = sprite("visibility"); settings = sprite("settings"); leftCap = sprite("left_stick_cap"); rightCapSprite = sprite("right_stick_cap");
            dpad[0] = sprite("up"); dpad[1] = sprite("right"); dpad[2] = sprite("down"); dpad[3] = sprite("left");
        }

        int count() { return SPRITE_IDS.length; }
        String spriteId(int sprite) { return SPRITE_IDS[sprite]; }
        /** The sprite's index by its stable semantic ID, -1 when there is none. */
        int sprite(String id) {
            if (id == null) return -1;
            for (int i = 0; i < SPRITE_IDS.length; i++) if (SPRITE_IDS[i].equals(id)) return i;
            return -1;
        }
        /** One edge of a sprite's source rectangle: 0 left, 1 top, 2 right (exclusive), 3 bottom (exclusive). */
        int rect(int sprite, int edge) { return rects[sprite][edge]; }
        /** The sprite that draws a control, -1 for the D-pad (four sprites) or an unknown combination. */
        int spriteFor(int kind, long buttons, int stick) { return sprite(spriteIdFor(kind, buttons, stick)); }
        StandardItem[] items() { return items.clone(); }
    }

    private static float[] zeldaDpad(int axis) {
        StandardItem d = ZELDA40[8];
        float[] out = new float[4];
        for (int k = 0; k < 4; k++) out[k] = (ZELDA40_DPAD[k][axis] - (axis == 0 ? d.x : d.y)) / d.halfW;
        return out;
    }

    static final Skin STANDARD_SKIN = new Skin("classic-standard", STANDARD_ATLAS_SIZE, STANDARD_ATLAS_SIZE, STANDARD_SPRITE_RECTS, STANDARD, STANDARD_REF_W, STANDARD_REF_H, 0.65f,
            STANDARD_CAP, STANDARD_RIGHT_CAP, STANDARD_STICK_TRAVEL, STANDARD_RIGHT_STICK_TRAVEL,
            new float[] {0, STANDARD_DPAD_OFFSET, 0, -STANDARD_DPAD_OFFSET}, new float[] {-STANDARD_DPAD_OFFSET, 0, STANDARD_DPAD_OFFSET, 0}, STANDARD_DPAD_SPRITE,
            new int[] {0xFF3FD8F2, 0xFFFF7B6B, 0xFFFFFFFF}, 0.28f, 0xC8FFFFFF);   // cyan left, coral right, white centre
    /** Warm gold on both sides and ivory in the centre, restrained: never the standard skin's cyan / coral on the green / gold art. */
    static final Skin ZELDA40_SKIN = new Skin("zelda-40", ZELDA40_ATLAS_W, ZELDA40_ATLAS_H, ZELDA40_SPRITE_RECTS, ZELDA40, ZELDA40_REF_W, ZELDA40_REF_H, 0.65f,
            ZELDA40_CAP, ZELDA40_CAP, ZELDA40_STICK_TRAVEL, ZELDA40_STICK_TRAVEL, zeldaDpad(0), zeldaDpad(1), ZELDA40_DPAD_SIZE / 2 / ZELDA40[8].halfW,
            new int[] {0xFFF0CF7A, 0xFFF0CF7A, 0xFFFFF4DC}, 0.24f, 0xC8FFF4DC);

    /** The sprite skin a resolved profile draws with: the standard skin for Classic, the anniversary skin for Zelda, none (their own artwork) for Bananza and Racing. */
    static Skin skin(String profile) {
        return CLASSIC.equals(profile) ? STANDARD_SKIN : ZELDA.equals(profile) ? ZELDA40_SKIN : null;
    }

    static int standardSpriteCount() { return STANDARD_SKIN.count(); }
    static String standardSpriteId(int sprite) { return STANDARD_SKIN.spriteId(sprite); }
    static int standardSprite(String id) { return STANDARD_SKIN.sprite(id); }
    static int standardRect(int sprite, int edge) { return STANDARD_SKIN.rect(sprite, edge); }
    static int standardSpriteFor(int kind, long buttons, int stick) { return STANDARD_SKIN.spriteFor(kind, buttons, stick); }
    static StandardItem[] standard() { return STANDARD.clone(); }

    /**
     * A skin's edits get their own namespace, v2/<title ID>/<skin>/<screen>, so positions saved for the old placement (v1/<title ID>/<profile>/<screen>) are
     * neither moved nor lost.
     */
    static String skinLayoutKey(String id, Skin skin, String screen) {
        return "v2/" + gameKey(id) + "/" + skin.id + "/" + screen;
    }
    static String standardLayoutKey(String id, String screen) { return skinLayoutKey(id, STANDARD_SKIN, screen); }

    static float[][] placeStandard(float width, float height, float density, float scale) { return placeSkin(STANDARD_SKIN, width, height, density, scale); }

    /**
     * Places a skin's layout in a safe rectangle of width x height px (origin at its top left). Unit u = height / refH * scale; left-anchored x is x*u,
     * right-anchored W - (refW - x)*u, centred W/2 + (x - refW/2)*u; the upper half keeps y*u from the top and the lower half (refH - y)*u from the bottom, which is
     * exactly the reference at scale 1. The unit shrinks until nothing overlaps or leaves the rectangle; artwork is never scaled anisotropically.
     * Returns one row per item {cx, cy, halfW, halfH, hit radius}, then {u}. Buttons get a hit radius of at least 22 dp where neighbours leave room.
     */
    static float[][] placeSkin(Skin skin, float width, float height, float density, float scale) {
        float want = height / skin.refH * scale, low = want * 0.3f, high = want;
        if (fits(placeAt(skin, width, height, high), width, height)) low = high;
        else for (int pass = 0; pass < 20; pass++) {   // the largest unit that fits (overlaps only grow with the unit)
            float candidate = (low + high) / 2;
            if (fits(placeAt(skin, width, height, candidate), width, height)) low = candidate; else high = candidate;
        }
        float[][] out = placeAt(skin, width, height, low);
        for (float[] row : out) {   // a screen too small for even the smallest unit: keep each element inside it
            row[0] = Math.max(row[2], Math.min(width - row[2], row[0]));
            row[1] = Math.max(row[3], Math.min(height - row[3], row[1]));
        }
        hitRadii(skin.items, out, density);
        float[][] result = Arrays.copyOf(out, out.length + 1);
        result[out.length] = new float[] {low};
        return result;
    }

    private static float[][] placeAt(Skin skin, float width, float height, float u) {
        StandardItem[] items = skin.items;
        float[][] out = new float[items.length][5];
        for (int i = 0; i < items.length; i++) {
            StandardItem s = items[i];
            out[i][0] = s.anchor == ANCHOR_LEFT ? s.x * u : s.anchor == ANCHOR_RIGHT ? width - (skin.refW - s.x) * u : width / 2 + (s.x - skin.refW / 2) * u;
            out[i][1] = s.y < skin.refH / 2 ? s.y * u : height - (skin.refH - s.y) * u;
            out[i][2] = s.halfW * u; out[i][3] = s.halfH * u; out[i][4] = Math.max(out[i][2], out[i][3]);
        }
        return out;
    }

    private static boolean round(float[] b) { return Math.abs(b[2] - b[3]) <= 0.25f * Math.max(b[2], b[3]); }

    /** Two placed elements apart: circles for round artwork, boxes for the shoulders and stick clicks, with a 2 px gap. */
    static boolean standardApart(float[] a, float[] b) {
        if (round(a) && round(b)) return Math.hypot(a[0] - b[0], a[1] - b[1]) >= Math.max(a[2], a[3]) + Math.max(b[2], b[3]) + 2;
        return Math.abs(a[0] - b[0]) >= a[2] + b[2] + 2 || Math.abs(a[1] - b[1]) >= a[3] + b[3] + 2;
    }

    private static boolean fits(float[][] p, float width, float height) {
        for (int i = 0; i < p.length; i++) {
            if (p[i][0] - p[i][2] < 0 || p[i][0] + p[i][2] > width || p[i][1] - p[i][3] < 0 || p[i][1] + p[i][3] > height) return false;
            for (int j = 0; j < i; j++) if (!standardApart(p[i], p[j])) return false;
        }
        return true;
    }

    /** Buttons' touch circles: at least 22 dp (a 44 dp target) where the neighbours leave room, never smaller than the artwork; sticks and the D-pad keep their extent. */
    private static void hitRadii(StandardItem[] items, float[][] p, float density) {
        for (int i = 0; i < items.length; i++) if (items[i].kind == 0) p[i][4] = Math.max(p[i][4], 22 * density);
        for (int i = 0; i < items.length; i++) for (int j = 0; j < i; j++) {
            if (items[i].kind == STANDARD_APP || items[j].kind == STANDARD_APP) continue;
            float d = (float) Math.hypot(p[i][0] - p[j][0], p[i][1] - p[j][1]), excess = p[i][4] + p[j][4] - d;
            if (excess <= 0) continue;
            if (items[i].kind == 0) p[i][4] = Math.max(Math.max(p[i][2], p[i][3]), p[i][4] - excess / 2);
            if (items[j].kind == 0) p[j][4] = Math.max(Math.max(p[j][2], p[j][3]), p[j][4] - excess / 2);
        }
    }

    static final class Control {
        final String action, label;
        final int kind, buttons, stick, icon;
        final float x, y, radius;
        Control(String action, String label, int kind, int buttons, int stick, int icon, float x, float y, float radius) {
            this.action = action; this.label = label; this.kind = kind; this.buttons = buttons; this.stick = stick;
            this.icon = icon; this.x = x; this.y = y; this.radius = radius;
        }
    }

    private static Control button(String action, String label, int bit, int icon, float x, float y, float radius) {
        return new Control(action, label, 0, bit, 0, icon, x, y, radius);
    }

    // Positions within the safe landscape area; radii in 360-height reference units.
    // L/R and L+R are independent controls: the host ORs held owners, including overlapping chords.
    static Control[] bananza() {
        return new Control[] {
            new Control("move", "", 1, 0, 0, -1, .13f, .78f, 48),
            new Control("camera", "", 1, 0, 1, -1, .64f, .80f, 40),
            button("punch", "Y", 8, 0, .80f, .68f, 29),
            button("jump", "A", 1, 1, .94f, .68f, 29),
            button("punch_up", "X", 4, 2, .87f, .48f, 24),
            button("punch_down", "B", 2, 3, .87f, .88f, 24),
            button("grab", "ZR", 512, 4, .90f, .28f, 28),
            button("roll", "ZL", 256, 5, .08f, .47f, 24),
            button("sonar", "R", 128, 6, .23f, .55f, 24),
            button("music", "L", 64, 7, .08f, .28f, 24),
            button("bananza", "L+R", 64 | 128, 8, .50f, .11f, 27),
            button("map", "\u2212", 2048, 9, .32f, .10f, 24),
            button("pause", "+", 1024, 14, .94f, .09f, 24),
            new Control("directions", "", 2, 0xf000, 0, -1, .23f, .28f, 34),
            button("left_click", "L3", 16, -1, .27f, .88f, 24),
            button("right_click", "R3", 32, -1, .74f, .94f, 24),
        };
    }

    /** Fit the authored layout to a safe area; never make a button's diameter smaller than 48 dp. */
    static float[][] place(Control[] controls, float width, float height, float density, float scale) {
        float unit = Math.min(width / 640f, height / 360f) * scale;
        float low = 0, high = unit;
        for (int pass = 0; pass < 18; pass++) {
            float candidate = (low + high) / 2;
            if (overlaps(placeAt(controls, width, height, density, candidate))) high = candidate;
            else low = candidate;
        }
        return placeAt(controls, width, height, density, low);
    }

    private static boolean overlaps(float[][] positions) {
        for (int i = 0; i < positions.length; i++) for (int j = 0; j < i; j++) {
            float[] a = positions[i], b = positions[j];
            if (Math.hypot(a[0] - b[0], a[1] - b[1]) < a[2] + b[2] + 2) return true;
        }
        return false;
    }

    private static float[][] placeAt(Control[] controls, float width, float height, float density, float unit) {
        float[][] out = new float[controls.length][3];
        for (int i = 0; i < controls.length; i++) {
            Control c = controls[i];
            float r = Math.max(24 * density, c.radius * unit);
            r = Math.min(r, Math.min(width, height) / 2);
            out[i][0] = Math.max(r, Math.min(width - r, width * c.x));
            out[i][1] = Math.max(r, Math.min(height - r, height * c.y));
            out[i][2] = r;
        }
        return out;
    }
}
