package dev.nxnative.android;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;
import android.view.View;

/**
 * One of Settings › Interface's three theme tiles (Console revision 6, console-v4/mockups/settings-general-rich-v3.png): a miniature of the library drawn live
 * from the launcher's own resources in that theme (res/values or res/values-night colors and the v6 mark of drawable or drawable-night), so it always matches
 * what the choice gives; System shows light and dark split on a diagonal. The small squares are the user's real covers once Covers has them (cover()), else
 * plain surface tiles: no sample art. Drawn only when invalidated (a cover arriving, selection, focus), never per frame, with no allocation in onDraw. The tile
 * is the touch and focus target (48 dp or more high), read by TalkBack as its theme's name and whether it is selected.
 */
final class ThemePreview extends View {
    /** The colors and mark of one theme, read from a context configured for it */
    private static final class Palette {
        final int bg, card, text, text2, tint;
        final Drawable mark;

        Palette(Context themed) {
            bg = themed.getColor(R.color.bn_bg);
            card = themed.getColor(R.color.bn_card);
            text = themed.getColor(R.color.bn_text);
            text2 = themed.getColor(R.color.bn_text_2);
            tint = themed.getColor(R.color.bn_tint);
            mark = themed.getDrawable(R.drawable.s2_mark_v6).mutate();
        }
    }

    private final Palette light, dark;
    private final String mode;
    private final Bitmap[] covers = new Bitmap[4];
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final RectF r = new RectF(), dst = new RectF();
    private final Rect src = new Rect();
    private final Path clip = new Path(), half = new Path(), corner = new Path();
    private final int ring, edge, focusColor, checkFill, checkMark;
    private final float d;

    ThemePreview(Context c, String mode) {
        super(c);
        this.mode = mode;
        light = new Palette(themed(c, false));
        dark = new Palette(themed(c, true));
        d = c.getResources().getDisplayMetrics().density;
        ring = c.getColor(R.color.bn_text);
        edge = c.getColor(R.color.bn_card_stroke);
        focusColor = c.getColor(R.color.bn_banana);
        checkFill = c.getColor(R.color.bn_text);
        checkMark = c.getColor(R.color.bn_bg);
        setFocusable(true);
        setClickable(true);
        setSoundEffectsEnabled(false);
        setMinimumHeight(Math.round(48 * d));
    }

