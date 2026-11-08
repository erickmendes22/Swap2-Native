package dev.nxnative.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

/**
 * The launcher's building blocks, in code like the rest of the launcher (no layouts, no AndroidX), in Swap2-Native's UI kit (assets/artwork/swap2-native/ui-kit:
 * its tokens in res/values/colors.xml, its icons, symbol, background and illustration as resources made by android/tools/swap2_ui_kit_android.py; themes.xml's
 * Theme.Banana, light or dark: Console revision 6, LauncherTheme). One small design system so every screen looks the same:
 * <ul>
 * <li>Type: page title 24 sp heavy, heading 18 sp bold, body 15 sp, small 13 sp, section label 12 sp caps; buttons 15 sp semibold, one line.</li>
 * <li>Shapes: cards 20 dp corners with a hairline edge; buttons and icon buttons 14 dp corners (a card's big action 16 dp). A focused control (a gamepad or a
 * keyboard moving the focus) gets a 3 dp ring in the theme's focus color (near-black / off-white); pressing darkens it with a ripple, without moving the layout.</li>
 * <li>Spacing: every page has the same gutter (20 dp, 16 dp on a narrow screen), the same header (Ui.header: 56 dp, 8 dp under the status bar); cards 18 dp inside,
 * 12 dp between cards, 24 dp before a section label.</li>
 * <li>Button and header icons are vector drawables (res/drawable/ic_*.xml) tinted from the palette, so they look the same on every phone; list rows keep their
 * emoji tiles.</li>
 * </ul>
 */
final class Ui {
    private Ui() {}

    enum Kind { PRIMARY, PREPARE, TONAL, SOFT, DANGER, QUIET }   // SOFT: an outlined button for use on a tinted surface

    static final int GAP = 12, SECTION_GAP = 24;
    /** Console revision 6's finish: rounder buttons (22 dp), pill-shaped big actions and round icon buttons (24 dp) */
    static final int BUTTON_RADIUS = 22, ACTION_RADIUS = 24;

    static int dp(Context c, float v) { return Math.round(v * c.getResources().getDisplayMetrics().density); }
    static int col(Context c, int res) { return c.getColor(res); }

