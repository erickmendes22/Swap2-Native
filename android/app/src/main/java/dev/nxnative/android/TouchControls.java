package dev.nxnative.android;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.util.TypedValue;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

import java.util.Arrays;

/**
 * The on-screen controls over the game's SurfaceView: a virtual Pro Controller drawn by the launcher and driven by the host. The view lays the controls out in dp around
 * the letterboxed 16:9 picture, hands the layout to the host (nxhost_touch_controls_set) and passes every touch on (nxhost_input_touch); the host decides what each touch
 * drives, a control (its buttons and sticks go to the game as the handheld controller, dm_input_set) or the game's touchscreen, so a touch on a control never reaches the
 * touchscreen. The view reads back what each control holds to draw it and to give a haptic tick on each press.
 * The small button at the top centre shows or hides the controls; holding it opens the settings (opacity, size, vibration). They hide by themselves while a gamepad is
 * connected and come back when the last one goes.
 * Classic and Zelda draw a sprite skin (TouchProfile.Skin): Classic the standard skin v2 (drawable-nodpi/s2_standard_controls_v2.png), Zelda the 40th anniversary
 * skin (drawable-nodpi/s2_zelda40_controls.png), each with its measured rectangles and, in landscape, its own geometry (TouchProfile.placeSkin), and a gear that
 * opens the same settings and never reaches the game. Bananza and Racing keep their own artwork.
 */
final class TouchControls extends View {
    // DM_BTN_* (dm/host/dm_input.h, nn::hid::NpadButton order)
    private static final long A = 1, B = 1 << 1, X = 1 << 2, Y = 1 << 3, LS = 1 << 4, RS = 1 << 5, L = 1 << 6, R = 1 << 7, ZL = 1 << 8, ZR = 1 << 9,
            PLUS = 1 << 10, MINUS = 1 << 11, LEFT = 1 << 12, UP = 1 << 13, RIGHT = 1 << 14, DOWN = 1 << 15;
    private static final int BUTTON = 0, STICK = 1, DPAD = 2, MAX = 24;   // input_map.h NXT_*, NXT_MAX
    private static final int SHAPE_ROUND = 0, SHAPE_SHOULDER = 1;

    private final boolean input;   // the host takes touches (nxhost_input_touch)
    private final String gameId;
    private String profile;
    private boolean suspended;
    private boolean autoAccelerate;
    private final String[] actions = new String[MAX];
    private Bitmap atlas;
    private Bitmap racingActions, controllerArtwork, raceImage;
    private int atlasResource;
    private final Paint artwork = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Rect source = new Rect();
    private static final int[] ATLAS_X = {173, 476, 779, 1082}, ATLAS_Y = {178, 480, 780, 1084};
    // The sprite skins (TouchProfile.Skin): the standard skin v2 for Classic (docs/SWAP2-NATIVE-STANDARD-TOUCH-v2.md), the 40th anniversary skin for Zelda
    // (docs/SWAP2-NATIVE-ZELDA40-TOUCH-v1.md). Each atlas is decoded once, unscaled; sprites by semantic ID; state drawn on the Canvas
    private final Bitmap[] skinAtlas = new Bitmap[2];   // by skinIndex
    private final boolean[] skinTried = new boolean[2];
    private TouchProfile.Skin skin;   // the profile's skin; null for Bananza and Racing (their own artwork)
    private boolean skinV2;           // the skin's landscape geometry (TouchProfile.placeSkin), not an old placement the user customized
    private String baseKey;         // the profile's layout key (v1) prof was chosen for
    private final int[] sprite = new int[MAX];
    private final float[] vw = new float[MAX], vh = new float[MAX];   // each control's artwork half extents; r is its touch circle
    private final long[] fadeBits = new long[MAX], fadeAt = new long[MAX];   // what each control just let go, for the release animation
    private boolean fading;
    private static final long RELEASE_MS = 110;
    private static final long[] DPAD_BITS = {UP, RIGHT, DOWN, LEFT};   // the order of Skin.dpad
    private final Paint tint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    // Pressed highlight from the skin's palette (left, right, centre), kept in the sprite's own alpha (SRC_IN); made again only when the skin changes
    private final android.graphics.ColorFilter[] tints = new android.graphics.ColorFilter[3];
    private TouchProfile.Skin tintsFor;
    private float gx, gy, gr, gearGrab, toggleGrab;   // the settings gear (the launcher's, never the guest's) and the show / hide button's touch radius
    private int gearId = -1;
    private final int[] icons = new int[MAX];
    private String setting(String name) { return name + "@" + gameId; }
    private SharedPreferences prefs() { return Prefs.open(getContext(), "touch_controls"); }   // read again when the other process wrote it (Prefs.open)
    private boolean available;     // the host takes a layout (nxhost_touch_controls_set): the controls can be drawn
    private boolean shown = true, gamepad;
    private float opacity, scale;
    private boolean haptics;

    // The layout in pixels, as the host has it
    private int n;
    private final int[] kind = new int[MAX], stick = new int[MAX], shape = new int[MAX];
    private final long[] buttons = new long[MAX];
    private final float[] cx = new float[MAX], cy = new float[MAX], r = new float[MAX];
    private final String[] label = new String[MAX];
    private float tx, ty, tr;      // the show / hide button
    private float picX, picY, picW = 1, picH = 1;   // the game's picture in the view, normalized
    private float safeLeft, safeTop, safeRight, safeBottom;

    // The user's layout, one per screen shape (prof: the view's size in steps of 40 units, so a foldable's two screens keep one each): each group (the left stick with L3,
    // the D-pad, the face buttons, the right stick with R3, the left and the right shoulders with − / +) moved by (gdx, gdy) units and scaled by gsc around its centre,
    // and where the picture sits in the free space (placeX, placeY: 0 left / top, 0.5 centred, 1 right / bottom; nxhost_picture_place)
    private static final int GROUPS = 6;
    private static final String[] GROUP_NAME = {"left stick", "D-pad", "A B X Y", "right stick", "ZL L −", "ZR R +"};
    private String prof;
    private final float[] gdx = new float[GROUPS], gdy = new float[GROUPS], gsc = new float[GROUPS];
    private float placeX = 0.5f, placeY = 0.5f;
    private final RectF[] gbox = new RectF[GROUPS];
    // The layout editor (startEditLayout): touches move the groups and the picture instead of going to the host
    private boolean editing;
    private int dragG = -1, dragId = -1, pinchId = -1;   // dragG: a group, GROUPS for the picture
    private float lastX, lastY, pinchD0, pinchS0;
    private final RectF[] tool = new RectF[5];   // the editor's buttons: Top, Centre, Bottom, Reset, Done
    private static final String[] TOOL = {"Top", "Centre", "Bottom", "Reset", "Done"};

