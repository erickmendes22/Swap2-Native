package dev.nxnative.android;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

/**
 * The settings pages' frame, Console revision 6 (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md "General settings" / "Per-game settings", console-v4/mockups/
 * settings-general-rich-v3.png and settings-game-rich-v3.png). From 600 dp of width: the page's header, then a softly inset category rail (each category an
 * original line icon and its name; the current one a dark rounded pill with pale text and tiny cyan / coral edges) beside the options pane. The rail is about
 * 22 % of the safe width (railDp: 156..184 dp on a short landscape phone, docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 4) and scrolls on its own only
 * when its entries need more height than the window has; the pane scrolls when its rows need it, and choosing a category swaps the pane alone. A short window
 * (compact) takes tighter gaps and paddings. Narrower: the header and the list of categories, then one
 * category's own page (its header's back returns to the list; MainActivity.onBackPressed too). Text is never shrunk to fit: everything scrolls instead.
 * Used by MainActivity (the general settings) and GameSettings (a game's own).
 */
final class SettingsFrame {
    private SettingsFrame() {}

    /** One category: its id (kept in the saved state), its icon and name, the sentence under its title, and what fills its pane */
    static final class Category {
        final String id, label, intro;
        final int icon;
        final Consumer<LinearLayout> fill;

        Category(String id, int icon, String label, String intro, Consumer<LinearLayout> fill) {
            this.id = id;
            this.icon = icon;
            this.label = label;
            this.intro = intro;
            this.fill = fill;
        }
    }

    /** A rail beside the options (a landscape phone, a tablet, an unfolded phone); below 600 dp the list-then-page form */
    static boolean twoPane(Activity a) { return a.getResources().getConfiguration().screenWidthDp >= 600; }

    /**
     * A short window (a landscape phone: under 560 dp of height): the settings pages' compact measures (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 4),
     * tighter gaps and paddings, the narrower rail, the capped theme tiles. Text sizes stay; everything scrolls instead
     */
    static boolean compact(android.content.Context c) { return c.getResources().getConfiguration().screenHeightDp < 560; }

    /** A gap between a pane's panels, in dp: as given, or about 60 % of it in the compact form (never under 4 dp) */
    static int gap(android.content.Context c, int dp) { return compact(c) ? Math.max(4, Math.round(dp * 0.6f)) : dp; }

    /**
     * The category rail's width in dp for a safe width (the window less its cutout / bar insets and the page's gutters) and the window's height: about 22 % of
     * that width, 156..184 dp on a short window (a landscape phone: the options keep most of the width) and 184..248 dp on a tall one (a tablet, an unfolded
     * phone); with a large font scale up to 212 dp on a short one, so the names wrap less (the rail scrolls when its entries need more height than it has)
     */
    static int railDp(int safeDp, int heightDp, float fontScale) {
        boolean low = heightDp < 560;
        int min = low ? 156 : 184, max = low ? (fontScale > 1.15f ? 212 : 184) : 248;
        return Math.max(min, Math.min(max, Math.round(safeDp * 0.22f)));
    }

    /**
     * About how wide the options pane is, in dp, from the window's width and the frame's own measures (build: the gutter, the rail of railDp, its margin, the
     * pane's padding; narrow: Ui.page's 800 dp column and gutter). Cutout insets are left out, so a row choosing its layout from this keeps a margin
     */
    static int paneDp(android.content.Context c) {
        android.content.res.Configuration conf = c.getResources().getConfiguration();
        int sw = conf.screenWidthDp;
        if (sw < 600) return Math.min(sw, 800) - 2 * (sw < 360 ? 16 : 20);
        int side = Math.max(20, (sw - 1200) / 2), safe = sw - 2 * side;
        return safe - railDp(safe, conf.screenHeightDp, conf.fontScale) - (compact(c) ? 14 : 20) - 8;
    }