    static GradientDrawable round(int fill, float radiusPx, int stroke, int strokePx) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(radiusPx);
        if (strokePx > 0) g.setStroke(strokePx, stroke);
        return g;
    }

    /**
     * A touch ripple over a shape (the shape is its mask), and the focus ring (3 dp, the theme's focus color) while the view has the focus. A shape filled
     * with the focus color itself (the primary action, the selected settings category) would hide that ring, so its ring also gets a 2 dp contour in the
     * background color just inside it (a two-tone indicator, visible on either side)
     */
    static Drawable ripple(Context c, GradientDrawable shape) {
        GradientDrawable mask = new GradientDrawable();   // an opaque copy of the shape: a transparent button (QUIET) still shows its ripple
        mask.setColor(Color.BLACK);
        mask.setCornerRadius(shape.getCornerRadius());
        int focusColor = col(c, R.color.bn_banana);
        GradientDrawable ring = new GradientDrawable();
        ring.setColor(Color.TRANSPARENT);
        ring.setCornerRadius(shape.getCornerRadius());
        ring.setStroke(dp(c, 3), focusColor);
        Drawable focused = ring;
        ColorStateList fill = shape.getColor();
        if (fill != null && (fill.getDefaultColor() | 0xFF000000) == (focusColor | 0xFF000000) && Color.alpha(fill.getDefaultColor()) > 0x80) {
            GradientDrawable inner = new GradientDrawable();
            inner.setColor(Color.TRANSPARENT);
            int in = dp(c, 3);
            inner.setCornerRadius(Math.max(0f, shape.getCornerRadius() - in));
            inner.setStroke(dp(c, 2), col(c, R.color.bn_bg));
            android.graphics.drawable.LayerDrawable two = new android.graphics.drawable.LayerDrawable(new Drawable[] {ring, inner});
            two.setLayerInset(1, in, in, in, in);
            focused = two;
        }
        android.graphics.drawable.StateListDrawable focus = new android.graphics.drawable.StateListDrawable();
        focus.addState(new int[] {android.R.attr.state_focused}, focused);
        focus.setEnterFadeDuration(120);   // the kit's focus motion
        focus.setExitFadeDuration(120);
        return new android.graphics.drawable.LayerDrawable(new Drawable[] {new RippleDrawable(ColorStateList.valueOf((col(c, R.color.bn_text) & 0x00FFFFFF) | 0x24000000), shape, mask), focus});
    }

    static Typeface face(int weight) { return Typeface.create(Typeface.SANS_SERIF, weight, false); }

    /** A vector icon (res/drawable/ic_*.xml) tinted with a palette color */
    static Drawable icon(Context c, int drawable, int colorRes) {
        Drawable d = c.getDrawable(drawable).mutate();
        d.setTint(col(c, colorRes));
        return d;
    }

    // ---- Text ----

    static TextView text(Context c, CharSequence s, float sp, int colorRes, int weight) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(col(c, colorRes));
        t.setTypeface(face(weight));
        t.setLineSpacing(0, 1.1f);
        return t;
    }

    static TextView title(Context c, CharSequence s) {
        TextView t = text(c, s, 24, R.color.bn_text, 800);
        t.setLetterSpacing(-0.01f);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        return t;
    }
    static TextView heading(Context c, CharSequence s) { return text(c, s, 18, R.color.bn_text, 700); }
    static TextView body(Context c, CharSequence s) { return text(c, s, 15, R.color.bn_text, 400); }
    static TextView small(Context c, CharSequence s) { return text(c, s, 13, R.color.bn_text_2, 400); }

    /** A rounded little label (the build tag, a step) */
    static TextView chip(Context c, CharSequence s) {
        TextView t = text(c, s, 12, R.color.bn_text_2, 600);
        t.setBackground(round(col(c, R.color.bn_tint), dp(c, 999), 0, 0));
        t.setPadding(dp(c, 10), dp(c, 5), dp(c, 10), dp(c, 5));
        return t;
    }

    /** A group's label above its card (the settings page, a sheet) */
    static TextView section(Context c, CharSequence s) {
        TextView t = text(c, s, 12, R.color.bn_text_2, 700);
        t.setAllCaps(true);
        t.setLetterSpacing(0.08f);
        t.setPadding(dp(c, 4), 0, 0, 0);
        t.setAccessibilityHeading(true);
        return t;
    }

    /** A short state: a colored dot and a word (Ready, Shaders needed, …) */
    static TextView status(Context c, CharSequence s, int colorRes) {
        TextView t = text(c, "", 13, colorRes, 600);
        status(t, s, colorRes);
        return t;
    }

    static void status(TextView t, CharSequence s, int colorRes) {
        t.setText("●  " + s);
        t.setTextColor(col(t.getContext(), colorRes));
    }

    /** A small warning chip ("! Pack from other tools") whose tap shows the whole sentence in a small dialog */
    static TextView warnChip(Activity a, CharSequence s, CharSequence title, CharSequence message) {
        TextView t = text(a, "!  " + s, 12, R.color.bn_text, 600);
        t.setBackground(ripple(a, round(col(a, R.color.bn_warn_tint), dp(a, 999), 0, 0)));
        t.setPadding(dp(a, 10), dp(a, 5), dp(a, 12), dp(a, 5));
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setContentDescription(s + ": tap for details");
        t.setOnClickListener(v -> new AlertDialog.Builder(a).setTitle(title).setMessage(message).setPositiveButton("OK", null).show());
        return t;
    }

    /** A game's tile: the first letter of its name on banana yellow, rounded */
    static TextView tile(Context c, String name, int sizeDp) {
        String n = name == null ? "" : name.trim();
        TextView t = text(c, n.isEmpty() ? "?" : n.substring(0, n.offsetByCodePoints(0, 1)).toUpperCase(java.util.Locale.ROOT), sizeDp * 0.4f, R.color.bn_on_banana, 800);
        t.setGravity(Gravity.CENTER);
        t.setIncludeFontPadding(false);
        t.setBackground(round(col(c, R.color.bn_banana), dp(c, 16), 0, 0));
        t.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        t.setLayoutParams(new LinearLayout.LayoutParams(dp(c, sizeDp), dp(c, sizeDp)));
        return t;
    }

    // ---- Containers ----

    /** A card: rounded, a hairline peel edge, vertical, 18 dp inside */
    static LinearLayout card(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(round(col(c, R.color.bn_card), dp(c, 20), col(c, R.color.bn_card_stroke), dp(c, 1)));
        int p = dp(c, 18);
        l.setPadding(p, p, p, p);
        return l;
    }

    /** A card for list rows (settings, the Readiness check): the rows reach close to its edges */
    static LinearLayout listCard(Context c) {
        LinearLayout l = card(c);
        l.setPadding(dp(c, 6), dp(c, 6), dp(c, 6), dp(c, 6));
        return l;
    }

    /** A card inside a card: the tint color, no edge */
    static LinearLayout inner(Context c, int fillRes) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(round(col(c, fillRes), dp(c, 16), 0, 0));
        int p = dp(c, 14);
        l.setPadding(p, p, p, p);
        return l;
    }

    static LinearLayout row(Context c) {
        LinearLayout r = new LinearLayout(c);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    static LinearLayout.LayoutParams fill() { return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT); }
    static LinearLayout.LayoutParams wrap() { return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT); }
    static LinearLayout.LayoutParams weight() { return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1); }

    /** Adds v to a vertical parent with a gap above it (none for the first child) */
    static <V extends View> V add(LinearLayout parent, V v, int gapDp) { return add(parent, v, gapDp, fill()); }
    static <V extends View> V add(LinearLayout parent, V v, int gapDp, LinearLayout.LayoutParams lp) {
        if (parent.getChildCount() > 0) lp.topMargin = dp(parent.getContext(), gapDp);
        parent.addView(v, lp);
        return v;
    }

    static View spacer(Context c) { View v = new View(c); v.setLayoutParams(new LinearLayout.LayoutParams(0, 1, 1)); return v; }

    /** A thin line between a sheet's groups */
    static View divider(Context c) {
        View v = new View(c);
        v.setBackgroundColor(col(c, R.color.bn_card_stroke));
        v.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1)));
        return v;
    }

    // ---- Pages ----

    /** Full-window artwork, including the cutout area. System navigation remains available by edge swipe. */
    @SuppressWarnings("deprecation")
    static void immersive(Activity a) {
        android.view.Window w = a.getWindow();
        w.setDecorFitsSystemWindows(false);
        android.view.WindowManager.LayoutParams attrs = w.getAttributes();
        attrs.layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        w.setAttributes(attrs);
        w.setStatusBarColor(Color.TRANSPARENT);
        w.setNavigationBarColor(Color.TRANSPARENT);
        w.setNavigationBarContrastEnforced(false);
        w.setStatusBarContrastEnforced(false);
        // PhoneWindow.getInsetsController() dereferences its decor on some Android builds.
        // immersive() is also called before setContentView(), so create that decor explicitly first.
        w.getDecorView();
        android.view.WindowInsetsController controller = w.getInsetsController();
        if (controller != null) {
            int bars = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            controller.setSystemBarsAppearance(lightBars(a) ? bars : 0, bars);   // dark bar icons over the launcher's light theme, light ones elsewhere
            controller.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
        }
    }

    /** Whether the activity's theme asks for dark system bar icons (the launcher's light theme, themes.xml windowLightStatusBar) */
    private static boolean lightBars(Activity a) {
        android.content.res.TypedArray t = a.getTheme().obtainStyledAttributes(new int[] {android.R.attr.windowLightStatusBar});
        try { return t.getBoolean(0, false); } finally { t.recycle(); }
    }

    /** The background fills the window; only interactive content is inset for cutouts and visible system UI. */
    static LinearLayout page(Activity a, FrameLayout frame, int maxWidthDp) {
        immersive(a);
        ScrollView scroll = new ScrollView(a) {
            @Override public void onWindowFocusChanged(boolean focus) {
                super.onWindowFocusChanged(focus);
                if (focus) immersive(a);
            }
        };
        scroll.setFillViewport(true);
        scroll.setClipToPadding(true);
        scroll.setVerticalScrollBarEnabled(false);
        LinearLayout content = new LinearLayout(a);
        content.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        frame.addView(scroll, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        scroll.setOnApplyWindowInsetsListener((v, in) -> {
            Insets i = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            int w = a.getWindowManager().getCurrentWindowMetrics().getBounds().width();
            int gutter = dp(a, a.getResources().getConfiguration().screenWidthDp < 360 ? 16 : 20);
            int side = Math.max(gutter, (w - i.left - i.right - dp(a, maxWidthDp)) / 2);
            boolean low = a.getResources().getConfiguration().screenHeightDp < 560;
            v.setPadding(side + i.left, i.top + dp(a, low ? 8 : 12), side + i.right, i.bottom + dp(a, low ? 10 : 24));
            return in;
        });
        frame.requestApplyInsets();
        return content;
    }

    /** A page's header, the same on every screen: 56 dp high; a leading view (the banana badge, or a back button), the title, and an optional trailing button */
    static LinearLayout header(Context c, View leading, CharSequence title, View trailing) {
        LinearLayout h = row(c);
        h.setMinimumHeight(dp(c, 56));
        if (leading != null) h.addView(leading);
        TextView t = title(c, title);
        t.setAccessibilityHeading(true);
        t.setPadding(dp(c, leading != null ? 14 : 4), 0, dp(c, 8), 0);
        h.addView(t, weight());
        if (trailing != null) h.addView(trailing);
        return h;
    }

    /** The back button of a page's header */
    static ImageView back(Context c, View.OnClickListener l) { return back(c, LauncherEffects.Cue.BACK, l); }

    /** A back button whose one cue is cue (a settings page closing back to the library: PANEL_CLOSE) */
    static ImageView back(Context c, LauncherEffects.Cue cue, View.OnClickListener l) {
        ImageView v = iconButton(c, R.drawable.ic_back, c.getString(R.string.s2_hint_back), Kind.TONAL, l);
        v.setOnClickListener(LauncherEffects.click(cue, l));
        return v;
    }

    // ---- Buttons ----

    private static void style(Context c, View b, Kind k, float radiusDp) {
        int fill, stroke = 0;
        switch (k) {
            case PRIMARY: fill = col(c, R.color.bn_banana); break;
            case PREPARE: fill = col(c, R.color.s2_prepare); break;
            case TONAL: fill = col(c, R.color.bn_tint); break;
            case SOFT: fill = Color.TRANSPARENT; stroke = col(c, R.color.bn_card_stroke); break;
            case DANGER: fill = col(c, R.color.bn_danger_tint); break;
            default: fill = Color.TRANSPARENT; break;
        }
        b.setBackground(ripple(c, round(fill, dp(c, radiusDp), stroke, stroke != 0 ? dp(c, 1.5f) : 0)));
    }

    private static int textColor(Kind k) {
        switch (k) {
            case PRIMARY: return R.color.bn_on_banana;
            case PREPARE: return R.color.s2_on_prepare;
            case DANGER: return R.color.bn_danger;
            case QUIET: return R.color.bn_accent;
            default: return R.color.bn_text;
        }
    }

    /**
     * A button: 48 dp high, 14 dp corners, one line (labels are kept short; the button grows to fit its label, and a half-width one ellipsizes rather than wraps).
     * PRIMARY banana yellow, TONAL the soft tint, SOFT an outline, DANGER red-orange on its tint, QUIET text only in the accent. Disabled ones fade
     */
    static Button button(Context c, CharSequence s, Kind k, View.OnClickListener l) {
        Button b = new Button(c) {
            @Override public void setEnabled(boolean on) { super.setEnabled(on); setAlpha(on ? 1f : 0.42f); }
        };
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(15);
        b.setTypeface(face(k == Kind.PRIMARY ? 700 : 600));
        b.setLetterSpacing(0f);
        b.setStateListAnimator(null);
        b.setMinWidth(dp(c, 64));
        b.setMinimumWidth(dp(c, 64));
        b.setMinHeight(dp(c, 48));
        b.setMinimumHeight(dp(c, 48));
        int h = dp(c, k == Kind.QUIET ? 12 : 18);
        b.setPadding(h, 0, h, 0);
        b.setSingleLine(true);
        b.setEllipsize(TextUtils.TruncateAt.END);
        b.setGravity(Gravity.CENTER);
        b.setIncludeFontPadding(false);
        b.setTextColor(col(c, textColor(k)));
        style(c, b, k, BUTTON_RADIUS);
        b.setSoundEffectsEnabled(false);
        b.setOnClickListener(LauncherEffects.click(l));
        return b;
    }

    /** A card's big action (Play, Prepare, Add game): an icon and a label centered, 56 dp high; setText changes the label, setIcon the icon */
    static final class Action extends LinearLayout {
        final ImageView icon;
        final TextView label;
        Kind kind;
        private int drawableId;

        Action(Context c, int drawable, CharSequence s, Kind k, View.OnClickListener l) {
            super(c);
            kind = k;
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER);
            setMinimumHeight(dp(c, 56));
            setPadding(dp(c, 20), 0, dp(c, 20), 0);
            style(c, this, k, ACTION_RADIUS);
            setClickable(true);
            setFocusable(true);
            icon = new ImageView(c);
            icon.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            addView(icon, new LinearLayout.LayoutParams(dp(c, 22), dp(c, 22)));
            label = text(c, s, 17, textColor(k), 700);
            label.setSingleLine(true);
            label.setIncludeFontPadding(false);
            LinearLayout.LayoutParams lp = wrap();
            lp.leftMargin = dp(c, 10);
            addView(label, lp);
            setIcon(drawable);
            setContentDescription(s);
            setSoundEffectsEnabled(false);
            setOnClickListener(LauncherEffects.click(l));
        }

        void setText(CharSequence s) { label.setText(s); setContentDescription(s); }

        void setKind(Kind value) {
            if (kind == value) return;
            kind = value;
            style(getContext(), this, value, ACTION_RADIUS);
            label.setTextColor(col(getContext(), textColor(value)));
            setIcon(drawableId);
        }

        void setIcon(int drawable) {
            drawableId = drawable;
            icon.setImageDrawable(drawable == 0 ? null : Ui.icon(getContext(), drawable, textColor(kind)));
            icon.setVisibility(drawable == 0 ? GONE : VISIBLE);
        }

        @Override public void setEnabled(boolean on) { super.setEnabled(on); setAlpha(on ? 1f : 0.42f); }
        @Override public CharSequence getAccessibilityClassName() { return Button.class.getName(); }
    }

    static Action action(Context c, int drawable, CharSequence s, Kind k, View.OnClickListener l) { return new Action(c, drawable, s, k, l); }

    /** A square icon button, 44 dp, 14 dp corners (a page's back and settings buttons, a card's ⋯) */
    static ImageView iconButton(Context c, int drawable, String description, Kind k, View.OnClickListener l) {
        ImageView v = new ImageView(c);
        v.setImageDrawable(icon(c, drawable, R.color.bn_text));
        v.setScaleType(ImageView.ScaleType.CENTER);
        style(c, v, k, ACTION_RADIUS);
        v.setContentDescription(description);
        v.setClickable(true);
        v.setFocusable(true);
        v.setSoundEffectsEnabled(false);
        v.setOnClickListener(LauncherEffects.click(l));
        v.setLayoutParams(new LinearLayout.LayoutParams(dp(c, 48), dp(c, 48)));
        return v;
    }

    /** A card's ⋯ (Manage): borderless */
    static ImageView more(Context c, String description, View.OnClickListener l) { return iconButton(c, R.drawable.ic_more, description, Kind.QUIET, l); }

    /** Two buttons side by side, each half the width */
    static LinearLayout pair(Context c, View a, View b) {
        LinearLayout r = row(c);
        r.addView(a, weight());
        if (b != null) {
            LinearLayout.LayoutParams lp = weight();
            lp.leftMargin = dp(c, 10);
            r.addView(b, lp);
        }
        return r;
    }

    /** Swap2-Native's compact mark, brand v6 (two angular arrows and the 2, res/drawable[-night]/s2_mark_v6.xml: near-black faces in the light theme, off-white in
     *  the dark one, small cyan / coral offset shadows), sizeDp high in its 192x112 box; a page header's brand */
    static ImageView badge(Context c, int sizeDp) {
        ImageView v = new ImageView(c);
        v.setImageResource(R.drawable.s2_mark_v6);
        v.setScaleType(ImageView.ScaleType.FIT_CENTER);
        v.setLayoutParams(new LinearLayout.LayoutParams(dp(c, sizeDp * 192f / 112f), dp(c, sizeDp)));
        v.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        return v;
    }

    /** The screen's background: the theme's neutral background (Console revision 6; the library adds its selected cover's soft impression, CoverGlow) */
    static ImageView background(Context c) {
        ImageView v = new ImageView(c);
        v.setBackgroundColor(col(c, R.color.bn_bg));
        v.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        return v;
    }

    static ProgressBar progress(Context c) {
        ProgressBar bar = new ProgressBar(c, null, android.R.attr.progressBarStyleHorizontal);
        bar.setProgressTintList(ColorStateList.valueOf(col(c, R.color.bn_banana_deep)));
        bar.setProgressBackgroundTintList(ColorStateList.valueOf(col(c, R.color.bn_card_stroke)));
        bar.setScaleY(1.6f);
        return bar;
    }

    // ---- List rows ----

    /** One row of a list card or a sheet: an emoji tile, a title over its current value, and a chevron (or a switch); the whole row is the touch target */
    static final class Setting {
        final LinearLayout view;
        final TextView value;
        Switch toggle;

        Setting(Context c, String emoji, String title, View.OnClickListener l) {
            view = row(c);
            boolean low = SettingsFrame.compact(c);   // a short window: 52 dp rows (still above the 48 dp touch target), so more options are in view
            view.setPadding(dp(c, 10), dp(c, low ? 5 : 8), dp(c, 12), dp(c, low ? 5 : 8));
            view.setMinimumHeight(dp(c, low ? 52 : 60));
            view.setBackground(ripple(c, round(Color.TRANSPARENT, dp(c, 14), 0, 0)));
            view.setSoundEffectsEnabled(false);
            view.setOnClickListener(LauncherEffects.click(l));
            TextView tile = text(c, emoji, 18, R.color.bn_text, 400);
            tile.setGravity(Gravity.CENTER);
            tile.setIncludeFontPadding(false);
            tile.setBackground(round(col(c, R.color.bn_tint), dp(c, 12), 0, 0));
            tile.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            view.addView(tile, new LinearLayout.LayoutParams(dp(c, 40), dp(c, 40)));
            LinearLayout col = new LinearLayout(c);
            col.setOrientation(LinearLayout.VERTICAL);
            col.setPadding(dp(c, 14), 0, dp(c, 8), 0);
            TextView t = text(c, title, 16, R.color.bn_text, 600);
            t.setSingleLine(true);
            t.setEllipsize(TextUtils.TruncateAt.END);
            col.addView(t);
            value = small(c, "");
            value.setMaxLines(2);
            value.setEllipsize(TextUtils.TruncateAt.END);
            value.setVisibility(View.GONE);   // shown by value(…) when there is one
            col.addView(value);
            view.addView(col, weight());
        }

        Setting(Context c, int drawable, String title, View.OnClickListener l) {
            this(c, "", title, l);
            ImageView tile = new ImageView(c);
            tile.setImageDrawable(icon(c, drawable, R.color.bn_banana));
            tile.setPadding(dp(c, 9), dp(c, 9), dp(c, 9), dp(c, 9));
            tile.setBackground(round(col(c, R.color.bn_tint), dp(c, 12), 0, 0));
            tile.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            view.removeViewAt(0);
            view.addView(tile, 0, new LinearLayout.LayoutParams(dp(c, 40), dp(c, 40)));
        }

        Setting chevron(Context c) {
            ImageView ch = new ImageView(c);
            ch.setImageDrawable(icon(c, R.drawable.ic_chevron, R.color.bn_text_2));
            ch.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            view.addView(ch, new LinearLayout.LayoutParams(dp(c, 20), dp(c, 20)));
            return this;
        }

        Setting toggle(Context c, boolean on, android.widget.CompoundButton.OnCheckedChangeListener l) {
            toggle = new Switch(c);
            switchColors(c, toggle);
            toggle.setContentDescription(((TextView) ((LinearLayout) view.getChildAt(1)).getChildAt(0)).getText());
            toggle.setChecked(on);
            toggle.setOnCheckedChangeListener(l);
            // One Confirm cue for a change the user made, after it is stored (so turning Interface sounds off is silent); never for a value set from code
            toggle.setSoundEffectsEnabled(false);
            toggle.setOnClickListener(v -> LauncherEffects.play(v.getContext(), LauncherEffects.Cue.CONFIRM));
            boolean other = false;   // a row with its own control besides the switch (a mod's remove ×): only the switch toggles, never a tap beside that control
            for (int i = 2; i < view.getChildCount(); i++) other |= view.getChildAt(i).isClickable();
            if (!other && !view.hasOnClickListeners()) {
                // The whole row is the switch: one touch, focus and TalkBack target (read as a switch with its state), so the switch itself takes none
                view.setOnClickListener(v -> {
                    toggle.setChecked(!toggle.isChecked());
                    LauncherEffects.play(v.getContext(), LauncherEffects.Cue.CONFIRM);
                });
                view.setFocusable(true);
                toggle.setClickable(false);
                toggle.setFocusable(false);
                toggle.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                view.setAccessibilityDelegate(new View.AccessibilityDelegate() {
                    @Override public void onInitializeAccessibilityNodeInfo(View host, android.view.accessibility.AccessibilityNodeInfo info) {
                        super.onInitializeAccessibilityNodeInfo(host, info);
                        info.setClassName(Switch.class.getName());
                        info.setCheckable(true);
                        info.setChecked(toggle.isChecked());
                    }
                });
            }
            view.addView(toggle);
            return this;
        }

        Setting value(CharSequence s) { value.setText(s); value.setVisibility(s == null || s.length() == 0 ? View.GONE : View.VISIBLE); return this; }

        /**
         * A game's option against the general settings (Console revision 6 "Per-game settings"): Custom with the value set here, or Inherit global with the
         * value it currently inherits. In a wide pane both sit at the row's end (the value over a Custom chip, or Inherit global over "Current: …"); in a
         * narrower one (decided from the pane's width, not the window's: the two-pane frame's rail takes about 270 dp) they are the row's value line, so the
         * title keeps its width. Before chevron()
         */
        Setting override(Context c, boolean custom, CharSequence effective) {
            String state = c.getString(custom ? R.string.s2_custom : R.string.s2_inherit);
            // The row's end column is up to 276 dp, the tile and paddings about 96 dp: from a 560 dp pane the title still keeps 180 dp or more
            if (SettingsFrame.paneDp(c) < 560) return value(state + " · " + effective);
            LinearLayout col = new LinearLayout(c);
            col.setOrientation(LinearLayout.VERTICAL);
            col.setGravity(Gravity.END);
            col.setPadding(dp(c, 8), 0, dp(c, 8), 0);
            TextView top = text(c, custom ? effective : state, 15, R.color.bn_text, 700);
            top.setSingleLine(true);
            top.setEllipsize(TextUtils.TruncateAt.END);
            top.setMaxWidth(dp(c, 260));
            col.addView(top, wrap());
            TextView under;
            if (custom) under = chip(c, state);
            else {
                under = small(c, c.getString(R.string.s2_inherit_current, effective));
                under.setSingleLine(true);
                under.setEllipsize(TextUtils.TruncateAt.END);
                under.setMaxWidth(dp(c, 260));
            }
            LinearLayout.LayoutParams ul = wrap();
            ul.topMargin = dp(c, custom ? 3 : 1);
            col.addView(under, ul);
            view.addView(col, wrap());
            return this;
        }
    }

    /**
     * A settings switch in neutral, theme-aware colors (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 4) rather than the theme's cyan accent: on, the
     * thumb in the theme's text color over a track of that color at 45 %; off, a muted thumb over the border-colored track; disabled, the off colors faded.
     * Like the Audio volume slider; light and dark follow from the palette (res/values, res/values-night)
     */
    static void switchColors(Context c, Switch s) {
        int text = col(c, R.color.bn_text), muted = col(c, R.color.bn_text_2), track = col(c, R.color.bn_card_stroke);
        int[][] states = {{-android.R.attr.state_enabled}, {android.R.attr.state_checked}, {}};
        s.setThumbTintList(new ColorStateList(states, new int[] {fade(muted, 0.5f), text, muted}));
        s.setTrackTintList(new ColorStateList(states, new int[] {fade(track, 0.5f), fade(text, 0.45f), track}));
    }

    private static int fade(int color, float alpha) { return Color.argb(Math.round(Color.alpha(color) * alpha), Color.red(color), Color.green(color), Color.blue(color)); }

    /** Console revision 6's softly raised panel for settings rows: 22 dp corners, the 1 dp light edge, about 2 dp of elevation */
    static LinearLayout panel(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(round(col(c, R.color.bn_card), dp(c, 22), col(c, R.color.s2_edge), dp(c, 1)));
        l.setElevation(dp(c, 2));
        int p = dp(c, 6);
        l.setPadding(p, p, p, p);
        return l;
    }

    // ---- Dialogs ----

    /** A dialog whose content scrolls (a short screen, the folded phone, landscape): every custom dialog view goes through here */
    static AlertDialog.Builder sheet(Activity a, CharSequence title, View content) {
        ScrollView sv = new ScrollView(a);
        sv.setFillViewport(true);
        sv.setClipToPadding(false);
        int p = dp(a, 20);
        content.setPadding(p, dp(a, 4), p, dp(a, 8));
        sv.addView(content);
        return new AlertDialog.Builder(a).setTitle(title).setView(sv);
    }

    /**
     * Asks before something is deleted or forgotten: what goes and what stays, in the message; the yes button in the danger color, Cancel the default.
     */
    static void confirmDanger(Activity a, String title, CharSequence message, String yes, Runnable r) {
        AlertDialog d = new AlertDialog.Builder(a).setTitle(title).setMessage(message)
                .setPositiveButton(yes, (x, w) -> r.run()).setNegativeButton("Cancel", null).create();
        d.setOnShowListener(x -> {
            Button b = d.getButton(AlertDialog.BUTTON_POSITIVE);
            if (b != null) b.setTextColor(col(a, R.color.bn_danger));
            Button n = d.getButton(AlertDialog.BUTTON_NEGATIVE);
            if (n != null) n.requestFocus();
        });
        d.show();
    }
}
