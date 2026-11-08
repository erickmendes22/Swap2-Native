package dev.nxnative.android;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.view.animation.DecelerateInterpolator;

/**
 * A library cover's preparation stroke (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md): only along the cover's straight bottom edge, growing left to right from the
 * job's actual progress (old to new value over 220 ms, motion.json progress_ms), still while the job is paused, and nothing at all when no job is preparing this
 * game. Selection and focus are the slot's CoverFrame, never this. Independent of the card's layout.
 */
final class CardProgressBorder extends Drawable {
    private final Context context;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float stroke, radius;
    private final int track;
    private int color;
    private float progress, target;
    private boolean active;
    private ValueAnimator animator;

    CardProgressBorder(Context c) {
        context = c.getApplicationContext();
        stroke = Ui.dp(c, 4);
        radius = Ui.dp(c, 12);   // the cover's corner radius: the stroke stays on its straight part
        track = 0x59000000;      // a dark 35% track, readable over any artwork
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeCap(Paint.Cap.BUTT);
    }

    void update(boolean selected, boolean active, double value, int color) {
        boolean wasActive = this.active;
        this.active = active;
        this.color = color;
        float next = (float) value;
        boolean reduced = LauncherTheme.still(context);
        if (!active || !wasActive || reduced) {
            cancelAnimation();
            progress = target = next;
        } else if (next != target) {
            cancelAnimation();
            target = next;
            animator = ValueAnimator.ofFloat(progress, target);
            animator.setDuration(220);
            animator.setInterpolator(new DecelerateInterpolator());
            animator.addUpdateListener(animation -> {
                progress = (float) animation.getAnimatedValue();
                invalidateSelf();
            });
            animator.start();
        }
        invalidateSelf();
    }

    private void cancelAnimation() {
        if (animator != null) { animator.cancel(); animator = null; }
    }

    /** Hidden/detached cards settle immediately; no animation survives leaving the launcher. */
    void finishAnimation() {
        cancelAnimation();
        progress = target;
        invalidateSelf();
    }

    @Override public void draw(Canvas canvas) {
        if (!active) return;
        // The straight bottom edge between the rounded corners, never the perimeter
        float left = getBounds().left + radius;
        float right = getBounds().right - radius;
        float y = getBounds().bottom - stroke / 2;
        if (right <= left) return;
        paint.setStrokeWidth(stroke);
        paint.setColor(track);
        canvas.drawLine(left, y, right, y, paint);
        if (progress > 0) {
            paint.setColor(color);
            canvas.drawLine(left, y, left + (right - left) * Math.min(1f, progress), y, paint);
        }
    }

    @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); invalidateSelf(); }
    @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
}