    private static Context themed(Context c, boolean night) {
        Configuration conf = new Configuration(c.getResources().getConfiguration());
        conf.uiMode = (conf.uiMode & ~Configuration.UI_MODE_NIGHT_MASK) | (night ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
        return c.createConfigurationContext(conf);
    }

    /** A real cover for square k (0..3), once Covers has it */
    void cover(int k, Bitmap b) {
        if (k < 0 || k >= covers.length) return;
        covers[k] = b;
        invalidate();
    }

    /**
     * Width / 1.8 high, at least 48 dp; on a short window (SettingsFrame.compact: a landscape phone) at most 64 dp, so the theme card leaves the pane's other
     * options in view (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 4: the miniature then shows the mark and the squares, without the dock when too low)
     */
    @Override protected void onMeasure(int w, int h) {
        int width = MeasureSpec.getSize(w);
        int height = Math.max(Math.round(48 * d), Math.round(width / 1.8f));
        if (SettingsFrame.compact(getContext())) height = Math.min(height, Math.round(64 * d));
        setMeasuredDimension(width, resolveSize(height, h));
    }

    @Override protected void onSizeChanged(int w, int h, int ow, int oh) {
        float inset = 4 * d;   // room for the selection ring and the focus ring
        r.set(inset, inset, w - inset, h - inset);
        clip.reset();
        clip.addRoundRect(r, 10 * d, 10 * d, Path.Direction.CW);
        half.reset();   // System: the dark half, right of a diagonal
        half.moveTo(w * 0.62f, 0);
        half.lineTo(w, 0);
        half.lineTo(w, h);
        half.lineTo(w * 0.40f, h);
        half.close();
    }

    @Override protected void drawableStateChanged() {
        super.drawableStateChanged();
        invalidate();   // the focus ring
    }

    @Override protected void onDraw(Canvas c) {
        int save = c.save();
        c.clipPath(clip);
        scene(c, LauncherTheme.DARK.equals(mode) ? dark : light);
        if (LauncherTheme.SYSTEM.equals(mode)) {
            c.clipPath(half);
            scene(c, dark);
        }
        c.restoreToCount(save);
        paint.setStyle(Paint.Style.STROKE);
        boolean on = isSelected();
        paint.setStrokeWidth((on ? 2.5f : 1f) * d);
        paint.setColor(on ? ring : edge);
        c.drawRoundRect(r, 10 * d, 10 * d, paint);
        if (isFocused()) {
            paint.setStrokeWidth(3 * d);
            paint.setColor(focusColor);
            float o = 2.5f * d;
            c.drawRoundRect(r.left - o, r.top - o, r.right + o, r.bottom + o, 12 * d, 12 * d, paint);
        }
        if (on) {   // the check badge at the top-right corner
            float cx = r.right - 9 * d, cy = r.top + 9 * d, rad = 8 * d;
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(checkFill);
            c.drawCircle(cx, cy, rad, paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(1.8f * d);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setColor(checkMark);
            c.drawLine(cx - 3.5f * d, cy, cx - 1 * d, cy + 2.5f * d, paint);
            c.drawLine(cx - 1 * d, cy + 2.5f * d, cx + 3.8f * d, cy - 2.6f * d, paint);
        }
    }

    /** The miniature library in one theme: background, the mark and the header's dashes, four squares, the dock's pill with its dots */
    private void scene(Canvas c, Palette p) {
        float w = r.width(), h = r.height(), x0 = r.left, y0 = r.top, pad = Math.max(6 * d, w * 0.06f);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(p.bg);
        c.drawRect(r, paint);
        float mh = Math.max(6 * d, h * 0.12f), mw = mh * 192f / 112f;
        p.mark.setBounds(Math.round(x0 + pad), Math.round(y0 + pad), Math.round(x0 + pad + mw), Math.round(y0 + pad + mh));
        p.mark.draw(c);
        paint.setColor(p.text2);
        float dash = Math.max(5 * d, w * 0.06f), dy = y0 + pad + mh / 2, dh = Math.max(1.5f * d, h * 0.02f);
        for (int k = 0; k < 3; k++) {
            float dx = x0 + w - pad - (3 - k) * dash * 1.35f;
            c.drawRoundRect(dx, dy - dh / 2, dx + dash, dy + dh / 2, dh, dh, paint);
        }
        float gap = Math.max(3 * d, w * 0.025f), top = y0 + pad + mh + Math.max(5 * d, h * 0.1f);
        float side = Math.min((w - 2 * pad - 3 * gap) / 4f, h * 0.42f);
        float left = x0 + (w - (4 * side + 3 * gap)) / 2f;
        for (int k = 0; k < 4; k++) {
            float sx = left + k * (side + gap);
            Bitmap b = covers[k];
            if (b == null || b.isRecycled()) {
                paint.setColor(p.tint);
                c.drawRoundRect(sx, top, sx + side, top + side, 3 * d, 3 * d, paint);
                continue;
            }
            int s = c.save();
            corner.reset();
            corner.addRoundRect(sx, top, sx + side, top + side, 3 * d, 3 * d, Path.Direction.CW);
            c.clipPath(corner);
            int bw = b.getWidth(), bh = b.getHeight(), m = Math.min(bw, bh);   // center crop to the square
            src.set((bw - m) / 2, (bh - m) / 2, (bw - m) / 2 + m, (bh - m) / 2 + m);
            dst.set(sx, top, sx + side, top + side);
            c.drawBitmap(b, src, dst, paint);
            c.restoreToCount(s);
        }
        float py = top + side + Math.max(5 * d, h * 0.08f), ph = Math.max(6 * d, h * 0.1f), pw = w * 0.42f, px = x0 + (w - pw) / 2;
        if (py + ph > y0 + h - 2 * d) return;   // a very low tile: no dock
        paint.setColor(p.card);
        c.drawRoundRect(px, py, px + pw, py + ph, ph / 2, ph / 2, paint);
        paint.setColor(p.text);
        float seg = pw / 4f, ry = py + ph / 2, rr = ph * 0.18f;
        c.drawRoundRect(px + seg * 0.5f - rr * 2, ry - rr, px + seg * 0.5f + rr * 2, ry + rr, rr, rr, paint);
        paint.setColor(p.text2);
        for (int k = 1; k < 4; k++) c.drawCircle(px + seg * (k + 0.5f), ry, rr, paint);
    }
}
