package dev.nxnative.android;

import android.content.Context;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.List;

/**
 * FSR 1 upscaling at the present (DM_VK_FSR, DM_VK_FSR_SHARP: dm/gfx/vk_android/vka_present.c), set from the in-game panel (SidePanel). The choice is kept for the next
 * starts (env, every game, as frame generation's) and sent to the running game as lines of its live control file (DM_CTL, android/TESTING.md "Live control"), which the
 * host reads within 100 ms and applies at the next frame; with DM_CTL= in env.txt (no reader) it takes effect at the next start. It acts only when the game's picture is
 * smaller than the screen (Game resolution Phone 720p or 1080p on a larger panel); the game's own rendering cost is set by Game resolution, not by this.
 * From Banana Native's Fsr.java (moceure/BananaNative 5efee20c), with its labels in res/values/strings.xml and res/values-pt/strings.xml
 */
final class Fsr {
    private Fsr() {}

    /** RCAS sharpness in stops: 0 is the strongest, each stop halves it (AMD's default 0.25) */
    static final float[] SHARPS = {0f, 0.25f, 0.5f, 1f};
    private static final int[] SHARP_NAMES = {R.string.s2_fsr_sharp_max, R.string.s2_fsr_sharp_default, R.string.s2_fsr_sharp_soft, R.string.s2_fsr_sharp_softer};

    /** A sharpness value's name (the nearest of SHARPS): the launcher's Settings › Performance shows and picks the same values as the in-game panel */
    static int sharpName(float v) {
        int best = 0;
        for (int k = 1; k < SHARPS.length; k++) if (Math.abs(SHARPS[k] - v) < Math.abs(SHARPS[best] - v)) best = k;
        return SHARP_NAMES[best];
    }

    static boolean on(Context c) { return Prefs.of(c).getBoolean("fsr", false); }
    static float sharp(Context c) { return Prefs.of(c).getFloat("fsr_sharp", 0.25f); }

    /** What the running game started with: the last DM_VK_FSR / DM_VK_FSR_SHARP lines of its env, where env.txt and env-<title ID>.txt come after env() and win; the panel
     *  shows these, not the setting, so a DM_VK_FSR=1 line in env.txt is shown on, and sends them with a change (push). Parsed as the host does (vka.h VKA_ENV: strtod,
     *  empty = the default, not a number = 0). Static, as GameActivity's overlayEnv: a panel built again for the same run keeps them; a change from the panel replaces
     *  only the value it changes; null (no start in this process) = the settings */
    private static Boolean runOn;
    private static Float runSharp;

    private static boolean shownOn(Context c) { return runOn != null ? runOn : on(c); }
    private static float shownSharp(Context c) { return runSharp != null ? runSharp : sharp(c); }

    static void started(Context c, List<String> env) {
        boolean o = on(c); float sh = sharp(c);
        for (String kv : env) {
            if (kv.startsWith("DM_VK_FSR=")) o = num(kv.substring(10), 0) != 0;
            else if (kv.startsWith("DM_VK_FSR_SHARP=")) sh = (float) num(kv.substring(16), 0.25);
        }
        runOn = o; runSharp = sh;
    }

    private static double num(String v, double def) {
        v = v.trim();
        if (v.isEmpty()) return def;
        try { return Double.parseDouble(v); } catch (NumberFormatException e) { return 0; }
    }

    /** The host's switches for a run (env.txt lines come after these and win) */
    static void env(Context c, List<String> env) {
        env.add("DM_VK_FSR=" + (on(c) ? 1 : 0));
        env.add("DM_VK_FSR_SHARP=" + sharp(c));
    }

    private static void push(Context c) {
        File ext = c.getExternalFilesDir(null);   // GameActivity's DM_CTL: <app files>/ctl.txt
        if (ext == null) return;
        try (FileWriter w = new FileWriter(new File(ext, "ctl.txt"), true)) {
            w.write("env DM_VK_FSR=" + (shownOn(c) ? 1 : 0) + "\nenv DM_VK_FSR_SHARP=" + shownSharp(c) + "\n");   // what the panel shows: the run's values with this change
        } catch (IOException e) { Native.note("[RED] FSR: the setting could not be sent to the game (" + e.getMessage() + "); it applies at the next start"); }
    }

    /** The in-game panel's rows: on / off and the sharpness, each applied at once */
    static void rows(Context c, LinearLayout box) {
        TextView head = new TextView(c);
        head.setText(c.getString(R.string.s2_fsr_head));
        head.setPadding(0, 24, 0, 0);
        box.addView(head);
        CheckBox on = new CheckBox(c);
        on.setText(c.getString(R.string.s2_fsr_on));
        on.setChecked(shownOn(c));
        on.setOnCheckedChangeListener((b, v) -> { Prefs.of(c).edit().putBoolean("fsr", v).commit(); runOn = v; push(c); });
        box.addView(on);
        TextView l = new TextView(c); l.setText(c.getString(R.string.s2_fsr_sharpness)); box.addView(l);
        RadioGroup g = new RadioGroup(c);
        g.setOrientation(LinearLayout.HORIZONTAL);
        float cur = shownSharp(c);
        for (int i = 0; i < SHARPS.length; i++) {
            RadioButton b = new RadioButton(c);
            b.setText(c.getString(SHARP_NAMES[i]));
            b.setId(3000 + i);
            g.addView(b);
            if (SHARPS[i] == cur) b.setChecked(true);
        }
        g.setOnCheckedChangeListener((gr, id) -> { Prefs.of(c).edit().putFloat("fsr_sharp", SHARPS[id - 3000]).commit(); runSharp = SHARPS[id - 3000]; push(c); });
        box.addView(g);
        TextView hint = new TextView(c);
        hint.setText(c.getString(R.string.s2_fsr_hint));
        hint.setTextSize(12);
        box.addView(hint);
    }
}