    private final long[] pressed = new long[MAX], prev = new long[MAX];
    private final float[] sticks = new float[4];
    private int toggleId = -1;
    private boolean toggleLong;
    private final Runnable longPress = () -> { toggleLong = true; performHapticFeedback(HapticFeedbackConstants.LONG_PRESS); settings(); };

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG), line = new Paint(Paint.ANTI_ALIAS_FLAG), text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF rect = new RectF();

    TouchControls(Context c, boolean input) {
        this(c, input, null);
    }

    TouchControls(Context c, boolean input, String titleId) {
        super(c);
        this.input = input;
        gameId = TouchProfile.gameKey(titleId);
        profile = TouchProfile.resolve(gameId, prefs().getString(setting("profile"), TouchProfile.AUTO));
        autoAccelerate = prefs().getBoolean(setting("race_auto"), false);
        // A fresh install starts a sprite skin at its suggested opacity (65 %); an opacity the user already chose is kept
        TouchProfile.Skin initial = TouchProfile.skin(profile);
        opacity = prefs().getFloat(setting("opacity"), prefs().getFloat("opacity", initial != null ? initial.opacity : 0.6f));
        scale = prefs().getFloat(setting("scale"), prefs().getFloat("scale", 1f));
        haptics = prefs().getBoolean(setting("haptics"), prefs().getBoolean("haptics", true));
        shown = prefs().getBoolean(setting("shown"), prefs().getBoolean("shown", true));
        line.setStyle(Paint.Style.STROKE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setFakeBoldText(true);
        setHapticFeedbackEnabled(true);
    }

    /** The game's picture in the view (normalized), as the replay letterboxes it: 16:9 at its full size, at (px, py) of the free space (0.5: centred) */
    static float[] picture(int w, int h, float px, float py) {
        float pw = 1, ph = 1;
        if (w * 9f > h * 16f) pw = h * 16f / 9f / w; else ph = w * 9f / 16f / h;
        return new float[] {(1 - pw) * px, (1 - ph) * py, pw, ph};
    }

    /** A gamepad connected (the controls hide) or the last one gone (they come back, unless the user hid them) */
    void setGamepad(boolean connected) {
        if (gamepad == connected) return;
        cancelInput();
        gamepad = connected;
        Native.note("on-screen controls " + (active() ? "shown" : "hidden") + (connected ? ": a gamepad is connected" : ": no gamepad"));
        apply();
    }

    private boolean active() { return available && shown && !gamepad; }

    private void apply() {
        if (input) Native.touchControlsEnable(active() && !editing && !suspended);
        Arrays.fill(pressed, 0); Arrays.fill(prev, 0); Arrays.fill(sticks, 0); Arrays.fill(fadeBits, 0);
        invalidate();
    }

    private void toggle() {
        if (gamepad) { gamepad = false; shown = true; }   // the user wants them back with a gamepad connected
        else shown = !shown;
        prefs().edit().putBoolean(setting("shown"), shown).commit();
        Native.note("on-screen controls " + (active() ? "shown" : "hidden") + " by the user");
        apply();
    }

    @Override protected void onSizeChanged(int w, int h, int ow, int oh) {
        super.onSizeChanged(w, h, ow, oh);
        layout(w, h);
    }

    @Override public android.view.WindowInsets onApplyWindowInsets(android.view.WindowInsets insets) {
        post(this::relayout);
        return super.onApplyWindowInsets(insets);
    }

    // ---- Layout: in units of 1/135 inch, scaled by the user's size, anchored to the screen's sides and its bottom, so the controls sit in the letterbox bars as far as they fit ----
    private int add(int k, long b, int s, int sh, float x, float y, float rad, String lb) {
        if (n >= MAX) return -1;
        kind[n] = k; buttons[n] = b; stick[n] = s; shape[n] = sh; cx[n] = x; cy[n] = y; r[n] = rad; label[n] = lb;
        vw[n] = rad; vh[n] = sh == SHAPE_SHOULDER ? rad * 0.62f : rad; sprite[n] = skin != null ? skin.spriteFor(k, b, s) : -1;
        return n++;
    }

    /** Pixels per layout unit: 1/135 inch from the screen's physical dpi, which is a dp on the phone the layout was tuned on (Honor PNM-N49's outer screen, 405 dpi at
     *  density 3), so the controls keep their physical size whatever the display size setting; the dp when the screen reports a dpi far from its density */
    private float unit() {
        android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
        float ppi = (dm.xdpi + dm.ydpi) / 2, u = ppi / 135f;
        return u > dm.density * 0.6f && u < dm.density * 1.6f ? u : dm.density;
    }

    private void layout(int w, int h) {
        if (w <= 0 || h <= 0) return;
        float dp = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 1, getResources().getDisplayMetrics()), u = unit();
        String screen = Math.round(w / u / 40) + "x" + Math.round(h / u / 40);
        String key = TouchProfile.layoutKey(gameId, profile + (TouchProfile.RACING.equals(profile) && autoAccelerate ? "-auto" : ""), screen);
        TouchProfile.Skin wanted = TouchProfile.skin(profile);
        if (!key.equals(baseKey)) {   // a new screen shape (a fold, an unfold) or profile: its own layout
            baseKey = key;
            // A sprite skin in landscape: its own geometry in its own namespace (v2/<title ID>/<skin>/<screen>), unless the user customized the profile's old
            // placement here (Classic's, or Zelda's v1/<title ID>/zelda-oot/<screen>) and has not restored the defaults since: their positions stay where they put
            // them, drawn with the new art
            String v2 = wanted != null ? TouchProfile.skinLayoutKey(gameId, wanted, screen) : null;
            prof = v2 != null && w > h && (prefs().contains("group0@" + v2) || !legacyCustom(key, screen)) ? v2 : key;
            load();
        }
        float[] p = picture(w, h, placeX, placeY);
        picX = p[0]; picY = p[1]; picW = p[2]; picH = p[3];
        if (input) { Native.picturePlace(placeX, placeY); Native.touchLayout(w, h, picX, picY, picW, picH); }
        // On a short screen (under 340 units high) everything shrinks with it
        float fit = Math.min(1f, h / u / 340f), d = u * scale * fit, m = 14 * u;
        // The controls take a band along the bottom no taller than a phone held in landscape (380 units, 2.8 inches): on a taller screen (a foldable's inner screen,
        // a tablet) they stay where the thumbs are, in the bottom corners, instead of spreading over its height
        float y0 = Math.max(0, h - 380 * d), bh = h - y0;
        float bar = picX * w;   // the width of each letterbox bar
        float rStick = 60 * d, rRight = 54 * d, rPad = 50 * d, rFace = 25 * d, rSh = 25 * d, rSmall = 17 * d, rClick = 17 * d, off = 1.65f * rFace;
        n = 0;
        safeLeft = safeTop = 0; safeRight = w; safeBottom = h;
        Arrays.fill(icons, -1);
        Arrays.fill(actions, null);
        boolean actionLayout = !TouchProfile.CLASSIC.equals(profile) && w > h;
        skin = wanted;
        skinV2 = skin != null && w > h && prof.startsWith("v2/");
        int left = 0, topInset = 0, right = 0, bottom = 0;
        if (actionLayout || skinV2) {
            android.view.WindowInsets wi = getRootWindowInsets();
            if (wi != null) {
                // The whole screen less 6 dp for the rounded corners (2026-11-08, the user's choice): the game hides the status and navigation bars (Ui.immersive,
                // shown over the picture by an edge swipe), and a control may sit beside the camera hole. Counting the bars took 161 px at the top and 177 px at the
                // right of the POCO F7 Ultra's 3200x1440, and its cutout inset another 161 px at the left (the whole strip, for a small hole), pulling the controls
                // towards the middle
                int edge = Math.round(6 * dp);
                left = topInset = right = bottom = edge;
            }
            safeLeft = left; safeTop = topInset; safeRight = w - right; safeBottom = h - bottom;
        }
        if (skin != null && !skinTried[skinIndex(skin)]) {   // decoded once, unscaled; drawing reuses it
            int index = skinIndex(skin);
            skinTried[index] = true;
            BitmapFactory.Options options = new BitmapFactory.Options(); options.inScaled = false;
            Bitmap decoded = BitmapFactory.decodeResource(getResources(), skinResource(skin), options);
            if (decoded != null && (decoded.getWidth() != skin.width || decoded.getHeight() != skin.height)) {   // the measured rectangles address only that size
                Native.note("[RED] touch artwork: " + skin.id + " decoded at " + decoded.getWidth() + "x" + decoded.getHeight() + ", not " + skin.width + "x" + skin.height + ": not used");
                decoded = null;
            }
            skinAtlas[index] = decoded;
            Native.note("touch artwork: " + skin.id + ", loaded=" + (decoded != null) + (decoded != null ? " " + decoded.getWidth() + "x" + decoded.getHeight() : ""));
        }
        if (skin != null && tintsFor != skin) {
            for (int k = 0; k < tints.length; k++) tints[k] = new android.graphics.PorterDuffColorFilter(skin.pressed[k], android.graphics.PorterDuff.Mode.SRC_IN);
            tintsFor = skin;
        }
        float vx = 0, vy = 0, vr = 0;
        if (skinV2) {
            // The skin's layout reference in the safe rectangle: anchored to its sides, scaled from its height by the user's size, shrunk until nothing overlaps
            TouchProfile.StandardItem[] items = skin.items();
            float[][] pos = TouchProfile.placeSkin(skin, safeRight - safeLeft, safeBottom - safeTop, dp, scale);
            for (int i = 0; i < items.length; i++) {
                TouchProfile.StandardItem s = items[i];
                float x = safeLeft + pos[i][0], y = safeTop + pos[i][1];
                if (s.kind == TouchProfile.STANDARD_APP) {
                    if ("visibility".equals(s.action)) { vx = x; vy = y; vr = pos[i][2]; } else { gx = x; gy = y; gr = pos[i][2]; }
                    continue;
                }
                String lb = "minus".equals(s.sprite) ? "−" : "plus".equals(s.sprite) ? "+" : s.kind == BUTTON ? s.sprite.toUpperCase(java.util.Locale.ROOT) : "";
                int index = add(s.kind, s.buttons, s.stick, s.halfW > s.halfH * 1.5f ? SHAPE_SHOULDER : SHAPE_ROUND, x, y, pos[i][4], lb);
                if (index < 0) continue;
                vw[index] = pos[i][2]; vh[index] = pos[i][3]; actions[index] = s.action;
            }
        } else if (actionLayout) {
            TouchProfile.Control[] definition = TouchProfile.RACING.equals(profile) ? TouchProfile.racing(autoAccelerate)
                    : TouchProfile.ZELDA.equals(profile) ? TouchProfile.zelda() : TouchProfile.bananza();
            float[][] pos = TouchProfile.place(definition, w - left - right, h - topInset - bottom, dp, scale);
            for (int i = 0; i < definition.length; i++) {
                TouchProfile.Control c = definition[i];
                int index = add(c.kind, c.buttons, c.stick, SHAPE_ROUND, left + pos[i][0], topInset + pos[i][1], pos[i][2], c.label);
                // Zelda here is an old placement the user customized, drawn with the anniversary skin's fixed controller glyphs: its old action-icon indices
                // (zelda_icon_<action>@<title ID>, kept stored) address only the old atlas and are not used
                icons[index] = skin == null ? c.icon : -1; actions[index] = c.action;
            }
            int wantedAtlas = TouchProfile.BANANZA.equals(profile) ? dev.nxnative.android.R.drawable.s2_bananza_controls
                    : TouchProfile.RACING.equals(profile) ? dev.nxnative.android.R.drawable.s2_racing_controls : 0;
            if (wantedAtlas != 0 && (atlas == null || atlasResource != wantedAtlas)) {
                BitmapFactory.Options options = new BitmapFactory.Options(); options.inScaled = false;
                atlas = BitmapFactory.decodeResource(getResources(), wantedAtlas, options);
                atlasResource = wantedAtlas;
                Native.note("touch artwork: profile=" + profile + ", loaded=" + (atlas != null));
            }
            if (TouchProfile.RACING.equals(profile) && racingActions == null) {
                BitmapFactory.Options options = new BitmapFactory.Options(); options.inScaled = false;
                racingActions = BitmapFactory.decodeResource(getResources(), dev.nxnative.android.R.drawable.s2_bananza_controls, options);
                controllerArtwork = BitmapFactory.decodeResource(getResources(), dev.nxnative.android.R.drawable.s2_controller_controls, options);
            }
        } else {
        // Shoulders in the band's top corners, ZL / ZR outside, L / R inside, minus / plus next to them
        float shY = y0 + m + 0.7f * rSh;
        add(BUTTON, ZL, 0, SHAPE_SHOULDER, m + rSh, shY, rSh, "ZL");
        add(BUTTON, L, 0, SHAPE_SHOULDER, m + 3 * rSh + 10 * d, shY, rSh, "L");
        add(BUTTON, ZR, 0, SHAPE_SHOULDER, w - m - rSh, shY, rSh, "ZR");
        add(BUTTON, R, 0, SHAPE_SHOULDER, w - m - 3 * rSh - 10 * d, shY, rSh, "R");
        add(BUTTON, MINUS, 0, SHAPE_ROUND, m + 4 * rSh + 22 * d + rSmall, shY, rSmall, "−");
        add(BUTTON, PLUS, 0, SHAPE_ROUND, w - m - 4 * rSh - 22 * d - rSmall, shY, rSmall, "+");
        // Left: the stick high, the D-pad low, centred in the bar when it is wide enough
        float top = shY + rSh + 10 * d;
        float lx = Math.max(m + rStick, bar / 2), ly = Math.max(y0 + bh * 0.45f, top + rStick);
        int ls = add(STICK, 0, 0, SHAPE_ROUND, lx, ly, rStick, "");
        add(DPAD, UP | DOWN | LEFT | RIGHT, 0, SHAPE_ROUND, Math.max(m + rPad, bar / 2), h - m - rPad, rPad, "");
        float diag = (rStick + rClick + 6 * d) * 0.7071f;
        add(BUTTON, LS, 0, SHAPE_ROUND, lx + diag, ly + diag, rClick, "L3");
        // Right: the face buttons high (A right, B bottom, X top, Y left, as on a Switch), the right stick low
        float fx = Math.min(w - m - rFace - off, w - bar / 2), fy = ly;
        add(BUTTON, A, 0, SHAPE_ROUND, fx + off, fy, rFace, "A");
        add(BUTTON, B, 0, SHAPE_ROUND, fx, fy + off, rFace, "B");
        add(BUTTON, X, 0, SHAPE_ROUND, fx, fy - off, rFace, "X");
        add(BUTTON, Y, 0, SHAPE_ROUND, fx - off, fy, rFace, "Y");
        float rx = Math.min(w - m - rRight, w - bar / 2), ry = h - m - rRight;
        add(STICK, 0, 1, SHAPE_ROUND, rx, ry, rRight, "");
        float diagR = (rRight + rClick + 6 * d) * 0.7071f;
        add(BUTTON, RS, 0, SHAPE_ROUND, rx - diagR, ry - diagR, rClick, "R3");
        // Push apart what still overlaps (a large size on a small screen): the later control moves towards the middle
        for (int pass = 0; pass < 4; pass++)
            for (int j = 0; j < n; j++)
                for (int i = 0; i < j; i++) {
                    float dx = cx[j] - cx[i], dy = cy[j] - cy[i], need = r[i] + r[j] + 2 * d;
                    if (dx * dx + dy * dy >= need * need) continue;
                    float move = (float) Math.sqrt(Math.max(0, need * need - dy * dy)) - Math.abs(dx);
                    cx[j] += cx[j] < w / 2f ? move : -move;
                }
        }
        groups(w, h, u);
        tr = 15 * u; tx = w / 2f; ty = m + tr * 0.8f;
        if (actionLayout) { tx = safeLeft + 28 * dp; ty = safeTop + 28 * dp; tr = 15 * dp; }
        if (skinV2) { tx = vx; ty = vy; tr = vr; }
        else if (skin != null) { gr = tr * 0.86f; gx = tx + tr * 3f; gy = ty; }   // the old placement (portrait, or the user's own): the gear beside the show / hide button
        toggleGrab = skin != null ? Math.max(tr * 1.6f, 22 * dp) : tr * 1.6f;   // at least a 44 dp target
        gearGrab = Math.max(gr * 1.3f, 22 * dp);
        if (skin != null) { toggleGrab = grabApart(tx, ty, tr, toggleGrab, 2 * dp); gearGrab = grabApart(gx, gy, gr, gearGrab, 2 * dp); }   // the app's buttons are tested before the guest's: never let their margin take a control's touch circle
        // The host's units: centres normalized to the view, radii in units of its height; a stick's grab ring is its own (input_map.c)
        float[] f = new float[n * 6];
        for (int i = 0; i < n; i++) {
            f[6 * i] = kind[i]; f[6 * i + 1] = buttons[i]; f[6 * i + 2] = stick[i];
            f[6 * i + 3] = cx[i] / w; f[6 * i + 4] = cy[i] / h; f[6 * i + 5] = r[i] / h;
        }
        int kept = input ? Native.touchControlsSet(f) : -1;
        boolean was = available;
        available = !input || kept == n;
        if (!available && was != available) Native.note("on-screen controls: this host takes no layout (" + kept + "): not drawn");
        if (!editing) Native.note(String.format(java.util.Locale.ROOT, "on-screen controls: %d in a %dx%d view (%.1f dp high, %.2f px a unit, band from y %.0f, screen %s%s), picture x %.3f y %.3f, size %.2f, opacity %.2f, %s",
                n, w, h, h / dp, u, y0, prof, custom() ? ", the user's layout" : "", picX, picY, scale, opacity, active() ? "shown" : "hidden"));
        apply();
        // The performance overlay keeps clear of the controls just placed (PerformanceOverlay.place asks freeX)
        if (getParent() instanceof android.view.ViewGroup) {
            android.view.ViewGroup root = (android.view.ViewGroup) getParent();
            for (int i = 0; i < root.getChildCount(); i++) if (root.getChildAt(i) instanceof PerformanceOverlay) { PerformanceOverlay po = (PerformanceOverlay) root.getChildAt(i); po.post(po::place); }
        }
    }

    /**
     * The left edge nearest to want (px, in this view, which fills the same parent as the performance overlay) at which a box bw wide from y0 to y1 covers no
     * drawn control, the show / hide button or the gear, at least 4 dp apart (2026-11-08: the overlay covered "+" on a 20:9 phone); want when no position in
     * [0, maxX] is free. Hidden controls (a gamepad, hidden by the user) leave only the show / hide button
     */
    float freeX(float want, float bw, float y0, float y1, float maxX) {
        float gap = 4 * getResources().getDisplayMetrics().density;
        java.util.List<float[]> spans = new java.util.ArrayList<>();
        if (active()) for (int i = 0; i < n; i++) {
            float ex = Math.max(r[i], vw[i]), ey = Math.max(r[i], vh[i]);
            if (cy[i] + ey + gap > y0 && cy[i] - ey - gap < y1) spans.add(new float[] {cx[i] - ex - gap, cx[i] + ex + gap});
        }
        if (available && tr > 0 && ty + tr + gap > y0 && ty - tr - gap < y1) spans.add(new float[] {tx - tr - gap, tx + tr + gap});
        if (active() && gr > 0 && gy + gr + gap > y0 && gy - gr - gap < y1) spans.add(new float[] {gx - gr - gap, gx + gr + gap});
        java.util.List<Float> at = new java.util.ArrayList<>();
        at.add(want);
        for (float[] s : spans) { at.add(s[0] - bw); at.add(s[1]); }
        float best = want, bestD = Float.MAX_VALUE;
        for (float x : at) {
            x = Math.max(0, Math.min(maxX, x));
            boolean free = true;
            for (float[] s : spans) if (x < s[1] && x + bw > s[0]) { free = false; break; }
            if (free && Math.abs(x - want) < bestD) { best = x; bestD = Math.abs(x - want); }
        }
        return best;
    }

    // ---- The user's layout: groups moved and scaled, the picture placed, kept per screen shape ----
    private int groupOf(int i) {
        if (TouchProfile.RACING.equals(profile) && actions[i] != null) {
            switch (actions[i]) {
                case "steering": return 0;
                case "camera": return 3;
                case "accelerate": case "brake": return 2;
                case "item": case "rear_view": return 4;
                case "drift": case "jump": return 5;
                default: return 1;
            }
        }
        long b = buttons[i];
        if (kind[i] == STICK) return stick[i] == 0 ? 0 : 3;
        if (kind[i] == DPAD) return 1;
        if (b == LS) return 0;
        if (b == RS) return 3;
        if ((b & (A | B | X | Y)) != 0) return 2;
        if ((b & (ZL | L | MINUS)) != 0) return 4;
        return 5;
    }

    /** Moves and scales each group as the user left it, around the centre of where the automatic layout put it, kept inside the view; gbox gets each group's bounds */
    private void groups(int w, int h, float u) {
        for (int g = 0; g < GROUPS; g++) {
            float sx = 0, sy = 0; int k = 0;
            for (int i = 0; i < n; i++) if (groupOf(i) == g) { sx += cx[i]; sy += cy[i]; k++; }
            if (k == 0) { gbox[g] = null; continue; }
            float mx = sx / k, my = sy / k, sc = gsc[g];
            float x0 = Float.MAX_VALUE, y0 = Float.MAX_VALUE, x1 = -Float.MAX_VALUE, y1 = -Float.MAX_VALUE;
            for (int i = 0; i < n; i++) {
                if (groupOf(i) != g) continue;
                cx[i] = mx + (cx[i] - mx) * sc + gdx[g] * u; cy[i] = my + (cy[i] - my) * sc + gdy[g] * u; r[i] *= sc; vw[i] *= sc; vh[i] *= sc;
                x0 = Math.min(x0, cx[i] - r[i]); y0 = Math.min(y0, cy[i] - r[i]); x1 = Math.max(x1, cx[i] + r[i]); y1 = Math.max(y1, cy[i] + r[i]);
            }
            float ox = x0 < safeLeft ? safeLeft - x0 : x1 > safeRight ? safeRight - x1 : 0;
            float oy = y0 < safeTop ? safeTop - y0 : y1 > safeBottom ? safeBottom - y1 : 0;
            if (ox != 0 || oy != 0) for (int i = 0; i < n; i++) if (groupOf(i) == g) { cx[i] += ox; cy[i] += oy; }
            gbox[g] = new RectF(x0 + ox, y0 + oy, x1 + ox, y1 + oy);
        }
    }

    private boolean custom() {
        for (int g = 0; g < GROUPS; g++) if (gdx[g] != 0 || gdy[g] != 0 || gsc[g] != 1) return true;
        return placeX != 0.5f || placeY != 0.5f;
    }

    private void load() {
        boolean v2 = prof.startsWith("v2/");   // a skin's geometry starts from its own defaults; the old Classic / Zelda edits stay stored under their keys
        for (int g = 0; g < GROUPS; g++) {
            String oldScreen = prof.substring(prof.lastIndexOf('/') + 1);
            String fallback = TouchProfile.CLASSIC.equals(profile) && !v2 ? prefs().getString("group" + g + "@" + oldScreen, "0 0 1") : "0 0 1";
            String[] v = prefs().getString("group" + g + "@" + prof, fallback).split(" ");
            try { gdx[g] = Float.parseFloat(v[0]); gdy[g] = Float.parseFloat(v[1]); gsc[g] = Float.parseFloat(v[2]); }
            catch (RuntimeException e) { gdx[g] = 0; gdy[g] = 0; gsc[g] = 1; }
        }
        String oldScreen = prof.substring(prof.lastIndexOf('/') + 1);
        String fallback = TouchProfile.CLASSIC.equals(profile) ? prefs().getString("picture@" + oldScreen, "0.5 0.5") : "0.5 0.5";
        if (v2 && baseKey != null) fallback = prefs().getString("picture@" + baseKey, fallback);   // the picture stays where the user put it
        String[] v = prefs().getString("picture@" + prof, fallback).split(" ");
        try { placeX = Float.parseFloat(v[0]); placeY = Float.parseFloat(v[1]); } catch (RuntimeException e) { placeX = placeY = 0.5f; }
    }

    /** Whether the user moved or resized a group of the profile's old placement on this screen shape (its v1 key; for Classic also the global key it started from) */
    private boolean legacyCustom(String key, String screen) {
        boolean classic = TouchProfile.CLASSIC.equals(profile);   // only Classic's layouts started from the global keys (load)
        for (int g = 0; g < GROUPS; g++) {
            String[] v = prefs().getString("group" + g + "@" + key, classic ? prefs().getString("group" + g + "@" + screen, "0 0 1") : "0 0 1").split(" ");
            try { if (Float.parseFloat(v[0]) != 0 || Float.parseFloat(v[1]) != 0 || Float.parseFloat(v[2]) != 1) return true; }
            catch (RuntimeException e) { /* unreadable: the defaults */ }
        }
        return false;
    }

    private void saveLayout() {
        SharedPreferences.Editor e = prefs().edit();
        for (int g = 0; g < GROUPS; g++) e.putString("group" + g + "@" + prof, gdx[g] + " " + gdy[g] + " " + gsc[g]);
        e.putString("picture@" + prof, placeX + " " + placeY).commit();   // commit: the game process may end right after (Stop)
    }

    private void relayout() { layout(getWidth(), getHeight()); }

    /** Where the picture sits vertically on this screen: 0 top, 0.5 centred, 1 bottom (the panel's Picture row); never scaled or cropped */
    float picturePosition() { return placeY; }
    void setPicturePosition(float y) {
        if (prof == null) return;   // not laid out yet
        placeY = Math.max(0, Math.min(1, y));
        relayout(); saveLayout();
        Native.note(String.format(java.util.Locale.ROOT, "picture placed at y %.2f of the free space on screen %s", placeY, prof));
    }

    /** Run when the editor opens, before it draws: closes what opened it (the in-game panel sets it to its close) and hides what lies over the controls (Paused) */
    Runnable onEditStart;
    /** Run when the editor closes (Done): shows again what onEditStart hid */
    Runnable onEditEnd;

    boolean editing() { return editing; }

    /** The layout editor: drag a group of controls to move it, pinch it to resize it, drag the picture to move it into the black bars; Done keeps it for this screen shape */
    void startEditLayout() {
        if (editing || prof == null) return;
        if (onEditStart != null) onEditStart.run();
        editing = true; shown = true; gamepad = false;
        Native.note("on-screen controls: the layout editor is open (screen " + prof + ")");
        apply();
    }

    private void endEditLayout() {
        editing = false; dragG = -1; dragId = -1; pinchId = -1;
        saveLayout(); relayout();
        if (onEditEnd != null) onEditEnd.run();
    }

    private void resetLayout() {
        Arrays.fill(gdx, 0); Arrays.fill(gdy, 0); Arrays.fill(gsc, 1); placeX = placeY = 0.5f;
        // Restore defaults on a skinned profile's old placement in landscape (Classic's, Zelda's): the skin's geometry from now on (saved below under its key);
        // the old edits stay stored
        if (skin != null && getWidth() > getHeight() && prof != null && !prof.startsWith("v2/"))
            prof = TouchProfile.skinLayoutKey(gameId, skin, prof.substring(prof.lastIndexOf('/') + 1));
        relayout(); saveLayout();
    }

    /** The rows for the layout, for the controls' settings: the picture's position and the editor (which runs onEditStart) */
    void layoutRows(Context ctx, LinearLayout box) {
        TextView t = new TextView(ctx);
        t.setText("Picture position (this screen)");
        android.widget.RadioGroup rg = new android.widget.RadioGroup(ctx);
        rg.setOrientation(LinearLayout.HORIZONTAL);
        String[] names = {"Top", "Centre", "Bottom"};
        float[] at = {0, 0.5f, 1};
        for (int i = 0; i < 3; i++) {
            android.widget.RadioButton b = new android.widget.RadioButton(ctx);
            b.setText(names[i]); b.setId(View.generateViewId());
            rg.addView(b);
            if (Math.abs(placeY - at[i]) < 0.01f) b.setChecked(true);
            float y = at[i];
            b.setOnCheckedChangeListener((v, on) -> { if (on) setPicturePosition(y); });
        }
        android.widget.Button ed = new android.widget.Button(ctx);
        ed.setText("Edit the controls layout…");
        ed.setOnClickListener(v -> startEditLayout());
        box.addView(t); box.addView(rg); box.addView(ed);
    }

    // ---- The editor's touches ----
    private boolean editTouch(MotionEvent e) {
        int act = e.getActionMasked(), i = e.getActionIndex(), id = e.getPointerId(i);
        float x = e.getX(i), y = e.getY(i);
        switch (act) {
            case MotionEvent.ACTION_DOWN: {
                for (int k = 0; k < tool.length; k++) if (tool[k] != null && tool[k].contains(x, y)) { toolTap(k); return true; }
                dragG = -1;
                float pad = 10 * unit();
                for (int g = 0; g < GROUPS; g++)
                    if (gbox[g] != null && x >= gbox[g].left - pad && x <= gbox[g].right + pad && y >= gbox[g].top - pad && y <= gbox[g].bottom + pad) { dragG = g; break; }
                if (dragG < 0 && x >= picX * getWidth() && x <= (picX + picW) * getWidth() && y >= picY * getHeight() && y <= (picY + picH) * getHeight()) dragG = GROUPS;
                dragId = id; lastX = x; lastY = y;
                invalidate();
                return true;
            }
            case MotionEvent.ACTION_POINTER_DOWN:
                if (dragG >= 0 && dragG < GROUPS && pinchId < 0) {
                    int j = e.findPointerIndex(dragId);
                    if (j < 0) return true;
                    pinchId = id; pinchD0 = (float) Math.hypot(x - e.getX(j), y - e.getY(j)); pinchS0 = gsc[dragG];
                }
                return true;
            case MotionEvent.ACTION_MOVE: {
                int j = e.findPointerIndex(dragId);
                if (dragG < 0 || j < 0) return true;
                float mx = e.getX(j), my = e.getY(j), u = unit();
                if (pinchId >= 0) {
                    int q = e.findPointerIndex(pinchId);
                    if (q >= 0 && pinchD0 > 0) gsc[dragG] = Math.max(0.5f, Math.min(2f, pinchS0 * (float) Math.hypot(mx - e.getX(q), my - e.getY(q)) / pinchD0));
                } else if (dragG < GROUPS) {
                    gdx[dragG] += (mx - lastX) / u; gdy[dragG] += (my - lastY) / u;
                } else {
                    float fx = getWidth() * (1 - picW), fy = getHeight() * (1 - picH);
                    if (fx > 1) placeX = snap(placeX + (mx - lastX) / fx);
                    if (fy > 1) placeY = snap(placeY + (my - lastY) / fy);
                }
                lastX = mx; lastY = my;
                relayout();
                return true;
            }
            case MotionEvent.ACTION_POINTER_UP:
                if (id == pinchId) pinchId = -1;
                else if (id == dragId) { dragG = -1; dragId = -1; pinchId = -1; }
                return true;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                if (dragG == GROUPS) { placeX = snapEnd(placeX); placeY = snapEnd(placeY); relayout(); }
                dragG = -1; dragId = -1; pinchId = -1;
                saveLayout(); invalidate();
                return true;
            default:
                return true;
        }
    }

    // The picture's position: free while dragged (clamped), pulled to the top, the centre and the bottom near them
    private static float snap(float v) { return Math.max(0, Math.min(1, v)); }
    private static float snapEnd(float v) {
        for (float t : new float[] {0, 0.5f, 1}) if (Math.abs(v - t) < 0.06f) return t;
        return v;
    }

    private void toolTap(int k) {
        if (haptics) performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
        if (k <= 2) { placeY = k * 0.5f; relayout(); saveLayout(); }
        else if (k == 3) resetLayout();
        else { endEditLayout(); Native.note("on-screen controls: layout kept for screen " + prof + (custom() ? "" : " (the automatic one)")); }
        invalidate();
    }

    // ---- Touches: the show / hide button is the launcher's; every other pointer goes to the host ----
    private void send(int action, int id, float x, float y) { if (input) Native.touch(action, id, x / getWidth(), y / getHeight()); }

    void cancelInput() {
        removeCallbacks(longPress); toggleId = -1; gearId = -1;
        if (input) Native.touch(MotionEvent.ACTION_CANCEL, 0, 0, 0);
        Arrays.fill(pressed, 0); Arrays.fill(prev, 0); Arrays.fill(sticks, 0); Arrays.fill(fadeBits, 0);
        invalidate();
    }

    void setSuspended(boolean value) {
        cancelInput(); suspended = value; apply();
    }

    @Override protected void onDetachedFromWindow() { cancelInput(); super.onDetachedFromWindow(); }
    @Override public void onWindowFocusChanged(boolean focus) { super.onWindowFocusChanged(focus); if (!focus) cancelInput(); }

    /** A launcher button's grab radius, shrunk so it stops 2 dp short of every control's touch circle, never below its own artwork. */
    private float grabApart(float x, float y, float art, float grab, float gap) {
        for (int i = 0; i < n; i++) grab = Math.min(grab, (float) Math.hypot(cx[i] - x, cy[i] - y) - r[i] - gap);
        return Math.max(art, grab);
    }
    private boolean onToggle(float x, float y) { float dx = x - tx, dy = y - ty, g = toggleGrab; return available && dx * dx + dy * dy <= g * g; }
    /** A sprite skin's gear: shown with the controls, it opens the controls' settings and sends nothing to the game */
    private boolean gearShown() { return skinBitmap() != null && active() && !editing; }

    private static int skinIndex(TouchProfile.Skin s) { return s == TouchProfile.ZELDA40_SKIN ? 1 : 0; }
    private static int skinResource(TouchProfile.Skin s) {
        return s == TouchProfile.ZELDA40_SKIN ? dev.nxnative.android.R.drawable.s2_zelda40_controls : dev.nxnative.android.R.drawable.s2_standard_controls_v2;
    }
    /** The current skin's decoded atlas; null without a skin or when it did not decode (the controls are then drawn as plain shapes) */
    private Bitmap skinBitmap() { return skin == null ? null : skinAtlas[skinIndex(skin)]; }
    private boolean onGear(float x, float y) { float dx = x - gx, dy = y - gy; return gearShown() && dx * dx + dy * dy <= gearGrab * gearGrab; }

    @Override public boolean onTouchEvent(MotionEvent e) {
        if (suspended) return true;
        if (editing) return editTouch(e);
        int act = e.getActionMasked();
        switch (act) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN: {
                int i = e.getActionIndex(), id = e.getPointerId(i);
                if (toggleId < 0 && onToggle(e.getX(i), e.getY(i))) {
                    toggleId = id; toggleLong = false;
                    postDelayed(longPress, 600);
                    if (haptics) performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    return true;
                }
                if (gearId < 0 && onGear(e.getX(i), e.getY(i))) {   // the launcher's own: never reaches the host
                    gearId = id;
                    if (haptics) performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    invalidate();
                    return true;
                }
                send(act, id, e.getX(i), e.getY(i));
                break;
            }
            case MotionEvent.ACTION_MOVE:
                for (int i = 0; i < e.getPointerCount(); i++) {
                    int id = e.getPointerId(i);
                    if (id != toggleId && id != gearId) send(act, id, e.getX(i), e.getY(i));
                }
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP: {
                int i = e.getActionIndex(), id = e.getPointerId(i);
                if (id == toggleId) {
                    toggleId = -1;
                    removeCallbacks(longPress);
                    if (!toggleLong && onToggle(e.getX(i), e.getY(i))) toggle();
                    return true;
                }
                if (id == gearId) {
                    gearId = -1; invalidate();
                    if (onGear(e.getX(i), e.getY(i))) settings();
                    return true;
                }
                send(act, id, e.getX(i), e.getY(i));
                break;
            }
            case MotionEvent.ACTION_CANCEL:
                toggleId = -1; gearId = -1;
                removeCallbacks(longPress);
                send(act, 0, 0, 0);
                break;
            default:
                return true;
        }
        poll();
        return true;
    }

    /** What the controls hold after a touch: a tick for each new press, a redraw when anything changed */
    private void poll() {
        if (!active() || !input) return;
        float s0 = sticks[0], s1 = sticks[1], s2 = sticks[2], s3 = sticks[3];
        Native.touchControlsState(pressed, sticks);
        boolean changed = s0 != sticks[0] || s1 != sticks[1] || s2 != sticks[2] || s3 != sticks[3], tick = false;
        for (int i = 0; i < n; i++) {
            if (pressed[i] != prev[i]) changed = true;
            if ((pressed[i] & ~prev[i]) != 0) tick = true;
            long released = prev[i] & ~pressed[i];
            if (released != 0) { fadeBits[i] = released; fadeAt[i] = android.os.SystemClock.uptimeMillis(); }   // the release animation (drawStandard)
            prev[i] = pressed[i];
        }
        if (tick && haptics) performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
        if (changed) invalidate();
    }

    // ---- Drawing ----
    private int alpha(float a) { return Math.max(0, Math.min(255, Math.round(255 * a * opacity))); }

    @Override protected void onDraw(Canvas c) {
        if (!available) return;
        float dp = getResources().getDisplayMetrics().density;
        line.setStrokeWidth(Math.max(1.5f, 1.6f * dp));
        fading = false;
        if (editing) { drawControls(c); drawEditor(c, dp); finishFrame(); return; }
        boolean on = active();
        if (skinBitmap() != null) {
            // The skin's show / hide sprite, faint and struck through while the controls are hidden
            drawSprite(c, skin.visibility, tx, ty, tr, tr, on ? Math.max(opacity, .55f) : .45f, 0, 2);
            if (!on) {
                line.setColor(skin.strike);
                c.drawLine(tx - tr * 0.7f, ty + tr * 0.7f, tx + tr * 0.7f, ty - tr * 0.7f, line);
            }
        } else {
            // The show / hide button: a small pad outline, faint while the controls are hidden
            float ta = on ? 1f : 0.7f;
            fill.setColor(Color.argb(Math.round(255 * 0.35f * ta), 0, 0, 0));
            c.drawCircle(tx, ty, tr, fill);
            line.setColor(Color.argb(Math.round(255 * 0.8f * ta), 255, 255, 255));
            c.drawCircle(tx, ty, tr, line);
            rect.set(tx - tr * 0.6f, ty - tr * 0.3f, tx + tr * 0.6f, ty + tr * 0.35f);
            c.drawRoundRect(rect, tr * 0.3f, tr * 0.3f, line);
            if (!on) c.drawLine(tx - tr * 0.65f, ty + tr * 0.65f, tx + tr * 0.65f, ty - tr * 0.65f, line);
        }
        if (!on) return;
        drawControls(c);
        if (gearShown()) drawSprite(c, skin.settings, gx, gy, gr, gr, Math.max(opacity, .55f), gearId >= 0 ? 1 : 0, 2);
        finishFrame();
    }

    /** Keeps redrawing while a release animation runs */
    private void finishFrame() { if (fading) postInvalidateOnAnimation(); }

    private void drawControls(Canvas c) {
        boolean zelda = TouchProfile.ZELDA.equals(profile);
        boolean standard = skinBitmap() != null;
        boolean motion = android.animation.ValueAnimator.areAnimatorsEnabled();   // off: the system's reduced motion (animator duration scale 0)
        long now = android.os.SystemClock.uptimeMillis();
        for (int i = 0; i < n; i++) {
            if (standard && (kind[i] != BUTTON || sprite[i] >= 0)) { drawStandard(c, i, now, motion); continue; }
            boolean held = pressed[i] != 0;
            fill.setColor(held ? Color.argb(alpha(0.55f), 255, 255, 255) : Color.argb(alpha(0.35f), 0, 0, 0));
            line.setColor(zelda ? Color.argb(alpha(.9f), 223, 192, 112) : Color.argb(alpha(0.9f), 255, 255, 255));
            if (kind[i] == STICK) drawStick(c, i);
            else if (kind[i] == DPAD) drawDpad(c, i);
            else {
                if (TouchProfile.RACING.equals(profile) && actions[i] != null) {
                    if (atlas != null && raceSource(actions[i])) drawRaceArtwork(c, i, held);
                    else drawRaceButton(c, i, held);
                    continue;
                }
                if (icons[i] >= 0 && atlas != null) {
                    drawAction(c, i, held);
                    continue;
                }
                if (shape[i] == SHAPE_SHOULDER) {
                    rect.set(cx[i] - r[i], cy[i] - r[i] * 0.62f, cx[i] + r[i], cy[i] + r[i] * 0.62f);
                    c.drawRoundRect(rect, r[i] * 0.5f, r[i] * 0.5f, fill);
                    c.drawRoundRect(rect, r[i] * 0.5f, r[i] * 0.5f, line);
                } else {
                    c.drawCircle(cx[i], cy[i], r[i], fill);
                    c.drawCircle(cx[i], cy[i], r[i], line);
                }
                text.setColor(held ? Color.argb(alpha(1f), 0, 0, 0) : Color.argb(alpha(1f), 255, 255, 255));
                text.setTextSize(r[i] * (label[i].length() > 1 ? 0.72f : 0.95f));
                c.drawText(label[i], cx[i], cy[i] - (text.descent() + text.ascent()) / 2, text);
            }
        }
    }

    /** How lit a control's bits are: 1 while held, then fading out over RELEASE_MS (none with reduced motion) */
    private float glow(int i, long bits, long now, boolean motion) {
        if ((pressed[i] & bits) != 0) return 1;
        if (!motion || (fadeBits[i] & bits) == 0) return 0;
        float t = (now - fadeAt[i]) / (float) RELEASE_MS;
        if (t >= 1 || t < 0) return 0;
        fading = true;
        return 1 - t;
    }

    /** One control of the current skin: its sprite (four for the D-pad; a fixed base and a moving cap for a stick), lit by side while held */
    private void drawStandard(Canvas c, int i, long now, boolean motion) {
        int accent = cx[i] < getWidth() * 0.45f ? 0 : cx[i] > getWidth() * 0.55f ? 1 : 2;
        if (kind[i] == DPAD) {   // one 8-way region (the host keeps diagonals); each direction's sprite at the skin's measured offset, lit by its own bit
            float half = vw[i] * skin.dpadSprite;
            for (int k = 0; k < 4; k++) {
                float g = glow(i, DPAD_BITS[k], now, motion), s = motion ? 1 + 0.03f * g : 1;
                drawSprite(c, skin.dpad[k], cx[i] + skin.dpadDx[k] * vw[i], cy[i] + skin.dpadDy[k] * vh[i], half * s, half * s, opacity, g, accent);
            }
        } else if (kind[i] == STICK) {
            boolean left = stick[i] == 0;
            float sx = sticks[2 * stick[i]], sy = sticks[2 * stick[i] + 1];
            float travel = vw[i] * (left ? skin.travel : skin.rightTravel);
            float cap = left ? skin.cap : skin.rightCap;
            drawSprite(c, sprite[i], cx[i], cy[i], vw[i], vh[i], opacity, 0, accent);   // the base stays put
            drawSprite(c, left ? skin.leftCap : skin.rightCapSprite, cx[i] + sx * travel, cy[i] - sy * travel, vw[i] * cap, vh[i] * cap,
                    opacity, sx != 0 || sy != 0 ? 1 : 0, accent);   // the host's vector (y up, at most 1): centred again on release / cancel
        } else {
            float g = glow(i, buttons[i], now, motion), s = motion ? 1 + 0.03f * g : 1;   // the touch circle (r) does not grow
            drawSprite(c, sprite[i], cx[i], cy[i], vw[i] * s, vh[i] * s, opacity, g, accent);
        }
    }

    /** A sprite of the current skin's atlas, centred in a half-extent box and aspect-preserving; its own alpha times a, raised modestly and tinted while lit */
    private void drawSprite(Canvas c, int s, float x, float y, float hw, float hh, float a, float glow, int accent) {
        Bitmap sheet = skinBitmap();
        if (sheet == null || s < 0) return;
        source.set(skin.rect(s, 0), skin.rect(s, 1), skin.rect(s, 2), skin.rect(s, 3));
        float f = Math.min(2 * hw / source.width(), 2 * hh / source.height()), dw = source.width() * f / 2, dh = source.height() * f / 2;
        rect.set(x - dw, y - dh, x + dw, y + dh);
        artwork.setAlpha(Math.max(0, Math.min(255, Math.round(255 * a * (1 + 0.25f * glow)))));
        c.drawBitmap(sheet, source, rect, artwork);
        if (glow > 0) {   // a tint of the sprite's own silhouette (the skin's palette), no tile behind it
            tint.setColorFilter(tints[accent]);
            tint.setAlpha(Math.round(255 * skin.pressedAlpha * glow * Math.max(a, .5f)));
            c.drawBitmap(sheet, source, rect, tint);
        }
    }

    private void drawAction(Canvas c, int i, boolean held) {
        // Measured centres in the approved 1254px Bananza atlas, not a uniform tile grid. (Zelda's old icon atlas is no longer drawn: the anniversary skin has fixed glyphs.)
        int icon = icons[i], sx = ATLAS_X[icon % 4], sy = ATLAS_Y[icon / 4];
        int half = 150;
        source.set(sx - half, sy - half, sx + half, sy + half);
        float radius = r[i] * (held ? .94f : 1f);
        rect.set(cx[i] - radius, cy[i] - radius, cx[i] + radius, cy[i] + radius);
        artwork.setAlpha(alpha(held ? 1f : .95f));
        c.drawBitmap(atlas, source, rect, artwork);
        if (held) { line.setColor(0xFFFFD454); c.drawCircle(cx[i], cy[i], r[i], line); }
        text.setTextSize(Math.max(10 * getResources().getDisplayMetrics().density, r[i] * .36f));
        text.setColor(Color.argb(alpha(1), 255, 255, 255));
        float yLabel = cy[i] + radius * .78f;
        fill.setColor(Color.argb(alpha(.95f), 8, 18, 34));
        rect.set(cx[i] - text.measureText(label[i]) / 2 - 5, yLabel + text.ascent(), cx[i] + text.measureText(label[i]) / 2 + 5, yLabel + text.descent());
        c.drawRoundRect(rect, 5, 5, fill);
        c.drawText(label[i], cx[i], yLabel, text);
    }

    private void drawRaceButton(Canvas c, int i, boolean held) {
        String action = actions[i];
        int accent = "brake".equals(action) ? 0xFFFF7775 : "accelerate".equals(action) ? 0xFF65E4AC : 0xFF55DDF0;
        fill.setColor(Color.argb(alpha(held ? .95f : .8f), 8, 22, 40));
        line.setColor((alpha(1) << 24) | (accent & 0xffffff));
        c.drawCircle(cx[i], cy[i], r[i], fill); c.drawCircle(cx[i], cy[i], r[i], line);
        if (held) { fill.setColor((alpha(.25f) << 24) | (accent & 0xffffff)); c.drawCircle(cx[i], cy[i], r[i] * .9f, fill); }
        int name = raceActionLabel(action);
        String title = name == 0 ? label[i] : getContext().getString(name);
        text.setColor(Color.argb(alpha(1), 255, 255, 255));
        text.setTextSize(r[i] * .40f);
        if (text.measureText(title) > r[i] * 1.7f) text.setTextSize(text.getTextSize() * r[i] * 1.7f / text.measureText(title));
        c.drawText(title, cx[i], cy[i] - r[i] * .08f, text);
        text.setTextSize(r[i] * .35f); text.setColor((alpha(1) << 24) | (accent & 0xffffff));
        c.drawText(label[i], cx[i], cy[i] + r[i] * .43f, text);
    }

    /** Original generated racing sheet: measured bounds, preserving each pedal's aspect ratio. */
    private boolean raceSource(String action) {
        raceImage = atlas;
        switch (action) {
            case "steering": source.set(42, 65, 480, 493); break;
            case "accelerate": source.set(542, 65, 784, 493); break;
            case "brake": source.set(916, 65, 1165, 493); break;
            case "drift": source.set(52, 548, 430, 919); break;
            case "item": source.set(452, 548, 834, 919); break;
            case "rear_view": source.set(846, 548, 1230, 919); break;
            case "pause": source.set(105, 945, 370, 1208); break;
            case "rewind": source.set(488, 945, 760, 1208); break;
            case "jump": raceImage = racingActions; source.set(326, 28, 626, 328); break;
            case "map": raceImage = racingActions; source.set(326, 630, 626, 930); break;
            case "minus": raceImage = controllerArtwork; source.set(18, 944, 316, 1240); break;
            default: return false;
        }
        return raceImage != null;
    }

    private void drawRaceArtwork(Canvas c, int i, boolean held) {
        float radius = r[i] * (held ? .94f : 1f);
        float fit = radius * 2 / Math.max(source.width(), source.height());
        float hw = source.width() * fit / 2, hh = source.height() * fit / 2;
        rect.set(cx[i] - hw, cy[i] - hh, cx[i] + hw, cy[i] + hh);
        artwork.setAlpha(alpha(held ? 1 : .95f));
        c.drawBitmap(raceImage, source, rect, artwork);
        if (held) { line.setColor(0xFFFFD454); c.drawCircle(cx[i], cy[i], r[i], line); }
        text.setTextSize(r[i] * .35f); text.setColor(Color.argb(alpha(1), 255, 255, 255));
        text.setShadowLayer(3, 0, 1, Color.BLACK);
        c.drawText(label[i], cx[i], cy[i] + radius * .82f, text);
        text.clearShadowLayer();
    }

    private static int raceActionLabel(String action) {
        switch (action) {
            case "accelerate": return dev.nxnative.android.R.string.s2_race_gas;
            case "brake": return dev.nxnative.android.R.string.s2_race_brake;
            case "drift": return dev.nxnative.android.R.string.s2_race_drift;
            case "jump": return dev.nxnative.android.R.string.s2_race_jump;
            case "item": return dev.nxnative.android.R.string.s2_race_item;
            case "rear_view": return dev.nxnative.android.R.string.s2_race_rear;
            case "map": return dev.nxnative.android.R.string.s2_race_map;
            case "pause": return dev.nxnative.android.R.string.s2_race_pause;
            case "minus": return dev.nxnative.android.R.string.s2_race_minus;
            case "rewind": return dev.nxnative.android.R.string.s2_race_rewind;
            default: return 0;
        }
    }

    static int profileLabel(String value) {
        if (TouchProfile.ZELDA.equals(value)) return dev.nxnative.android.R.string.s2_touch_zelda;
        if (TouchProfile.BANANZA.equals(value)) return dev.nxnative.android.R.string.s2_touch_bananza;
        if (TouchProfile.RACING.equals(value)) return dev.nxnative.android.R.string.s2_touch_racing;
        return TouchProfile.CLASSIC.equals(value) ? dev.nxnative.android.R.string.s2_touch_classic : dev.nxnative.android.R.string.s2_touch_auto;
    }

    /** The editor: the picture's outline, each group's frame (the one held filled), the buttons along the top and what to do */
    private void drawEditor(Canvas c, float dp) {
        int w = getWidth(), h = getHeight();
        float u = unit();
        line.setColor(Color.argb(200, 255, 210, 60));
        rect.set(picX * w, picY * h, (picX + picW) * w, (picY + picH) * h);
        if (dragG == GROUPS) { fill.setColor(Color.argb(50, 255, 210, 60)); c.drawRect(rect, fill); }
        c.drawRect(rect, line);
        for (int g = 0; g < GROUPS; g++) {
            if (gbox[g] == null) continue;
            line.setColor(g == dragG ? Color.argb(255, 255, 210, 60) : Color.argb(160, 255, 255, 255));
            rect.set(gbox[g]); rect.inset(-4 * u, -4 * u);
            if (g == dragG) { fill.setColor(Color.argb(60, 255, 210, 60)); c.drawRoundRect(rect, 8 * u, 8 * u, fill); }
            c.drawRoundRect(rect, 8 * u, 8 * u, line);
        }
        float bw = 74 * u, bh = 34 * u, gap = 8 * u, x = (w - (TOOL.length * bw + (TOOL.length - 1) * gap)) / 2, y = 14 * u;
        text.setTextSize(15 * u);
        for (int k = 0; k < TOOL.length; k++, x += bw + gap) {
            if (tool[k] == null) tool[k] = new RectF();
            tool[k].set(x, y, x + bw, y + bh);
            boolean cur = k <= 2 && Math.abs(placeY - k * 0.5f) < 0.01f;
            fill.setColor(k == 4 ? Color.argb(230, 255, 210, 60) : cur ? Color.argb(230, 255, 255, 255) : Color.argb(200, 40, 40, 40));
            c.drawRoundRect(tool[k], 8 * u, 8 * u, fill);
            line.setColor(Color.argb(220, 255, 255, 255));
            c.drawRoundRect(tool[k], 8 * u, 8 * u, line);
            text.setColor(k == 4 || cur ? Color.BLACK : Color.WHITE);
            c.drawText(TOOL[k], tool[k].centerX(), tool[k].centerY() - (text.descent() + text.ascent()) / 2, text);
        }
        text.setTextSize(13 * u);
        text.setColor(Color.argb(230, 255, 255, 255));
        String[] groupNames = TouchProfile.RACING.equals(profile) ? new String[] {"steering", "map / pause / rewind", "pedals", "camera", "item / rear view", "drift / jump"} : GROUP_NAME;
        String hint = dragG >= 0 && dragG < GROUPS ? groupNames[dragG] + ": drag to move, a second finger to resize (" + Math.round(gsc[dragG] * 100) + " %)"
                : dragG == GROUPS ? "picture: drag into the black bars" : "Drag a control or the picture; pinch a control to resize it";
        c.drawText(hint, w / 2f, y + bh + 22 * u, text);
    }

    private void drawStick(Canvas c, int i) {
        float sx = sticks[2 * stick[i]], sy = sticks[2 * stick[i] + 1];
        if (TouchProfile.RACING.equals(profile) && stick[i] == 0 && atlas != null && raceSource("steering")) {
            c.save(); c.rotate(sx * 35, cx[i], cy[i]);
            rect.set(cx[i] - r[i], cy[i] - r[i], cx[i] + r[i], cy[i] + r[i]);
            artwork.setAlpha(alpha(1)); c.drawBitmap(atlas, source, rect, artwork); c.restore();
            return;
        }
        if (TouchProfile.RACING.equals(profile) && stick[i] == 1 && controllerArtwork != null) {
            artwork.setAlpha(alpha(1));
            source.set(8, 623, 334, 946);
            rect.set(cx[i]-r[i], cy[i]-r[i], cx[i]+r[i], cy[i]+r[i]);
            c.drawBitmap(controllerArtwork, source, rect, artwork);
            float radius=r[i]*.43f, x=cx[i]+sx*r[i]*.55f, y=cy[i]-sy*r[i]*.55f;
            source.set(344, 667, 612, 931); rect.set(x-radius,y-radius,x+radius,y+radius);
            c.drawBitmap(controllerArtwork, source, rect, artwork);
            return;
        }
        boolean held = sx != 0 || sy != 0;
        fill.setColor(TouchProfile.ZELDA.equals(profile) ? Color.argb(alpha(.6f), 4, 34, 23) : Color.argb(alpha(0.25f), 0, 0, 0));
        c.drawCircle(cx[i], cy[i], r[i], fill);
        c.drawCircle(cx[i], cy[i], r[i], line);
        float k = r[i] * 0.55f, kx = cx[i] + sx * k, ky = cy[i] - sy * k;
        fill.setColor(held ? Color.argb(alpha(0.6f), 255, 255, 255) : Color.argb(alpha(0.4f), 90, 90, 90));
        c.drawCircle(kx, ky, r[i] * 0.45f, fill);
        c.drawCircle(kx, ky, r[i] * 0.45f, line);
    }

    private void drawDpad(Canvas c, int i) {
        float x = cx[i], y = cy[i], rr = r[i], w = rr * 0.36f;
        fill.setColor(Color.argb(alpha(0.25f), 0, 0, 0));
        c.drawCircle(x, y, rr, fill);
        c.drawCircle(x, y, rr, line);
        long[] dirs = {UP, RIGHT, DOWN, LEFT};
        for (int k = 0; k < 4; k++) {
            boolean held = (pressed[i] & dirs[k]) != 0;
            path.reset();
            // a triangle pointing away from the centre, rotated a quarter turn per direction
            float[] pts = {0, -rr * 0.82f, w, -rr * 0.38f, -w, -rr * 0.38f};
            for (int j = 0; j < 6; j += 2) {
                float px = pts[j], py = pts[j + 1];
                for (int t = 0; t < k; t++) { float q = px; px = -py; py = q; }
                if (j == 0) path.moveTo(x + px, y + py); else path.lineTo(x + px, y + py);
            }
            path.close();
            fill.setColor(held ? Color.argb(alpha(0.9f), 255, 255, 255) : Color.argb(alpha(0.35f), 255, 255, 255));
            c.drawPath(path, fill);
        }
    }

    // ---- Settings: opacity, size and the haptic tick, kept in the app's preferences ----
    /** What a long press on the show / hide button opens: GameActivity's in-game panel (SidePanel), which holds these rows (controlRows) */
    Runnable openSettings;
    private void settings() { if (openSettings != null) openSettings.run(); }

    /** The on-screen controls' rows of the in-game panel: opacity, size, the haptic tick, the log over the game, and Reset */
    void controlRows(Context ctx, LinearLayout box) {
        TextView profileTitle = new TextView(ctx);
        profileTitle.setText(dev.nxnative.android.R.string.s2_touch_profile);
        box.addView(profileTitle);
        android.widget.RadioGroup profiles = new android.widget.RadioGroup(ctx);
        String choice = prefs().getString(setting("profile"), TouchProfile.AUTO);
        String[] choices = TouchProfile.choices(gameId);
        for (String value : choices) {
            android.widget.RadioButton option = new android.widget.RadioButton(ctx);
            option.setId(View.generateViewId()); option.setTag(value);
            option.setText(profileLabel(value));
            profiles.addView(option); option.setChecked(value.equals(choice));
        }
        profiles.setOnCheckedChangeListener((group, id) -> {
            View selected = group.findViewById(id); if (selected == null) return;
            cancelInput();
            String value = (String) selected.getTag();
            prefs().edit().putString(setting("profile"), value).commit();
            profile = TouchProfile.resolve(gameId, value); prof = null; baseKey = null;
            relayout();
        });
        box.addView(profiles);
        TextView hint = new TextView(ctx); hint.setText(dev.nxnative.android.R.string.s2_touch_per_game); box.addView(hint);
        if (TouchProfile.DK.equals(gameId)) { TextView dkHint = new TextView(ctx); dkHint.setText(dev.nxnative.android.R.string.s2_touch_dk_hint); box.addView(dkHint); }
        if (TouchProfile.OOT.equals(gameId)) {
            // The anniversary skin draws the controller's own letters: the old action-symbol picker is not offered, and the symbols saved for the old
            // artwork (zelda_icon_<action>@<title ID>) are kept, never erased
            TextView zeldaHint = new TextView(ctx); zeldaHint.setText(dev.nxnative.android.R.string.s2_zelda40_hint); box.addView(zeldaHint);
        }
        if (TouchProfile.MKW.equals(gameId)) {
            CheckBox automatic = new CheckBox(ctx);
            automatic.setText(dev.nxnative.android.R.string.s2_race_auto);
            automatic.setChecked(autoAccelerate);
            automatic.setOnCheckedChangeListener((button, on) -> {
                cancelInput(); autoAccelerate = on;
                prefs().edit().putBoolean(setting("race_auto"), on).commit();
                prof = null; baseKey = null; relayout();
            });
            box.addView(automatic);
            TextView raceHint = new TextView(ctx); raceHint.setText(dev.nxnative.android.R.string.s2_race_hint); box.addView(raceHint);
        }
        TextView ol = new TextView(ctx), sl = new TextView(ctx);
        SeekBar os = new SeekBar(ctx), ss = new SeekBar(ctx);
        CheckBox hb = new CheckBox(ctx), lb = new CheckBox(ctx);
        os.setMax(90); os.setProgress(Math.round(opacity * 100) - 10);   // 10..100 %
        ss.setMax(90); ss.setProgress(Math.round(scale * 100) - 60);     // 60..150 %
        hb.setText("Vibrate on press"); hb.setChecked(haptics);
        lb.setText("Show the log over the game"); lb.setChecked(showLog(ctx));
        Runnable labels = () -> { ol.setText("Opacity " + (os.getProgress() + 10) + " %"); sl.setText("Size " + (ss.getProgress() + 60) + " %"); };
        labels.run();
        SeekBar.OnSeekBarChangeListener live = new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar b, int v, boolean user) {
                labels.run();
                opacity = (os.getProgress() + 10) / 100f;
                float ns = (ss.getProgress() + 60) / 100f;
                if (ns != scale) { scale = ns; layout(getWidth(), getHeight()); }
                invalidate();
                save();
            }
            @Override public void onStartTrackingTouch(SeekBar b) {}
            @Override public void onStopTrackingTouch(SeekBar b) {}
        };
        os.setOnSeekBarChangeListener(live);
        ss.setOnSeekBarChangeListener(live);
        hb.setOnCheckedChangeListener((b, v) -> { haptics = v; save(); });
        lb.setOnCheckedChangeListener((b, v) -> prefs().edit().putBoolean("log", v).commit());
        android.widget.Button reset = new android.widget.Button(ctx);
        reset.setText("Reset the controls");
        reset.setOnClickListener(v -> { os.setProgress(skin != null ? Math.round(skin.opacity * 100) - 10 : 50); ss.setProgress(40); hb.setChecked(true); });   // 60 % opacity (a skin's own, 65 %), 100 % size, the tick on
        box.addView(ol); box.addView(os); box.addView(sl); box.addView(ss); box.addView(hb); box.addView(lb); box.addView(reset);
        layoutRows(ctx, box);   // the picture position and the layout editor
    }

    /** Whether GameActivity keeps the newest log lines over the picture once the game draws (off by default; the settings dialog's last box) */
    static boolean showLog(Context c) { return Prefs.open(c, "touch_controls").getBoolean("log", false); }

    private void save() { prefs().edit().putFloat(setting("opacity"), opacity).putFloat(setting("scale"), scale).putBoolean(setting("haptics"), haptics).commit(); }
}
