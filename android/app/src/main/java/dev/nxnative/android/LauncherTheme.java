package dev.nxnative.android;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.UiModeManager;
import android.content.Context;
import android.content.res.Configuration;
import android.content.res.Resources;
import android.os.Handler;
import android.os.Looper;

/**
 * The launcher's theme and opening choices (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md; Settings › Interface). Light, Dark or System: the launcher's palette is
 * res/values (light) and res/values-night (dark), so a choice other than System forces the night bit of the launcher activities' configuration (apply, from
 * attachBaseContext) and the app's own night mode (UiModeManager.setApplicationNightMode, which the Android 12+ system splash follows, kept by the system across
 * starts). The game's process draws with its own palettes and is never re-themed by this. Kept in Prefs "interface" with versioned keys beside the existing
 * "sounds" and "reduced_motion".
 */
final class LauncherTheme {
    private LauncherTheme() {}

    static final String SYSTEM = "system", LIGHT = "light", DARK = "dark";
    static final String[] MODES = {SYSTEM, LIGHT, DARK};
    private static final String KEY = "theme_v6", OPENING = "opening_v6";

    static String mode(Context c) {
        String v = Prefs.open(c, "interface").getString(KEY, SYSTEM);
        return LIGHT.equals(v) || DARK.equals(v) ? v : SYSTEM;
    }

    static int label(String mode) {
        return LIGHT.equals(mode) ? R.string.s2_theme_light : DARK.equals(mode) ? R.string.s2_theme_dark : R.string.s2_theme_system;
    }

    /** From an activity's attachBaseContext, before anything reads its resources: the chosen theme's night bit over the system's (System: nothing) */
    static void apply(Activity a) {
        String m = mode(a);
        if (SYSTEM.equals(m)) return;
        Configuration o = new Configuration();   // all fields undefined: only the night bit is overridden
        o.uiMode = LIGHT.equals(m) ? Configuration.UI_MODE_NIGHT_NO : Configuration.UI_MODE_NIGHT_YES;
        a.applyOverrideConfiguration(o);
    }

    /** A new choice: stored, given to the system (its splash, the next starts), and the activity redrawn in it when the system has not already done so */
    static void mode(Activity a, String m) {
        Prefs.open(a, "interface").edit().putString(KEY, m).commit();
        UiModeManager ui = a.getSystemService(UiModeManager.class);
        if (ui != null) ui.setApplicationNightMode(LIGHT.equals(m) ? UiModeManager.MODE_NIGHT_NO : DARK.equals(m) ? UiModeManager.MODE_NIGHT_YES : UiModeManager.MODE_NIGHT_AUTO);
        // The system relaunches the activity when the app's night mode changes what it shows; when it already shows the chosen palette (System chosen while
        // the system's mode is the one forced before, or the other way round) nothing is redrawn. Only an activity still alive and still in the other palette a
        // moment later is recreated here, so a relaunch by the system is never doubled, nor are two quick choices. The page and selection come from the saved state
        boolean want = DARK.equals(m) || (SYSTEM.equals(m) && systemNight());
        if (night(a) == want) return;
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            if (!a.isFinishing() && !a.isDestroyed() && night(a) != want && mode(a).equals(m)) a.recreate();
        }, 300);
    }

    /** The system's own night mode (not the app's override) */
    private static boolean systemNight() {
        return (Resources.getSystem().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
    }

    static boolean night(Context c) {
        return (c.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
    }

    /** The opening (the mark's native animation at a cold launcher start, BrandIntro): on by default */
    static boolean opening(Context c) { return Prefs.open(c, "interface").getBoolean(OPENING, true); }
    static void opening(Context c, boolean on) { Prefs.open(c, "interface").edit().putBoolean(OPENING, on).apply(); }

    /** No travel or scaling: the user's Reduce motion, or the system's animator scale off */
    static boolean still(Context c) { return LauncherEffects.reduced(c) || !ValueAnimator.areAnimatorsEnabled(); }
}
