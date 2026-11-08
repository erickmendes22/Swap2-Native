package dev.nxnative.android;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;

/**
 * The selected cover's focus frame in the library carousel (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md, "Richer library finish"; thinned by
 * docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 2): one thin ring in the theme's neutral focus color with the brand's small cyan / coral offset edges
 * (top-left and bottom-right, hairlines at reduced alpha), drawn around the art with a gap that clears its 1.02x focus scale. Its whole extent stays within
 * 5.5 dp of the art (the slot's 6 dp pad). A static drawable on the card's slot: nothing is allocated while drawing, nothing animates by itself; setArt
 * follows the cover's side when the library fits the covers to the window.
 */
final class CoverFrame extends Drawable {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF art = new RectF(), r = new RectF();
    private final float ring, edge, offset, gap, radius;
    private final int focus, cyan, coral;
    private boolean on;

    /** pad: the art's distance from the slot's left and top; size: the art's side */
    CoverFrame(Context c, int pad, int size, float artRadiusPx) {
        ring = Ui.dp(c, 1.75f);
        edge = Ui.dp(c, 1f);
        offset = Ui.dp(c, 1.25f);
        gap = Ui.dp(c, 3.5f);
        radius = artRadiusPx + gap;
        focus = Ui.col(c, R.color.bn_banana);
        cyan = Ui.col(c, R.color.s2_brand_cyan);
        coral = Ui.col(c, R.color.s2_brand_coral);
        art.set(pad, pad, pad + size, pad + size);
        paint.setStyle(Paint.Style.STROKE);
    }

    /** The art's new place in the slot (the covers fitted to the window again) */
    void setArt(int pad, int size) {
        if (art.left == pad && art.width() == size) return;
        art.set(pad, pad, pad + size, pad + size);
        invalidateSelf();
    }

    void setOn(boolean value) {
        if (on == value) return;
        on = value;
        invalidateSelf();
    }

    @Override public void draw(Canvas canvas) {
        if (!on) return;
        r.set(art);
        r.inset(-gap, -gap);
        paint.setStrokeWidth(edge);
        paint.setColor(cyan);
        paint.setAlpha(170);
        r.offset(-offset, -offset);
        canvas.drawRoundRect(r, radius, radius, paint);
        paint.setColor(coral);
        paint.setAlpha(170);
        r.offset(2 * offset, 2 * offset);
        canvas.drawRoundRect(r, radius, radius, paint);
        r.offset(-offset, -offset);
        paint.setStrokeWidth(ring);
        paint.setColor(focus);
        canvas.drawRoundRect(r, radius, radius, paint);
    }

    @Override public void setAlpha(int alpha) {}
    @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
}
