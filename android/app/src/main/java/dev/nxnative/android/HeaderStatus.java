package dev.nxnative.android;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;
import android.os.BatteryManager;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Home's status cluster (Console revision 6, console-v4/mockups/library-rich-v3.png: the time and battery at the top right of the library's header). The launcher
 * hides the system bars (Ui.immersive), so it shows the phone's own: the current time in the system's 12 / 24 hour format, and the battery's level with a charging
 * mark (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md: real device state only, no new permission). Nothing runs per frame: one receiver, registered while the activity is
 * resumed (start / stop), redraws on the minute's tick, a clock or time zone change and a battery change. TalkBack reads the whole cluster as one sentence.
 */
final class HeaderStatus {
    final LinearLayout view;
    private final Activity activity;
    private final TextView time, percent;
    private final View divider;
    private final ImageView battery;
    private final BatteryIcon icon;
    private final boolean showPercent;
    private boolean registered;
    private int level = -1;          // percent, or -1 without a battery (a TV box, an emulator without one)
    private boolean charging;

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            if (Intent.ACTION_BATTERY_CHANGED.equals(i.getAction())) battery(i);
            update();
        }
    };

    /** showPercent: the level as text beside the icon too (dropped on a narrow window, where TalkBack still reads it) */
    HeaderStatus(Activity a, boolean showPercent) {
        activity = a;
        this.showPercent = showPercent;
        view = Ui.row(a);
        view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);   // one sentence for the cluster; its parts are silent
        time = Ui.text(a, "", 15, R.color.bn_text, 600);
        time.setSingleLine(true);
        time.setIncludeFontPadding(false);
        time.setFontFeatureSettings("tnum");   // the minutes do not shift the cluster
        time.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        view.addView(time, Ui.wrap());
        divider = new View(a);   // the mockup's hairline between the time and the battery
        divider.setBackgroundColor(Ui.col(a, R.color.bn_card_stroke));
        LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(Ui.dp(a, 1), Ui.dp(a, 18));
        dl.leftMargin = Ui.dp(a, 12);
        dl.rightMargin = Ui.dp(a, 12);
        view.addView(divider, dl);
        percent = Ui.text(a, "", 13, R.color.bn_text_2, 500);
        percent.setSingleLine(true);
        percent.setIncludeFontPadding(false);
        percent.setFontFeatureSettings("tnum");
        percent.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams pl = Ui.wrap();
        pl.rightMargin = Ui.dp(a, 6);
        view.addView(percent, pl);
        icon = new BatteryIcon(a);
        battery = new ImageView(a);
        battery.setImageDrawable(icon);
        battery.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        view.addView(battery, Ui.wrap());
        battery(a.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED)));   // the sticky broadcast: the level before the first resume
        update();
    }

    /** A short window's header (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 1): the same cluster with a smaller clock, level and hairline */
    HeaderStatus compact() {
        time.setTextSize(13);
        percent.setTextSize(12);
        LinearLayout.LayoutParams dl = (LinearLayout.LayoutParams) divider.getLayoutParams();
        dl.height = Ui.dp(activity, 14);
        dl.leftMargin = dl.rightMargin = Ui.dp(activity, 8);
        divider.setLayoutParams(dl);
        return this;
    }

    /** onResume: the clock and the battery follow the phone (the sticky battery intent comes back from the registration itself) */
    void start() {
        if (registered) return;
        IntentFilter f = new IntentFilter();
        f.addAction(Intent.ACTION_TIME_TICK);
        f.addAction(Intent.ACTION_TIME_CHANGED);       // also sent when the 12 / 24 hour setting changes
        f.addAction(Intent.ACTION_TIMEZONE_CHANGED);
        f.addAction(Intent.ACTION_BATTERY_CHANGED);
        Intent sticky = activity.registerReceiver(receiver, f, Context.RECEIVER_NOT_EXPORTED);   // system broadcasts only
        registered = true;
        battery(sticky);
        update();
    }

    /** onPause, or the header is rebuilt or left */
    void stop() {
        if (!registered) return;
        registered = false;
        try { activity.unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) {}
    }

    private void battery(Intent i) {
        if (i == null) return;
        int raw = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
        boolean present = i.getBooleanExtra(BatteryManager.EXTRA_PRESENT, true);
        level = present && raw >= 0 && scale > 0 ? Math.round(raw * 100f / scale) : -1;
        charging = i.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
    }

    private void update() {
        // A fresh format each time (once a minute at most): it takes the current 12 / 24 hour setting, locale and time zone
        String now = android.text.format.DateFormat.getTimeFormat(activity).format(new java.util.Date());
        time.setText(now);
        boolean has = level >= 0;
        divider.setVisibility(has ? View.VISIBLE : View.GONE);
        battery.setVisibility(has ? View.VISIBLE : View.GONE);
        percent.setVisibility(has && showPercent ? View.VISIBLE : View.GONE);
        if (has) {
            percent.setText(activity.getString(R.string.s2_status_percent, level));
            icon.set(level, charging);
        }
        view.setContentDescription(!has ? now
                : activity.getString(charging ? R.string.s2_status_desc_charging : R.string.s2_status_desc, now, level));
    }

    /**
     * The battery in the kit's line style (1.6 dp strokes, round joins, the theme's text color): an outline, its terminal, the level as an inner bar (coral when
     * low and not charging), and while plugged a bolt knocked out of the bar. Drawn, not a kit icon: the bar follows the level
     */
    private static final class BatteryIcon extends Drawable {
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG), fill = new Paint(Paint.ANTI_ALIAS_FLAG), clear = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int w, h, textColor, lowColor, chargeColor;
        private final float d;
        private final RectF r = new RectF();
        private final Path bolt = new Path();
        private int level = 100;
        private boolean charging;

        BatteryIcon(Context c) {
            d = c.getResources().getDisplayMetrics().density;
            w = Math.round(28 * d);
            h = Math.round(16 * d);
            textColor = Ui.col(c, R.color.bn_text);
            lowColor = Ui.col(c, R.color.s2_coral);
            chargeColor = Ui.col(c, R.color.bn_leaf);
            line.setStyle(Paint.Style.STROKE);
            line.setStrokeWidth(1.6f * d);
            line.setStrokeJoin(Paint.Join.ROUND);
            line.setStrokeCap(Paint.Cap.ROUND);
            line.setColor(textColor);
            fill.setStyle(Paint.Style.FILL);
            clear.setStyle(Paint.Style.FILL_AND_STROKE);
            clear.setStrokeWidth(1.4f * d);
            clear.setStrokeJoin(Paint.Join.ROUND);
            clear.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.CLEAR));
        }

        void set(int level, boolean charging) {
            if (level == this.level && charging == this.charging) return;
            this.level = level;
            this.charging = charging;
            invalidateSelf();
        }

        @Override public void draw(Canvas c) {
            float x = getBounds().left + (getBounds().width() - w) / 2f, y = getBounds().top + (getBounds().height() - h) / 2f;
            float s = line.getStrokeWidth() / 2;
            // the body: 24 x 14 dp, 3.5 dp corners; the terminal: 2 x 5 dp at its right
            r.set(x + d + s, y + d + s, x + 25 * d - s, y + 15 * d - s);
            c.drawRoundRect(r, 3.5f * d, 3.5f * d, line);
            c.drawLine(x + 27 * d - s, y + 6 * d, x + 27 * d - s, y + 10 * d, line);
            // the level: inside the outline with a 1.6 dp gap, at least a sliver while there is any charge
            float l = x + 4.2f * d, t = y + 4.2f * d, rr = x + 21.8f * d, b = y + 11.8f * d;
            float right = l + (rr - l) * Math.max(0, Math.min(100, level)) / 100f;
            if (level > 0) right = Math.max(right, l + 1.5f * d);
            fill.setColor(charging ? chargeColor : level <= 15 ? lowColor : textColor);
            if (!charging) {
                r.set(l, t, right, b);
                c.drawRoundRect(r, 1.5f * d, 1.5f * d, fill);
                return;
            }
            int saved = c.saveLayer(x, y, x + w, y + h, null);
            r.set(l, t, right, b);
            c.drawRoundRect(r, 1.5f * d, 1.5f * d, fill);
            // the bolt, centred on the body: knocked out of the bar, then drawn in the outline's color
            float cx = x + 13 * d, cy = y + 8 * d;
            bolt.reset();
            bolt.moveTo(cx + 1.2f * d, cy - 4.6f * d);
            bolt.lineTo(cx - 2.8f * d, cy + 0.7f * d);
            bolt.lineTo(cx - 0.2f * d, cy + 0.7f * d);
            bolt.lineTo(cx - 1.2f * d, cy + 4.6f * d);
            bolt.lineTo(cx + 2.8f * d, cy - 0.7f * d);
            bolt.lineTo(cx + 0.2f * d, cy - 0.7f * d);
            bolt.close();
            c.drawPath(bolt, clear);
            fill.setColor(textColor);
            c.drawPath(bolt, fill);
            c.restoreToCount(saved);
        }

        @Override public int getIntrinsicWidth() { return w; }
        @Override public int getIntrinsicHeight() { return h; }
        @Override public void setAlpha(int alpha) { line.setAlpha(alpha); fill.setAlpha(alpha); invalidateSelf(); }
        @Override public void setColorFilter(ColorFilter cf) { line.setColorFilter(cf); fill.setColorFilter(cf); invalidateSelf(); }
        @SuppressWarnings("deprecation")
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
}