    static Category find(List<Category> cats, String id) {
        for (Category c : cats) if (c.id.equals(id)) return c;
        return null;
    }

    /**
     * Builds the page into frame. top: the page's header (the list's, on a narrow window); current: the category shown (null on a narrow window: the list);
     * chosen: a category the user picked (the two-pane frame has already swapped its pane; on a narrow window the caller builds the page again);
     * back: the narrow category page's back (to the list); dock: the lower dock, or null. Returns the scroll view that holds the options, whose position the
     * caller keeps across a rebuild
     */
    static ScrollView build(Activity a, FrameLayout frame, View top, List<Category> cats, String current, Consumer<String> chosen, Runnable back, View dock) {
        if (!twoPane(a)) return narrow(a, frame, top, cats, find(cats, current == null ? "" : current), chosen, back);
        Category cur = current == null ? null : find(cats, current);
        if (cur == null) cur = cats.get(0);
        Ui.immersive(a);
        LinearLayout root = new LinearLayout(a) {
            @Override public void onWindowFocusChanged(boolean focus) {   // back from a dialog: the bars hidden again, as Ui.page's scroll does
                super.onWindowFocusChanged(focus);
                if (focus) Ui.immersive(a);
            }
        };
        root.setOrientation(LinearLayout.VERTICAL);
        frame.addView(root, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        boolean low = compact(a);
        android.content.res.Configuration conf = a.getResources().getConfiguration();
        ScrollView railScroll = new ScrollView(a);
        root.setOnApplyWindowInsetsListener((v, in) -> {   // Ui.page's gutter and cutout insets, without its page-sized scroll
            Insets i = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            android.graphics.Rect bounds = a.getWindowManager().getCurrentWindowMetrics().getBounds();
            int w = bounds.width();
            int side = Math.max(Ui.dp(a, 20), (w - i.left - i.right - Ui.dp(a, 1200)) / 2);
            v.setPadding(side + i.left, i.top + Ui.dp(a, low ? 6 : 12), side + i.right, i.bottom + Ui.dp(a, low ? 6 : 16));
            // The rail from the safe width actually left (and the height): a short landscape phone keeps most of its width for the options
            float density = a.getResources().getDisplayMetrics().density;
            int safeDp = Math.round((w - i.left - i.right - 2 * side) / density), heightDp = Math.round((bounds.height() - i.top - i.bottom) / density);
            ViewGroup.LayoutParams rl = railScroll.getLayoutParams();
            int railPx = Ui.dp(a, railDp(safeDp, Math.min(heightDp, conf.screenHeightDp), conf.fontScale));
            if (rl != null && rl.width != railPx) { rl.width = railPx; railScroll.setLayoutParams(rl); }
            return in;
        });
        root.addView(top, Ui.fill());
        LinearLayout body = Ui.row(a);
        body.setGravity(Gravity.TOP);
        body.setBaselineAligned(false);
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        bl.topMargin = Ui.dp(a, low ? 6 : 16);
        root.addView(body, bl);

        railScroll.setVerticalScrollBarEnabled(false);
        railScroll.setClipToPadding(false);
        LinearLayout rail = new LinearLayout(a);
        rail.setOrientation(LinearLayout.VERTICAL);
        rail.setBackground(Ui.round(Ui.col(a, R.color.s2_shelf), Ui.dp(a, low ? 20 : 24), Ui.col(a, R.color.s2_edge), Ui.dp(a, 1)));
        int rp = Ui.dp(a, low ? 6 : 10);
        rail.setPadding(rp, rp, rp, rp);
        railScroll.addView(rail, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        // First from the configuration (the insets listener sets it from the safe width before the first layout)
        int sw = conf.screenWidthDp, gutter = Math.max(20, (sw - 1200) / 2);
        body.addView(railScroll, new LinearLayout.LayoutParams(Ui.dp(a, railDp(sw - 2 * gutter, conf.screenHeightDp, conf.fontScale)), ViewGroup.LayoutParams.WRAP_CONTENT));

        ScrollView paneScroll = new ScrollView(a);
        paneScroll.setVerticalScrollBarEnabled(false);
        paneScroll.setClipToPadding(false);
        LinearLayout pane = new LinearLayout(a);
        pane.setOrientation(LinearLayout.VERTICAL);
        int pp = Ui.dp(a, 4);
        pane.setPadding(pp, 0, pp, Ui.dp(a, 12));   // room for the panels' shadows
        paneScroll.addView(pane, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams pl = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f);
        pl.leftMargin = Ui.dp(a, low ? 14 : 20);   // paneDp counts the same margin
        body.addView(paneScroll, pl);

        List<View> items = new ArrayList<>();
        Category[] shown = {cur};
        for (Category c : cats) {
            View item = railItem(a, c, v -> {
                if (shown[0] == c) return;   // the category already shown: no change, no cue
                LauncherEffects.play(a, LauncherEffects.Cue.FOCUS);   // a category is a selection
                shown[0] = c;
                for (int k = 0; k < items.size(); k++) style(a, items.get(k), cats.get(k) == c);
                pane.removeAllViews();
                fill(a, pane, c, true);
                paneScroll.scrollTo(0, 0);
                LauncherEffects.enter(pane, false);
                chosen.accept(c.id);
            });
            items.add(item);
            LinearLayout.LayoutParams il = Ui.fill();
            if (rail.getChildCount() > 0) il.topMargin = Ui.dp(a, low ? 2 : 4);
            rail.addView(item, il);
            style(a, item, c == cur);
        }
        fill(a, pane, cur, true);
        if (dock != null) {
            LinearLayout.LayoutParams dl = Ui.wrap();
            dl.gravity = Gravity.CENTER_HORIZONTAL;
            dl.topMargin = Ui.dp(a, 8);
            root.addView(dock, dl);
        }
        frame.requestApplyInsets();
        return paneScroll;
    }

    /** The narrow form: the list of categories under the page's header, or one category's page with its own header */
    private static ScrollView narrow(Activity a, FrameLayout frame, View top, List<Category> cats, Category cur, Consumer<String> chosen, Runnable back) {
        LinearLayout content = Ui.page(a, frame, 800);
        ScrollView scroll = (ScrollView) content.getParent();
        if (cur == null) {
            content.addView(top);
            LinearLayout list = Ui.add(content, Ui.panel(a), 16);
            for (Category c : cats) {
                Ui.Setting row = new Ui.Setting(a, c.icon, c.label, v -> chosen.accept(c.id)).value(c.intro).chevron(a);
                list.addView(row.view);
            }
            return scroll;
        }
        content.addView(Ui.header(a, Ui.back(a, v -> back.run()), cur.label, null));
        fill(a, content, cur, false);
        return scroll;
    }

    /** A category's pane: its title (on the two-pane form; the narrow page has it in its header) and sentence, then its panels */
    private static void fill(Activity a, LinearLayout pane, Category c, boolean title) {
        if (title) {   // a short window's title is smaller (the rail beside it already names the category)
            TextView t = Ui.text(a, c.label, compact(a) ? 22 : 26, R.color.bn_text, 800);
            t.setTypeface(Typeface.create(Typeface.SANS_SERIF, 800, true));
            t.setAccessibilityHeading(true);
            t.setSingleLine(true);
            t.setEllipsize(TextUtils.TruncateAt.END);
            pane.addView(t, Ui.fill());
        }
        if (c.intro != null && !c.intro.isEmpty()) Ui.add(pane, Ui.text(a, c.intro, 14, R.color.bn_text_2, 400), title ? 2 : 4);
        int first = pane.getChildCount();
        c.fill.accept(pane);
        if (!compact(a)) return;
        // A short window: the gaps between the category's panels, labels and notes tightened in one place (gap), for the general and the per-game settings alike
        int eight = Ui.dp(a, 8);
        for (int k = first; k < pane.getChildCount(); k++) {
            ViewGroup.LayoutParams lp = pane.getChildAt(k).getLayoutParams();
            if (!(lp instanceof ViewGroup.MarginLayoutParams)) continue;
            ViewGroup.MarginLayoutParams m = (ViewGroup.MarginLayoutParams) lp;
            if (m.topMargin < eight) continue;   // already small (a caption under its control)
            m.topMargin = Ui.dp(a, gap(a, Math.round(m.topMargin / a.getResources().getDisplayMetrics().density)));
        }
    }

    /**
     * A rail entry: 52 dp (48 dp in the compact form, its narrower rail: the name may take two lines rather than be cut), its line icon and name; the whole
     * entry is the touch and focus target, read as its name and whether it is selected
     */
    private static View railItem(Activity a, Category c, View.OnClickListener l) {
        boolean low = compact(a);
        LinearLayout item = Ui.row(a);
        item.setMinimumHeight(Ui.dp(a, low ? 48 : 52));
        item.setPadding(Ui.dp(a, low ? 12 : 16), Ui.dp(a, low ? 4 : 6), Ui.dp(a, low ? 10 : 14), Ui.dp(a, low ? 4 : 6));
        item.setClickable(true);
        item.setFocusable(true);
        item.setContentDescription(c.label);
        item.setSoundEffectsEnabled(false);
        item.setOnClickListener(l);   // its Focus cue is played by l, only when the category changes
        ImageView ic = new ImageView(a);
        ic.setScaleType(ImageView.ScaleType.FIT_CENTER);
        ic.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        item.addView(ic, new LinearLayout.LayoutParams(Ui.dp(a, low ? 22 : 24), Ui.dp(a, low ? 22 : 24)));
        TextView t = Ui.text(a, c.label, low ? 15 : 16, R.color.bn_text, 600);
        if (low) t.setMaxLines(2);
        else t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        t.setPadding(Ui.dp(a, low ? 10 : 14), 0, 0, 0);
        item.addView(t, Ui.weight());
        item.setTag(c.icon);
        return item;
    }

    /** The selected entry: the dark pill (the theme's text color) with pale icon and name and its tiny cyan / coral edges; the others on the rail itself */
    private static void style(Activity a, View v, boolean on) {
        LinearLayout item = (LinearLayout) v;
        item.setSelected(on);
        float r = Ui.dp(a, 22);
        int fg = Ui.col(a, on ? R.color.bn_bg : R.color.bn_text);
        ((ImageView) item.getChildAt(0)).setImageDrawable(Ui.icon(a, (Integer) item.getTag(), on ? R.color.bn_bg : R.color.bn_text));
        ((TextView) item.getChildAt(1)).setTextColor(fg);
        ((TextView) item.getChildAt(1)).setTypeface(Ui.face(on ? 700 : 500));
        if (!on) { item.setBackground(Ui.ripple(a, Ui.round(Color.TRANSPARENT, r, 0, 0))); return; }
        GradientDrawable cyan = Ui.round(Ui.col(a, R.color.s2_brand_cyan), r, 0, 0), coral = Ui.round(Ui.col(a, R.color.s2_brand_coral), r, 0, 0);
        Drawable pill = Ui.ripple(a, Ui.round(Ui.col(a, R.color.bn_text), r, 0, 0));
        LayerDrawable d = new LayerDrawable(new Drawable[] {cyan, coral, pill});
        int e = Ui.dp(a, 2);
        d.setLayerInset(0, 0, 0, e, e);   // the cyan edge shows at the left and top
        d.setLayerInset(1, e, e, 0, 0);   // the coral one at the right and bottom
        d.setLayerInset(2, e / 2 + 1, e / 2 + 1, e / 2 + 1, e / 2 + 1);
        item.setBackground(d);
    }
}
