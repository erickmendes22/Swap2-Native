package dev.nxnative.android;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.Interpolator;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * The opening at a cold launcher start (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md "Brand v6", console-v4/motion.json "boot"): the v6 mark's three layers (upper
 * arrow, lower arrow, numeral 2: res/drawable[-night]/s2_*_v6.xml, the same 192x112 box, so they stack in three identically sized ImageViews) and the
 * Swap2-Native wordmark beneath, animated natively over the already built library, then faded into it. No video, no PNG, no wait for the library scan (it goes
 * on underneath). Once per process, only for a plain launcher start (not a return, a rotation, a recreation or a frontend / adb intent), and only with Settings ›
 * Opening animation on. Reduce motion or the system's animator scale off: the still lockup crossfades away in 120 ms. A tap or a key skips it; leaving the
 * launcher ends it.
 */
final class BrandIntro {
    private static boolean decided;   // this process already started the launcher once: never again

    private final FrameLayout root;
    private final View[] parts;
    private final Runnable gone;
    private boolean done;

    /** Whether this start shows the opening; decided at the first launcher start of the process, so later ones never do */
    static boolean wanted(Activity a, Bundle saved) {
        if (decided) return false;
        decided = true;
        if (saved != null || !LauncherTheme.opening(a)) return false;
        Intent i = a.getIntent();
        if (i == null || !Intent.ACTION_MAIN.equals(i.getAction()) || !i.hasCategory(Intent.CATEGORY_LAUNCHER)) return false;
        Bundle x = i.getExtras();
        if (x != null) for (String k : x.keySet())   // MainActivity.fromIntent's destinations go straight there
            if (k.equals("game") || k.equals("add_game") || k.equals("frontend_game") || k.startsWith("ondevice_") || k.startsWith("pack_") || k.startsWith("gpu_driver")) return false;
        return true;
    }

    /** Over everything in frame; gone runs once the launcher shows (focus goes back to the library) */
    static BrandIntro show(Activity a, FrameLayout frame, Runnable gone) { return new BrandIntro(a, frame, gone); }

    private BrandIntro(Activity a, FrameLayout frame, Runnable gone) {
        this.gone = gone;
        root = new FrameLayout(a);
        root.setBackgroundColor(Ui.col(a, R.color.bn_bg));
        root.setClickable(true);
        root.setFocusable(true);
        root.setFocusableInTouchMode(true);
        root.setContentDescription(a.getString(R.string.s2_intro_skip));
        root.setSoundEffectsEnabled(false);
        root.setOnClickListener(v -> finish());
        root.setOnKeyListener((v, code, e) -> {
            if (code == KeyEvent.KEYCODE_VOLUME_UP || code == KeyEvent.KEYCODE_VOLUME_DOWN || code == KeyEvent.KEYCODE_VOLUME_MUTE) return false;
            if (e.getAction() == KeyEvent.ACTION_DOWN) finish();
            return true;
        });

        // The mark at most 192 dp wide (motion.json's nominal box) and 42% of the window; travel scales with it
        android.content.res.Configuration cfg = a.getResources().getConfiguration();
        float widthDp = Math.min(192f, Math.min(cfg.screenWidthDp, cfg.screenHeightDp * 1.6f) * 0.42f);
        float scale = widthDp / 192f;
        int w = Ui.dp(a, widthDp), h = Math.round(w * 112f / 192f);
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        col.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        FrameLayout mark = new FrameLayout(a);
        ImageView upper = layer(a, R.drawable.s2_arrow_upper_v6), lower = layer(a, R.drawable.s2_arrow_lower_v6), two = layer(a, R.drawable.s2_number_2_v6);
        mark.addView(upper, new FrameLayout.LayoutParams(w, h));
        mark.addView(lower, new FrameLayout.LayoutParams(w, h));
        mark.addView(two, new FrameLayout.LayoutParams(w, h));
        col.addView(mark, new LinearLayout.LayoutParams(w, h));
        TextView word = Ui.text(a, a.getString(R.string.s2_wordmark), Math.max(16f, 26f * scale), R.color.bn_text, 600);
        word.setSingleLine(true);
        word.setEllipsize(TextUtils.TruncateAt.END);
        word.setIncludeFontPadding(false);
        LinearLayout.LayoutParams wl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        wl.topMargin = Ui.dp(a, 14 * scale + 4);
        col.addView(word, wl);
        root.addView(col, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        parts = new View[] {upper, lower, two, word};
        frame.addView(root, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.requestFocus();

        if (LauncherTheme.still(a)) {   // the still lockup, crossfaded away (motion.json reduced_motion.boot_ms)
            root.post(() -> { if (!done) root.animate().alpha(0f).setDuration(120).withEndAction(this::finish).start(); });
            return;
        }
        LauncherEffects.boot(a);   // the opening's cue near its start, only if loaded by then (motion.json: optional with reduced motion, so not over the 120 ms crossfade)
        Interpolator arrow = new PathInterpolator(0.2f, 0.8f, 0.2f, 1f), ease = new DecelerateInterpolator();
        float unit = a.getResources().getDisplayMetrics().density * scale;
        enter(upper, -36 * unit, 0, 0, 440, arrow);
        enter(lower, 36 * unit, 0, 120, 440, arrow);
        enter(two, 0, 5 * unit, 420, 240, ease);
        enter(word, 0, 6 * unit, 660, 240, ease);
        root.animate().alpha(0f).setStartDelay(1320).setDuration(180).setInterpolator(ease).withEndAction(this::finish).start();
    }

    private static ImageView layer(Activity a, int drawable) {
        ImageView v = new ImageView(a);
        v.setImageResource(drawable);
        v.setScaleType(ImageView.ScaleType.FIT_CENTER);
        v.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        return v;
    }

    private static void enter(View v, float fromX, float fromY, long delay, long duration, Interpolator i) {
        v.setAlpha(0f);
        v.setTranslationX(fromX);
        v.setTranslationY(fromY);
        v.animate().alpha(1f).translationX(0f).translationY(0f).setStartDelay(delay).setDuration(duration).setInterpolator(i).start();
    }

    boolean showing() { return !done; }

    /** Ends it now (a skip, the end of the timeline, the launcher leaving the foreground): every animator cancelled, the overlay removed */
    void finish() {
        if (done) return;
        done = true;
        LauncherEffects.stopBoot();   // a skip ends its cue too
        for (View v : parts) v.animate().cancel();
        root.animate().cancel();
        ViewGroup parent = (ViewGroup) root.getParent();
        if (parent != null) parent.removeView(root);
        gone.run();
    }

    /** Its overlay (MainActivity.build keeps it when the page is built again) */
    boolean owns(View v) { return v == root; }

    /** MainActivity.build keeps it above a page built again under it */
    void raise() { if (!done) root.bringToFront(); }
}
