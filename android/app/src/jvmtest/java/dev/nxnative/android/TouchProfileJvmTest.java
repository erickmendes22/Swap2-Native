package dev.nxnative.android;

import java.util.HashSet;
import java.util.Set;

/** Pure layout and routing tests. Native multitouch ownership stays in input_map's tests. */
public final class TouchProfileJvmTest {
    private static int checks;
    private static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); checks++; }
    public static void main(String[] args) {
        check(TouchProfile.resolve(TouchProfile.DK, "auto").equals("bananza"), "DK automatic");
        check(TouchProfile.resolve(TouchProfile.DK.toLowerCase(java.util.Locale.ROOT), "auto").equals("bananza"), "case normalized");
        check(TouchProfile.resolve(TouchProfile.DK, "classic").equals("classic"), "manual classic");
        check(TouchProfile.resolve("0400000000000000", "bananza").equals("classic"), "unknown game stays classic");
        check(TouchProfile.resolve(TouchProfile.OOT, "auto").equals(TouchProfile.ZELDA), "Zelda automatic");
        check(TouchProfile.resolve(TouchProfile.OOT, "classic").equals("classic"), "Zelda classic override");
        check(TouchProfile.choices(TouchProfile.OOT)[1].equals(TouchProfile.ZELDA), "Zelda selection");
        TouchProfile.Control[] zelda = TouchProfile.zelda();
        int zeldaBits = 0, zeldaSticks = 0;
        Set<String> zeldaActions = new HashSet<>();
        for (TouchProfile.Control c : zelda) {
            check(zeldaActions.add(c.action), "unique Zelda action");
            zeldaBits |= c.buttons;
            if (c.kind == 1) zeldaSticks |= 1 << c.stick;
            check(c.icon >= -1 && c.icon <= 14, "Zelda atlas index excludes app settings");
            if (c.label.equals("A")) check(c.buttons == 1, "Zelda A remains A");
            if (c.label.equals("B")) check(c.buttons == 2, "Zelda B remains B");
        }
        check(zeldaBits == 0xffff && zeldaSticks == 3, "Zelda full controller");
        check(zelda.length <= 24, "Zelda native ABI capacity");
        check(TouchProfile.resolve(null, "auto").equals("classic"), "unknown game");
        check(TouchProfile.resolve(TouchProfile.MKW, "auto").equals("racing"), "Mario Kart automatic");
        check(TouchProfile.resolve(TouchProfile.MKW, "classic").equals("classic"), "Mario Kart classic override");
        check(TouchProfile.choices(TouchProfile.MKW).length == 3, "racing selector");
        TouchProfile.Control[] manual = TouchProfile.racing(false), automatic = TouchProfile.racing(true);
        check(manual.length == automatic.length + 1, "auto removes one pedal");
        int accelerate = 0, brake = 0, drift = 0;
        for (TouchProfile.Control c : manual) {
            if (c.action.equals("accelerate")) { check(c.buttons == 1, "gas is A"); accelerate++; }
            if (c.action.equals("drift") || c.action.equals("jump")) { check(c.buttons == 128, "drift and jump hold R"); drift++; }
        }
        for (TouchProfile.Control c : automatic) {
            check((c.buttons & 1) == 0, "auto has no A hitbox");
            if (c.action.equals("brake")) { check(c.buttons == 2, "brake is B"); brake++; }
        }
        check(accelerate == 1 && brake == 1 && drift == 2, "pedals and shared R surfaces");
        check(!TouchProfile.layoutKey(TouchProfile.DK, "classic", "20x9").equals(TouchProfile.layoutKey("0400486024DEC000", "classic", "20x9")), "per-game edits");
        check(!TouchProfile.layoutKey(TouchProfile.DK, "classic", "20x9").equals(TouchProfile.layoutKey(TouchProfile.DK, "bananza", "20x9")), "per-preset edits");
        TouchProfile.Control[] controls = TouchProfile.bananza();
        Set<String> actions = new HashSet<>(); int bits = 0, sticks = 0;
        for (TouchProfile.Control c : controls) {
            check(actions.add(c.action), "stable unique action"); bits |= c.buttons;
            if (c.kind == 1) sticks |= 1 << c.stick;
            if (c.action.equals("bananza")) check(c.buttons == (64 | 128), "L+R chord");
        }
        check(bits == 0xffff, "all controller bits available"); check(sticks == 3, "both sticks");
        check(controls.length <= 24, "native ABI capacity");
        for (TouchProfile.Control[] layout : new TouchProfile.Control[][] {controls, manual, automatic, zelda})
        for (float scale : new float[] {.6f, 1, 1.5f})
        for (float[] size : new float[][] {{640,360,1}, {800,360,1}, {2400,1080,3}, {2080,900,2.75f}, {1600,1200,2}, {1880,810,2.75f}}) {
            float[][] p = TouchProfile.place(layout,size[0],size[1],size[2],scale);
            for (int i=0; i<p.length; i++) {
                check(p[i][2] >= 24*size[2], "48dp minimum");
                check(p[i][0]-p[i][2]>=-.01f && p[i][0]+p[i][2]<=size[0]+.01f && p[i][1]-p[i][2]>=-.01f && p[i][1]+p[i][2]<=size[1]+.01f, "inside safe area");
                for (int j=0;j<i;j++) {
                    double distance=Math.hypot(p[i][0]-p[j][0],p[i][1]-p[j][1]);
                    check(distance+.01 >= p[i][2]+p[j][2], "overlap "+layout[i].action+" / "+layout[j].action);
                }
            }
        }
        standard();
        zelda40();
        System.out.println("ok " + checks);
    }

    /** Zelda's 40th anniversary skin: routing, the measured sprite table, the Zelda profile's control IDs and bits, Nintendo order, geometry. */
    private static void zelda40() {
        TouchProfile.Skin z = TouchProfile.ZELDA40_SKIN, s = TouchProfile.STANDARD_SKIN;
        // Routing: only the Zelda profile uses the anniversary atlas; explicit Classic on Zelda keeps the standard skin; DK and Mario Kart keep their own art
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.OOT, "auto")) == z, "Zelda automatic uses the anniversary skin");
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.OOT, TouchProfile.ZELDA)) == z, "Zelda explicit profile uses the anniversary skin");
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.OOT, "classic")) == s, "explicit Classic on Zelda keeps the standard skin");
        check(TouchProfile.skin(TouchProfile.resolve(null, "auto")) == s, "default games keep the standard skin");
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.DK, "auto")) == null, "Bananza keeps its own art");
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.MKW, "auto")) == null, "Racing keeps its own art");
        check(TouchProfile.skin(TouchProfile.resolve(TouchProfile.DK, "classic")) == s && TouchProfile.skin(TouchProfile.resolve(TouchProfile.MKW, "classic")) == s, "Classic elsewhere");
        check(z.width == 1263 && z.height == 1245 && z.width != TouchProfile.STANDARD_ATLAS_SIZE, "the atlas's real, non-square size");
        check(Math.abs(z.opacity - .65f) < 1e-6f, "65 % suggested opacity");
        // Sprites: 25 unique IDs, every rectangle inside the 1263x1245 atlas, no leak past its edges
        Set<String> ids = new HashSet<>();
        for (int k = 0; k < z.count(); k++) {
            check(ids.add(z.spriteId(k)), "unique anniversary sprite ID");
            int l = z.rect(k, 0), t = z.rect(k, 1), r = z.rect(k, 2), b = z.rect(k, 3);
            check(l >= 0 && t >= 0 && r > l && b > t && r <= z.width && b <= z.height, "anniversary sprite inside the atlas: " + z.spriteId(k));
            check(z.sprite(z.spriteId(k)) == k, "anniversary sprite lookup by ID");
        }
        check(z.count() == 25, "25 anniversary sprites");
        boolean differs = false;
        for (int k = 0; k < z.count(); k++) for (int e = 0; e < 4; e++) differs |= z.rect(k, e) != s.rect(k, e);
        check(differs, "the anniversary skin has its own rectangles");
        for (int bit = 0; bit < 16; bit++) check(z.spriteFor(0, 1L << bit, 0) >= 0, "every guest bit has an anniversary sprite");
        // Controls: exactly the Zelda profile's IDs, kinds, bits and sticks (stored settings and input semantics unchanged)
        java.util.Map<String, TouchProfile.Control> old = new java.util.HashMap<>();
        for (TouchProfile.Control c : TouchProfile.zelda()) old.put(c.action, c);
        TouchProfile.StandardItem[] items = z.items();
        long bits = 0; int sticks = 0, app = 0;
        java.util.Map<String, TouchProfile.StandardItem> by = new java.util.HashMap<>();
        for (TouchProfile.StandardItem it : items) {
            check(by.put(it.action, it) == null, "unique anniversary action");
            check(!it.sprite.equals("home") && !it.sprite.equals("capture") && !it.sprite.equals("c"), "Home / capture / C hidden");
            check(it.sprite.isEmpty() || z.sprite(it.sprite) >= 0, "anniversary item sprite exists");
            if (it.kind == TouchProfile.STANDARD_APP) { app++; check(it.buttons == 0, "app controls send no guest input"); continue; }
            TouchProfile.Control c = old.get(it.action);
            check(c != null, "a Zelda control ID: " + it.action);
            check(c.kind == it.kind && c.buttons == it.buttons && (c.kind != 1 || c.stick == it.stick), "same input as the Zelda profile: " + it.action);
            check((bits & it.buttons) == 0, "one control per bit");
            bits |= it.buttons;
            if (it.kind == 1) sticks |= 1 << it.stick;
            if (it.kind == 0) check(z.spriteFor(0, it.buttons, 0) == z.sprite(it.sprite), "glyph matches its bit: " + it.action);
        }
        check(by.size() - app == old.size(), "every Zelda control placed");
        check(bits == 0xffff && sticks == 3 && app == 2, "full controller plus visibility and settings");
        String[][] glyph = {{"face_a", "a"}, {"face_b", "b"}, {"slot_x", "x"}, {"slot_y", "y"}, {"left_click", "l3"}, {"right_click", "r3"}, {"shoulder_left", "l"},
            {"shoulder_right", "r"}, {"trigger_left", "zl"}, {"trigger_right", "zr"}, {"plus", "plus"}, {"minus", "minus"}, {"move", "left_stick_base"}, {"camera", "right_stick_base"}};
        for (String[] g : glyph) check(by.get(g[0]).sprite.equals(g[1]), "handoff mapping " + g[0] + " -> " + g[1]);
        TouchProfile.StandardItem a = by.get("face_a"), b = by.get("face_b"), x = by.get("slot_x"), y = by.get("slot_y");
        TouchProfile.StandardItem move = by.get("move"), camera = by.get("camera"), dpad = by.get("directions");
        check(x.y < a.y && x.y < y.y && b.y > a.y && b.y > y.y && y.x < x.x && a.x > x.x, "Nintendo order: X top, Y left, A right, B bottom");
        check(move.y < dpad.y && a.y < camera.y, "left stick high / D-pad low, ABXY high / right stick low");
        check(dpad.kind == 2 && dpad.buttons == 0xf000, "one D-pad region keeps diagonals");
        check(by.get("left_click").kind == 0 && by.get("right_click").kind == 0, "L3 / R3 independent buttons");
        // Sticks: separate caps, inside their bases at full travel
        check(z.cap + z.travel <= 1 && z.rightCap + z.rightTravel <= 1 && s.cap + s.travel <= 1 && s.rightCap + s.rightTravel <= 1, "caps stay on their bases");
        check(z.leftCap == z.sprite("left_stick_cap") && z.rightCapSprite == z.sprite("right_stick_cap"), "cap sprites");
        // Palette: warm gold / ivory, never the standard skin's cyan / coral
        for (int p : z.pressed) for (int q : new int[] {s.pressed[0], s.pressed[1]}) check(p != q, "no cyan / coral pressed tint on the anniversary skin");
        // Namespaces: fresh anniversary defaults apart from the old Zelda edits and from the standard skin's
        String v2 = TouchProfile.skinLayoutKey(TouchProfile.OOT, z, "20x9");
        check(v2.equals("v2/0400486024DEC000/zelda-40/20x9"), "anniversary namespace");
        check(!v2.equals(TouchProfile.layoutKey(TouchProfile.OOT, TouchProfile.ZELDA, "20x9")) && !v2.equals(TouchProfile.standardLayoutKey(TouchProfile.OOT, "20x9")), "separate edits");
        // The reference, reproduced at 1912x823 and scale 1, including the four measured D-pad sprite centres
        float[][] ref = TouchProfile.placeSkin(z, 1912, 823, 1, 1);
        check(Math.abs(ref[items.length][0] - 1) < 1e-3f, "anniversary reference unit");
        for (int i = 0; i < items.length; i++) check(Math.abs(ref[i][0] - items[i].x) < .5f && Math.abs(ref[i][1] - items[i].y) < .5f, "anniversary reference " + items[i].action);
        float[][] dpadRef = {{185, 462}, {266, 540}, {185, 619}, {101, 540}};   // up, right, down, left (layout-reference-v1.json)
        for (int k = 0; k < 4; k++) {
            check(Math.abs(dpad.x + z.dpadDx[k] * dpad.halfW - dpadRef[k][0]) < .01f && Math.abs(dpad.y + z.dpadDy[k] * dpad.halfH - dpadRef[k][1]) < .01f, "D-pad sprite centre " + k);
            check(Math.abs(z.dpadSprite * dpad.halfW - 45) < .01f, "D-pad sprites 90 units");
            check(Math.hypot(z.dpadDx[k], z.dpadDy[k]) + z.dpadSprite <= 1.001f, "D-pad sprites inside its region");
        }
        check(z.dpad[0] == z.sprite("up") && z.dpad[1] == z.sprite("right") && z.dpad[2] == z.sprite("down") && z.dpad[3] == z.sprite("left"), "D-pad sprite order");
        for (float scale : new float[] {.6f, 1, 1.5f})
        for (float[] size : new float[][] {{640,360,1}, {800,360,1}, {1920,1080,3}, {2400,1080,3}, {2520,1080,3}, {2080,900,2.75f}, {1600,1200,2}, {1880,810,2.75f}}) {
            float[][] p = TouchProfile.placeSkin(z, size[0], size[1], size[2], scale);
            float u = p[items.length][0];
            check(u > 0 && u <= size[1] / 823f * scale + 1e-4f, "anniversary unit never above the requested size");
            for (int i = 0; i < items.length; i++) {
                check(p[i][0] - p[i][2] >= -.01f && p[i][0] + p[i][2] <= size[0] + .01f && p[i][1] - p[i][3] >= -.01f && p[i][1] + p[i][3] <= size[1] + .01f,
                        "anniversary inside safe area " + items[i].action);
                check(Math.abs(p[i][2] / p[i][3] - items[i].halfW / items[i].halfH) < 1e-3f, "anniversary artwork aspect preserved");
                check(p[i][4] >= Math.max(p[i][2], p[i][3]) - .01f, "anniversary touch circle covers the artwork");
                for (int j = 0; j < i; j++) check(TouchProfile.standardApart(p[i], p[j]), "anniversary overlap " + items[i].action + " / " + items[j].action);
            }
        }
        // The standard skin is unchanged by the generalization
        float[][] a1 = TouchProfile.placeStandard(2400, 1080, 3, 1), a2 = TouchProfile.placeSkin(s, 2400, 1080, 3, 1);
        for (int i = 0; i < a1.length; i++) check(java.util.Arrays.equals(a1[i], a2[i]), "placeStandard is the standard skin's placement");
    }

    /** The standard skin v2: semantic sprite table, the full controller with no invented Home / C / capture input, Nintendo face order, geometry. */
    private static void standard() {
        Set<String> ids = new HashSet<>();
        for (int s = 0; s < TouchProfile.standardSpriteCount(); s++) {
            check(ids.add(TouchProfile.standardSpriteId(s)), "unique sprite ID");
            int l = TouchProfile.standardRect(s, 0), t = TouchProfile.standardRect(s, 1), r = TouchProfile.standardRect(s, 2), b = TouchProfile.standardRect(s, 3);
            check(l >= 0 && t >= 0 && r > l && b > t && r <= TouchProfile.STANDARD_ATLAS_SIZE && b <= TouchProfile.STANDARD_ATLAS_SIZE, "sprite inside the atlas");
            check(TouchProfile.standardSprite(TouchProfile.standardSpriteId(s)) == s, "sprite lookup by ID");
        }
        check(TouchProfile.standardSpriteCount() == 25, "25 sprites");
        check(TouchProfile.standardSprite("missing") == -1, "unknown sprite");
        for (int bit = 0; bit < 16; bit++) check(TouchProfile.standardSpriteFor(0, 1L << bit, 0) >= 0, "every guest bit has a sprite");
        check(TouchProfile.standardSpriteFor(0, 64 | 128, 0) == -1, "no sprite for a chord");
        check(TouchProfile.standardSpriteFor(1, 0, 0) == TouchProfile.standardSprite("left_stick_base"), "left stick base");
        check(TouchProfile.standardSpriteFor(1, 0, 1) == TouchProfile.standardSprite("right_stick_base"), "right stick base");
        TouchProfile.StandardItem[] items = TouchProfile.standard();
        long bits = 0; int sticks = 0, app = 0, sent = 0;
        Set<String> actions = new HashSet<>();
        TouchProfile.StandardItem a = null, b = null, x = null, y = null, leftStick = null, dpad = null, rightStick = null;
        for (TouchProfile.StandardItem s : items) {
            check(actions.add(s.action), "unique standard action");
            check(!s.sprite.equals("home") && !s.sprite.equals("capture") && !s.sprite.equals("c"), "Home / capture / C hidden");
            check(s.sprite.isEmpty() || TouchProfile.standardSprite(s.sprite) >= 0, "standard item sprite exists");
            if (s.kind == TouchProfile.STANDARD_APP) { app++; check(s.buttons == 0, "app controls send no guest input"); continue; }
            sent++;
            check((bits & s.buttons) == 0, "one control per bit");
            bits |= s.buttons;
            if (s.kind == 1) sticks |= 1 << s.stick;
            if (s.kind == 0) check(TouchProfile.standardSpriteFor(0, s.buttons, 0) == TouchProfile.standardSprite(s.sprite), "sprite matches its bit: " + s.action);
            switch (s.action) {
                case "a": a = s; break; case "b": b = s; break; case "x": x = s; break; case "y": y = s; break;
                case "left_stick": leftStick = s; break; case "right_stick": rightStick = s; break; case "dpad": dpad = s; break;
                default: break;
            }
        }
        check(bits == 0xffff && sticks == 3 && app == 2, "full controller plus visibility and settings");
        check(sent <= 24, "native ABI capacity");
        check(dpad != null && dpad.kind == 2 && dpad.buttons == 0xf000, "one D-pad region keeps diagonals");
        check(x.y < a.y && x.y < y.y && b.y > a.y && b.y > y.y && y.x < x.x && a.x > x.x, "Nintendo order: X top, Y left, A right, B bottom");
        check(leftStick.y < dpad.y && a.y < rightStick.y, "left stick high / D-pad low, ABXY high / right stick low");
        String v2 = TouchProfile.standardLayoutKey(TouchProfile.DK, "20x9");
        check(!v2.equals(TouchProfile.layoutKey(TouchProfile.DK, "classic", "20x9")) && v2.startsWith("v2/"), "standard edits in their own namespace");
        // At scale 1 on an exact 1913x822 rectangle the reference is reproduced
        float[][] ref = TouchProfile.placeStandard(1913, 822, 1, 1);
        check(Math.abs(ref[items.length][0] - 1) < 1e-3f, "reference unit");
        for (int i = 0; i < items.length; i++) check(Math.abs(ref[i][0] - items[i].x) < .5f && Math.abs(ref[i][1] - items[i].y) < .5f, "reference position " + items[i].action);
        for (float scale : new float[] {.6f, 1, 1.5f})
        for (float[] size : new float[][] {{640,360,1}, {800,360,1}, {1920,1080,3}, {2400,1080,3}, {2520,1080,3}, {2080,900,2.75f}, {1600,1200,2}, {1880,810,2.75f}}) {
            float[][] p = TouchProfile.placeStandard(size[0], size[1], size[2], scale);
            float u = p[items.length][0];
            check(u > 0 && u <= size[1] / 822f * scale + 1e-4f, "unit never above the requested size");
            for (int i = 0; i < items.length; i++) {
                check(p[i][0] - p[i][2] >= -.01f && p[i][0] + p[i][2] <= size[0] + .01f && p[i][1] - p[i][3] >= -.01f && p[i][1] + p[i][3] <= size[1] + .01f,
                        "inside safe area " + items[i].action);
                check(Math.abs(p[i][2] / p[i][3] - items[i].halfW / items[i].halfH) < 1e-3f, "artwork aspect preserved");
                check(p[i][4] >= Math.max(p[i][2], p[i][3]) - .01f, "touch circle covers the artwork");
                for (int j = 0; j < i; j++) check(TouchProfile.standardApart(p[i], p[j]), "standard overlap " + items[i].action + " / " + items[j].action);
            }
        }
    }
}
