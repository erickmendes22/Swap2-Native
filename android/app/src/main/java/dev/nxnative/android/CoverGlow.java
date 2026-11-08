package dev.nxnative.android;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.animation.DecelerateInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The library's upper background (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md, "Richer library finish"): a softly enlarged impression of the selected game's real
 * cover at about 8% opacity, fading into the neutral background. The selection is debounced (200 ms), and each cover is softened once into a 24 px bitmap
 * (two downscales and a box blur, a few hundred pixels of work) that is kept for the next selections; the GPU stretches it with bilinear filtering, so there is no
 * decode, blur or RenderEffect per frame. No cover: the neutral background alone. A cover is known by its title ID and its file's size and modification time
 * (Covers.get decodes a new Bitmap on every Home rebuild, so the Bitmap object is no key), and only the 24 px softened bitmaps are kept.
 */
final class CoverGlow {
    private static final int SIDE = 24;
    private static final long DEBOUNCE_MS = 200;
    /** Softened covers (24 px wide, about 2 KB each) by cover key: a downloaded or replaced cover file is a new key */
    private static final Map<String, Bitmap> cache = new LinkedHashMap<String, Bitmap>(32, 0.75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, Bitmap> e) { return size() > 32; }
    };

    final FrameLayout view;
    private final ImageView image;
    private final float alpha;
    private final Handler main = new Handler(Looper.getMainLooper());
    private Runnable pending;
    private String shown;

    CoverGlow(Context c) {
        view = new FrameLayout(c);
        view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        image = new ImageView(c);
        image.setScaleType(ImageView.ScaleType.CENTER_CROP);
        image.setAlpha(0f);
        view.addView(image, new FrameLayout.LayoutParams(-1, -1));
        int bg = Ui.col(c, R.color.bn_bg);
        View veil = new View(c);   // the neutral veil: the lower part of the impression melts into the background
        veil.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[] {bg & 0x00FFFFFF, bg & 0x00FFFFFF, bg}));
        view.addView(veil, new FrameLayout.LayoutParams(-1, -1));
        alpha = LauncherTheme.night(c) ? 0.10f : 0.07f;
    }

    /** The selected game's cover (null: none yet), after the debounce; the same one again does nothing */
    void select(String titleId, Bitmap cover) {
        if (pending != null) main.removeCallbacks(pending);
        pending = () -> { pending = null; show(titleId, cover); };
        main.postDelayed(pending, DEBOUNCE_MS);
    }

    /** The launcher leaves Home: nothing left pending, and a fade under way ends at its target (so the same cover shown again is already there, never stuck
     *  half-faded) */
    void cancel() {
        if (pending != null) main.removeCallbacks(pending);
        pending = null;
        image.animate().cancel();
        if (shown != null) image.setAlpha(alpha);
        else { image.setAlpha(0f); image.setImageDrawable(null); }
    }

    /** A cover's identity: its title ID with its file's size and modification time; a cover shown but not kept (no file) by its bitmap */
    private static String key(String titleId, Bitmap cover) {
        File f = Covers.file(titleId);
        return f.isFile() ? titleId + "@" + f.length() + ":" + f.lastModified() : titleId + "#" + System.identityHashCode(cover);
    }

    private void show(String titleId, Bitmap cover) {
        String key = cover == null ? null : key(titleId, cover);
        if (key != null && key.equals(shown)) return;
        shown = key;
        boolean still = LauncherTheme.still(view.getContext());
        image.animate().cancel();
        if (cover == null) {
            if (still) { image.setAlpha(0f); image.setImageDrawable(null); }
            else image.animate().alpha(0f).setDuration(180).withEndAction(() -> { if (shown == null) image.setImageDrawable(null); }).start();
            return;
        }
        image.setImageBitmap(soft(key, cover));
        if (still) { image.setAlpha(alpha); return; }
        image.setAlpha(0f);
        image.animate().alpha(alpha).setDuration(220).setInterpolator(new DecelerateInterpolator()).start();
    }

    private static Bitmap soft(String key, Bitmap cover) {
        Bitmap kept = cache.get(key);
        if (kept != null) return kept;
        int w = SIDE, h = Math.max(1, Math.round(SIDE * cover.getHeight() / (float) Math.max(1, cover.getWidth())));
        Bitmap mid = Bitmap.createScaledBitmap(cover, w * 4, h * 4, true);   // two steps: one large bilinear step would alias
        Bitmap small = Bitmap.createScaledBitmap(mid, w, h, true);
        if (mid != cover && mid != small) mid.recycle();
        int[] px = new int[w * h], tmp = new int[w * h];
        small.getPixels(px, 0, w, 0, 0, w, h);
        for (int pass = 0; pass < 2; pass++) { box(px, tmp, w, h, true); box(tmp, px, w, h, false); }
        Bitmap out = Bitmap.createBitmap(px, w, h, Bitmap.Config.ARGB_8888);
        if (small != cover) small.recycle();
        cache.put(key, out);
        return out;
    }

    /** A 5-tap box blur along one axis, edges clamped */
    private static void box(int[] in, int[] out, int w, int h, boolean horizontal) {
        int n = horizontal ? w : h, lines = horizontal ? h : w;
        for (int l = 0; l < lines; l++)
            for (int i = 0; i < n; i++) {
                int a = 0, r = 0, g = 0, b = 0;
                for (int k = -2; k <= 2; k++) {
                    int j = Math.max(0, Math.min(n - 1, i + k));
                    int p = horizontal ? in[l * w + j] : in[j * w + l];
                    a += p >>> 24; r += (p >> 16) & 0xFF; g += (p >> 8) & 0xFF; b += p & 0xFF;
                }
                out[horizontal ? l * w + i : i * w + l] = (a / 5) << 24 | (r / 5) << 16 | (g / 5) << 8 | (b / 5);
            }
    }
}
