package dev.nxnative.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * The launcher. Two pages in one activity (so every picker's result comes back here): Home, the short path to playing (pick your dump, prepare it, Play), and Settings
 * (the defaults of every game, GPU driver, folders, the Readiness check, the self-test, logs, the build), opened with the gear in Home's header; Back returns to Home.
 * <p>
 * Home: the All files access card while it is missing, a game being prepared (Ondevice: shown while there is a job), then the games, each a card with its state and
 * one big button: Play, or Prepare when its pack does not fit yet; ⋯ (or a long press) opens Manage (its folders, its own settings, saves, Prepare again, removal),
 * kept away from Play. With no game, a single card says what to do and has Add game. "Add game" takes a dump folder or .nup of any game this APK has a profile for
 * (Profile: one host per game), or a folder that holds several (all added, one summary: addAll): the best pack PackFind finds (the picked pack folder, the app's,
 * beside the game, Work/&lt;id&gt;/&lt;any&gt; or &lt;id&gt;-work/&lt;any&gt; up to three folders above it) is used when it fits or only needs the automatic shader update, else the app offers to
 * prepare one on the phone (or a card with Prepare, from a folder of games). A game without a profile in this APK is refused with a sentence (Profile.missing),
 * never started.
 * <p>
 * Home sits in a bounded root (homePage: its covers fitted to the safe window, its dock and hints pinned under them, the library part scrolling only when even
 * the smallest covers cannot fit); Settings sits in one ScrollView over the UI kit's background (Ui.background), so it scrolls on any screen (the folded phone's outer display, landscape, a split window), at a
 * readable width, centered on a wide window. The activity handles rotation itself (configChanges), so a size change builds the page again (onConfigurationChanged).
 */
public final class MainActivity extends Activity {
    private static final int PICK_GAME = 1, PICK_PACK = 2, PICK_DLL = 3, PICK_DRIVER = 4, PICK_NUP = 5;

    private final List<Game> games = new ArrayList<>();
    private LinearLayout gameBox;   // the library: the game cards and the selected game's bar (refresh)
    private LinearLayout libTop;    // the library's title, count and folder bar (above the preparation card)
    private View changeFolder, refreshButton;   // the header's library actions (hidden while the library is empty)
    private HeaderStatus headerStatus; // Home header's time and battery (its receiver is registered only while the activity is resumed)
    private String selected;        // the selected game (its gameDir): the bar under the cards shows it and plays it
    private final java.util.Map<String, Tile> tiles = new java.util.HashMap<>();
    private View accessCard;
    private View backdrop;   // the UI kit's background picture behind the screen (Ui.background)
    private Ui.Setting overlayRow, resRow, capRow, lsfgRow, gpuRow, fsrRow, fsrSharpRow, aspectRow, pipelineRow, timingRow, volumeRow;
    private boolean resumed, settingsPage;
    private Game settingsGame;
    private String settingsCat;   // the settings category showing (SettingsFrame; null: the first one, or the list on a narrow window)
    private android.widget.ScrollView pageScroll;
    private android.widget.HorizontalScrollView libraryScroll;
    private int homeScrollY, homeScrollX;
    private CoverGlow glow;      // the selected game's soft cover impression behind Home (CoverGlow)
    private BrandIntro intro;    // the opening, while it shows (BrandIntro)
    private void rememberLibrary() {
        if (!settingsPage && settingsGame == null) {
            if (pageScroll != null) homeScrollY = pageScroll.getScrollY();
            if (libraryScroll != null) homeScrollX = libraryScroll.getScrollX();
        }
    }
    void gameSettings(Game game) { gameSettings(game, null); }

    /** A game's own settings at one of its categories (GameSettings: null the first, or the list on a narrow window) */
    void gameSettings(Game game, String category) {
        rememberLibrary();
        settingsGame = game;
        settingsPage = false;
        settingsCat = category;
        Ondevice.pause(this);
        build();
    }
    /** A game's settings changed from outside its page (GameSettings' Add mod, after the picker): its page again, where it was, when it is the one showing */
    void gameSettingsChanged(Game game) {
        if (settingsGame == null || !settingsGame.gameDir.equals(game.gameDir) || pageScroll == null) return;
        int y = pageScroll.getScrollY();
        build();
        android.widget.ScrollView current = pageScroll;
        current.post(() -> current.scrollTo(0, y));
    }
    private File pendingGame;   // a game folder (or .nup) waiting for its pack folder
    private String pendingId;
    private File pendingPackPick;   // the pack folder the user just picked (remembered in Prefs once it is accepted)

    /** Settings › Theme: light or dark over the system's, before anything reads the resources (LauncherTheme) */
    @Override protected void attachBaseContext(android.content.Context base) {
        super.attachBaseContext(AppLanguage.wrap(base));
        LauncherTheme.apply(this);
    }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (saved != null) {
            settingsPage = saved.getBoolean("settings");
            settingsCat = saved.getString("settingsCat");
            selected = saved.getString("selected");
            homeScrollY = saved.getInt("homeY");
            homeScrollX = saved.getInt("homeX");
            String gamePath = saved.getString("settingsGame");
            for (Game g : Game.load(this)) if (g.gameDir.equals(gamePath)) settingsGame = g;
        }
        FrameLayout frame = new FrameLayout(this);
        backdrop = Ui.background(this);
        frame.addView(backdrop, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        glow = new CoverGlow(this);
        frame.addView(glow.view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.TOP));
        setContentView(frame);
        build();
        // The opening over the library built underneath (its scan goes on meanwhile): a plain cold launcher start only (BrandIntro.wanted)
        if (BrandIntro.wanted(this, saved)) intro = BrandIntro.show(this, frame, () -> { intro = null; focusSelected(); });
        if (saved == null) fromIntent(getIntent());
    }

    @Override protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        rememberLibrary();
        out.putBoolean("settings", settingsPage);
        out.putString("settingsCat", settingsCat);
        out.putString("selected", selected);
        out.putString("settingsGame", settingsGame == null ? null : settingsGame.gameDir);
        out.putInt("homeY", homeScrollY);
        out.putInt("homeX", homeScrollX);
    }

    /** Rotation, a window resize: the same page again */
    @Override public void onConfigurationChanged(Configuration c) {
        rememberLibrary();
        super.onConfigurationChanged(c);
        build();
        if (resumed) { onResumeViews(); if (!settingsPage && settingsGame == null) Ondevice.resume(this); }
    }

    /** Home ↔ Settings */
    private void page(boolean settings) {
        if (settingsPage == settings && settingsGame == null) return;
        rememberLibrary();
        settingsGame = null;
        settingsPage = settings;
        settingsCat = null;
        if (settings) Ondevice.pause(this);   // its card is on Home only: no updates while Settings shows
        build();
        if (resumed) { onResumeViews(); if (!settings) Ondevice.resume(this); }
    }

    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() {
        if (intro != null && intro.showing()) { intro.finish(); return; }   // Back skips the opening
        boolean settings = settingsPage || settingsGame != null;
        if (settings && settingsCat != null && !SettingsFrame.twoPane(this)) {   // a narrow window's category page: back to its list
            LauncherEffects.play(this, LauncherEffects.Cue.BACK);
            settingsCat = null;
            build();
        } else if (settings) {
            LauncherEffects.play(this, LauncherEffects.Cue.PANEL_CLOSE);
            page(false);
        } else super.onBackPressed();
    }

    /** (Re)builds the current page above the background (Ui.page: the same gutter, width and header spacing as every screen) */
    private void build() {
        FrameLayout frame = (FrameLayout) backdrop.getParent();
        for (int k = frame.getChildCount() - 1; k >= 0; k--) {   // the page goes; the background, the cover impression and the opening stay
            View v = frame.getChildAt(k);
            if (v != backdrop && v != glow.view && (intro == null || !intro.owns(v))) frame.removeViewAt(k);
        }
        if (headerStatus != null) { headerStatus.stop(); headerStatus = null; }   // the old header's clock goes with it (buildHome makes a new one)
        audioStateRow = null;   // Audio's state line goes with its pane, home included (refreshSettings stops updating it; the Audio pane makes a new one)
        boolean home = !settingsPage && settingsGame == null;
        glow.view.setVisibility(home ? View.VISIBLE : View.GONE);   // the library's only
        if (!home) glow.cancel();
        glow.view.getLayoutParams().height = dp(Math.round(getResources().getConfiguration().screenHeightDp * 0.62f));   // the upper background
        glow.view.requestLayout();
        if (home) {
            LinearLayout content = homePage(frame);   // the library column; the footer is pinned under it (homePage)
            if (intro != null) intro.raise();
            buildHome(content);
            android.widget.ScrollView current = pageScroll;
            current.post(() -> current.scrollTo(0, homeScrollY));
            LauncherEffects.enter(homeRoot, true);
            return;
        }
        // Settings, general or a game's (SettingsFrame: a rail and its pane on a wide window, a list then a page on a narrow one)
        accessCard = null;
        gameBox = null;
        overlayRow = resRow = capRow = lsfgRow = gpuRow = fsrRow = fsrSharpRow = aspectRow = pipelineRow = timingRow = volumeRow = null;
        java.util.function.Consumer<String> chosen = id -> {   // two panes: the pane is already swapped, its rows get their values; narrow: the category's page
            settingsCat = id;
            if (!SettingsFrame.twoPane(this)) build();
            else refreshSettings();
        };
        Runnable toList = () -> { settingsCat = null; build(); };
        if (settingsGame != null) {
            pageScroll = GameSettings.populate(this, settingsGame, frame, settingsCat, chosen, toList, () -> {
                int y = pageScroll.getScrollY();
                build();
                android.widget.ScrollView current = pageScroll;
                current.post(() -> current.scrollTo(0, y));
            }, () -> page(false), compact() ? null : dock(true));
        } else pageScroll = buildSettings(frame, chosen, toList);
        if (intro != null) intro.raise();
        if (pageScroll.getChildCount() > 0) LauncherEffects.enter(pageScroll.getChildAt(0), false);
    }

    private View homeRoot;            // Home's bounded root: the library column above, the footer pinned below it (homePage)
    private LinearLayout homeFooter;  // the dock, then the gamepad hints under it: never scrolled away
    private LinearLayout hintRow;     // the gamepad hints, centered under the dock; gone without a gamepad (hints)
    private boolean hintLibrary;      // what the hints describe: the library's covers, or the empty library's Choose folder
    private View homeSpacer;          // the column's leftover height on a tall window, between the action strip and the footer
    private int coverPx;              // the covers' side now (fitCovers), kept across a rebuild so the carousel does not jump
    private static final int COVER_MIN = 112, COVER_PAD = 6;   // dp: the smallest cover; the slot's room around the art for the focus frame and the 1.02x scale

    /**
     * Home's bounded root (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md sections 1 and 3): inside the safe window (system bars, the display cutout and the bottom
     * gesture handle) the library column above, and the footer pinned below it: the dock, then the gamepad hints. The column gives its covers whatever height the
     * header, the identity block and the action strip leave (LibraryColumn); only when even the smallest covers do not fit (a split window, the largest fonts)
     * does the column scroll, never the footer. Returns the column
     */
    private LinearLayout homePage(FrameLayout frame) {
        Ui.immersive(this);
        LinearLayout root = new LinearLayout(this) {
            @Override public void onWindowFocusChanged(boolean focus) {
                super.onWindowFocusChanged(focus);
                if (focus) Ui.immersive(MainActivity.this);   // back from a dialog, or after a swipe showed the bars
            }
        };
        root.setOrientation(LinearLayout.VERTICAL);
        android.widget.ScrollView scroll = new android.widget.ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setClipToPadding(false);
        LinearLayout column = new LibraryColumn();
        scroll.addView(column, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        homeFooter = new LinearLayout(this);
        homeFooter.setOrientation(LinearLayout.VERTICAL);
        homeFooter.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(homeFooter, Ui.fill());
        frame.addView(root, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.setOnApplyWindowInsetsListener((v, in) -> {
            android.graphics.Insets i = in.getInsets(android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.displayCutout());
            // The bottom gesture handle: the dock's labels and the hints stay above it (capped: some phones report a hidden three-button bar's whole height)
            int handle = Math.min(in.getInsets(android.view.WindowInsets.Type.mandatorySystemGestures()).bottom, dp(16));
            int w = getWindowManager().getCurrentWindowMetrics().getBounds().width();
            int gutter = dp(getResources().getConfiguration().screenWidthDp < 360 ? 16 : 20);
            int side = Math.max(gutter, (w - i.left - i.right - dp(1200)) / 2);
            boolean low = compact();
            v.setPadding(side + i.left, i.top + dp(low ? 0 : 8), side + i.right, Math.max(i.bottom, handle) + dp(low ? 4 : 16));
            return in;
        });
        frame.requestApplyInsets();
        pageScroll = scroll;
        homeRoot = root;
        return column;
    }

    /**
     * Home's library column: the header, the identity block, the carousel and its action strip, then the leftover (homeSpacer). Measured with the covers it has,
     * then, when the height it may use differs from what it needs, again with the covers grown or shrunk by the difference (within COVER_MIN and coverMax): the
     * covers are as large as the safe window allows, measured from the real rows (fonts, insets, the access card, the hints) rather than fixed reservations. The
     * scroll's first pass carries the viewport's height too, so a window too low for the smallest covers scrolls the column instead of clipping it
     */
    private final class LibraryColumn extends LinearLayout {
        LibraryColumn() { super(MainActivity.this); setOrientation(VERTICAL); }

        @Override protected void onMeasure(int wSpec, int hSpec) {
            int avail = MeasureSpec.getSize(hSpec), min = dp(COVER_MIN), max = coverMax(MeasureSpec.getSize(wSpec) - getPaddingLeft() - getPaddingRight());
            if (coverPx < min || coverPx > max) fitCovers(this, Math.max(min, Math.min(max, coverPx)));
            super.onMeasure(wSpec, hSpec);
            if (avail <= 0 || tiles.isEmpty()) return;
            int used = getPaddingTop() + getPaddingBottom();
            for (int k = 0; k < getChildCount(); k++) {
                View v = getChildAt(k);
                if (v == homeSpacer || v.getVisibility() == GONE) continue;
                LayoutParams lp = (LayoutParams) v.getLayoutParams();
                used += v.getMeasuredHeight() + lp.topMargin + lp.bottomMargin;
            }
            int want = Math.max(min, Math.min(max, coverPx + avail - used));
            if (want == coverPx) return;
            fitCovers(this, want);
            super.onMeasure(wSpec, hSpec);
        }
    }

    /** The covers' largest side: 240 dp on a low window, 260 on a tall one, and a share of the width so the next cover still shows */
    private int coverMax(int widthPx) {
        int cap = dp(compact() ? 240 : 260);
        if (widthPx <= 0) return cap;
        int share = Math.round((widthPx - 2 * dp(COVER_PAD)) * (narrow() ? 0.72f : 0.42f));
        return Math.max(dp(COVER_MIN), Math.min(cap, share));
    }

    /** Gives every cover the side size (its slot, art, caption and focus frame) and marks their measurements stale up to the column, which measures them again */
    private void fitCovers(View column, int size) {
        if (size == coverPx) return;
        coverPx = size;
        int pad = dp(COVER_PAD);
        View any = null;
        for (Tile tl : tiles.values()) {
            if (tl.card == null) continue;
            tl.card.getLayoutParams().width = size + 2 * pad;
            ViewGroup.LayoutParams al = tl.art.getLayoutParams();
            al.width = al.height = size;
            tl.caption.getLayoutParams().width = size;
            tl.frame.setArt(pad, size);
            tl.art.forceLayout();
            tl.caption.forceLayout();
            tl.card.forceLayout();
            any = tl.card;
        }
        for (android.view.ViewParent p = any == null ? null : any.getParent(); p instanceof View && p != column; p = p.getParent()) ((View) p).forceLayout();
    }

    /**
     * Home, Console revision 6's rich library (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md) in the order of docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 1:
     * the compact brand / status header (the v6 mark; the phone's time and battery, HeaderStatus, and a modest Refresh); the library's identity and the selected
     * game below it (refresh); the dominant row of square covers (CoverFrame marks the selected one, CardProgressBorder its preparation); the slim action strip
     * (status, one Options and the state's action: shelf); then the footer pinned under the column (homePage): the compact dock (Library, Files, Controls,
     * Settings, About) and, only with a gamepad, its hints centered under it. The empty library keeps its illustration and Choose folder. Behind it all, the
     * selected cover's soft impression (CoverGlow)
     */
    private void buildHome(LinearLayout content) {
        overlayRow = null;
        tiles.clear();
        boolean small = compact();
        // 1. The brand / status header, alone on its row: the mark on the left; the time, the battery and a modest Refresh (a 48 dp target) on the right.
        // 40 dp high on a low window (48 on a tall one)
        LinearLayout head = Ui.row(this);
        head.setMinimumHeight(dp(small ? 40 : 48));
        ImageView mark = Ui.badge(this, small ? 24 : 30);
        mark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        mark.setContentDescription(getString(R.string.s2_wordmark));
        head.addView(mark);
        head.addView(Ui.spacer(this));
        // The phone's own time and battery (the system bars are hidden: Ui.immersive), left out under 340 dp; the level as text from 380 dp (TalkBack reads it always)
        int width = getResources().getConfiguration().screenWidthDp;
        if (width >= 340) {
            headerStatus = new HeaderStatus(this, width >= 380);
            if (small) headerStatus.compact();
            LinearLayout.LayoutParams sl = Ui.wrap();
            sl.leftMargin = dp(12);
            head.addView(headerStatus.view, sl);
            if (resumed) headerStatus.start();
        }
        ImageView refresh = Ui.iconButton(this, R.drawable.s2_ic_refresh, getString(R.string.s2_refresh), Ui.Kind.QUIET, v -> rescan());
        modestIcon(refresh, R.drawable.s2_ic_refresh);
        refreshButton = refresh;
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(dp(48), dp(small ? 40 : 48));
        rp.leftMargin = dp(4);
        head.addView(refreshButton, rp);
        content.addView(head);
        if (small) {   // the 40 dp header: Refresh's target reaches 8 dp further down, over the identity block's empty right end (no other target there): 48 x 48
            head.addOnLayoutChangeListener((hv, l, t, r, b, ol, ot, or, ob) -> {
                if (refresh.getVisibility() != View.VISIBLE) { content.setTouchDelegate(null); return; }   // the empty library hides it
                android.graphics.Rect hit = new android.graphics.Rect();
                refresh.getHitRect(hit);
                hit.offset(head.getLeft(), head.getTop());
                hit.bottom += dp(8);
                content.setTouchDelegate(new android.view.TouchDelegate(hit, refresh));
            });
        }
        accessCard = accessCard();
        Ui.add(content, accessCard, 4);
        // 2. The library's identity and the selected game, under the header (refresh fills it)
        libTop = new LinearLayout(this);
        libTop.setOrientation(LinearLayout.VERTICAL);
        Ui.add(content, libTop, 0);
        Ondevice.attach(this, content, content.getChildCount());   // the preparing job's logic; its state shows in the game's card (prepSummary) and on PrepareActivity
        Ondevice.listen(this::prepSummary);
        fixGap(content, small ? 4 : 10);
        ((LinearLayout.LayoutParams) libTop.getLayoutParams()).topMargin = small ? 0 : dp(4);   // the header's 48 dp band is most of its gap
        // 3-4. The carousel and its action strip (refresh), then the column's leftover height on a tall window
        gameBox = new LinearLayout(this);
        gameBox.setOrientation(LinearLayout.VERTICAL);
        Ui.add(content, gameBox, small ? 4 : 12);
        homeSpacer = new View(this);
        content.addView(homeSpacer, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        // 5-6. The footer under the column (homePage): the dock, then the gamepad hints centered under it (hints)
        LinearLayout.LayoutParams dockLp = narrow() ? Ui.fill() : Ui.wrap();
        dockLp.gravity = Gravity.CENTER_HORIZONTAL;
        dockLp.topMargin = dp(small ? 4 : 12);
        homeFooter.addView(dock(false), dockLp);
        hintRow = Ui.row(this);
        hintRow.setGravity(Gravity.CENTER);
        hintRow.setVisibility(View.GONE);
        LinearLayout.LayoutParams hl = Ui.wrap();
        hl.gravity = Gravity.CENTER_HORIZONTAL;
        hl.topMargin = dp(small ? 2 : 10);
        homeFooter.addView(hintRow, hl);
        refresh();
    }

    /** A header icon kept modest: a 20 dp glyph in the secondary text color, centered in its 48 dp target (48 x 40 dp on a short window, so 10 dp above and below) */
    private void modestIcon(ImageView v, int drawable) {
        v.setImageDrawable(Ui.icon(this, drawable, R.color.bn_text_2));
        v.setScaleType(ImageView.ScaleType.FIT_CENTER);
        int side = dp(14), vertical = dp(compact() ? 10 : 14);
        v.setPadding(side, vertical, side, vertical);
    }

    /** A narrow window (a phone held upright, a split window): the action strip stacks its status over its buttons, the dock's items share the width */
    private boolean narrow() { return getResources().getConfiguration().screenWidthDp < 600; }

    private boolean compact() { return getResources().getConfiguration().screenHeightDp < 560; }

    private View dockControls;   // the dock's Controls: only while the selected game has a profile (its settings hold its touch profile)

    /**
     * The floating lower dock (Console revision 6): original line icons, the current section on a subtle plate with its underline, each item an existing function:
     * Library (back to the top, focus on the selected cover), Files (Add game: the folder or .nup picker), Controls (the selected game's settings, where its touch
     * profile is), Settings, About (Settings' About). Touch, keyboard and gamepad reach every item; none is a decorative pictogram. On a low window it is compact
     * (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 1): 48 dp items, the plate and underline kept, so the whole dock fits with the covers
     */
    private View dock(boolean settings) {
        boolean small = compact();
        LinearLayout d = Ui.row(this);
        d.setGravity(Gravity.CENTER);
        d.setBackground(Ui.round(Ui.col(this, R.color.s2_dock), dp(small ? 24 : 26), Ui.col(this, R.color.s2_edge), dp(1)));
        d.setElevation(dp(small ? 2 : 3));
        d.setPadding(dp(small ? 4 : 6), dp(small ? 0 : 4), dp(small ? 4 : 6), dp(small ? 0 : 4));
        dockItem(d, R.drawable.s2_ic_library, getString(R.string.s2_library), getString(R.string.s2_library), !settings,
                settings ? LauncherEffects.Cue.PANEL_CLOSE : LauncherEffects.Cue.CONFIRM, v -> { if (settings) page(false); else showLibrary(); });
        changeFolder = dockItem(d, R.drawable.s2_ic_folder, getString(R.string.s2_dock_files), getString(R.string.s2_dock_files_desc), false, LauncherEffects.Cue.CONFIRM, v -> addGame());
        dockControls = dockItem(d, R.drawable.s2_ic_gamepad, getString(R.string.s2_dock_controls), getString(R.string.s2_dock_controls), false, LauncherEffects.Cue.PANEL_OPEN,
                v -> { Tile tl = tiles.get(selected); if (tl != null && Profile.of(tl.game.titleId) != null) gameSettings(tl.game, GameSettings.CONTROLS); });
        dockItem(d, R.drawable.s2_ic_settings, getString(R.string.s2_settings), getString(R.string.s2_settings), settings, LauncherEffects.Cue.PANEL_OPEN, v -> page(true));
        dockItem(d, R.drawable.s2_ic_info, getString(R.string.s2_about), getString(R.string.s2_dock_about_desc), false, LauncherEffects.Cue.PANEL_OPEN, v -> about());
        updateDock();
        return d;
    }

    private View dockItem(LinearLayout dock, int icon, String label, String description, boolean current, LauncherEffects.Cue cue, View.OnClickListener l) {
        LinearLayout item = new LinearLayout(this);
        item.setOrientation(LinearLayout.VERTICAL);
        boolean small = compact();   // 48 dp items: a 24 dp icon plate, an 11 sp label, the underline
        item.setGravity(Gravity.CENTER_HORIZONTAL);
        item.setMinimumHeight(dp(small ? 48 : 56));
        item.setMinimumWidth(dp(narrow() ? 48 : small ? 76 : 84));
        item.setPadding(dp(8), dp(small ? 3 : 4), dp(8), dp(small ? 1 : 2));
        item.setBackground(Ui.ripple(this, Ui.round(android.graphics.Color.TRANSPARENT, dp(18), 0, 0)));
        item.setClickable(true);
        item.setFocusable(true);
        item.setSelected(current);
        item.setContentDescription(description);
        item.setSoundEffectsEnabled(false);
        item.setOnClickListener(LauncherEffects.click(cue, l));
        ImageView ic = new ImageView(this);
        ic.setImageDrawable(Ui.icon(this, icon, current ? R.color.bn_text : R.color.bn_text_2));
        ic.setScaleType(ImageView.ScaleType.CENTER);
        ic.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        if (current) ic.setBackground(Ui.round(Ui.col(this, R.color.bn_tint), dp(12), 0, 0));
        item.addView(ic, new LinearLayout.LayoutParams(dp(small ? 40 : 44), dp(small ? 24 : 30)));
        TextView t = Ui.text(this, label, small ? 11 : 12, current ? R.color.bn_text : R.color.bn_text_2, current ? 700 : 500);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setIncludeFontPadding(false);
        t.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams tl = Ui.wrap();
        tl.topMargin = dp(small ? 1 : 3);
        item.addView(t, tl);
        View line = new View(this);   // the selected underline (kept invisible elsewhere, so every item has the same height)
        line.setBackground(Ui.round(Ui.col(this, R.color.bn_banana), dp(1), 0, 0));
        line.setVisibility(current ? View.VISIBLE : View.INVISIBLE);
        LinearLayout.LayoutParams ll = new LinearLayout.LayoutParams(dp(20), dp(2));
        ll.topMargin = dp(small ? 2 : 3);
        item.addView(line, ll);
        dock.addView(item, narrow() ? new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1) : Ui.wrap());
        return item;
    }

    /** The dock's Library: the top of Home, the focus on the selected cover */
    private void showLibrary() {
        if (pageScroll != null) pageScroll.smoothScrollTo(0, 0);
        focusSelected();
    }

    private void focusSelected() {
        Tile tl = tiles.get(selected);
        if (tl != null && tl.card != null) tl.card.requestFocus();
    }

    /** The dock's About: Settings, at its About category */
    private void about() { openSettings("about"); }

    /** Settings at one of its categories (the dock's About, Interface's link to Audio) */
    private void openSettings(String category) {
        boolean wasHome = !settingsPage && settingsGame == null;
        rememberLibrary();
        settingsGame = null;
        settingsPage = true;
        settingsCat = category;
        if (wasHome) Ondevice.pause(this);
        build();
        if (resumed) onResumeViews();
    }

    /** The dock's Controls: shown only for a selected game with a profile, its name in the label TalkBack reads */
    private void updateDock() {
        if (dockControls == null) return;
        Tile tl = tiles.get(selected);
        boolean on = tl != null && Profile.of(tl.game.titleId) != null;
        dockControls.setVisibility(on ? View.VISIBLE : View.GONE);
        if (on) dockControls.setContentDescription(getString(R.string.s2_dock_controls_desc, tl.game.name));
    }

    /** Refresh: the library folder's games again (the ones listed stay as they are; new ones are added), or the list itself when no folder was chosen */
    private void rescan() {
        String f = libraryFolder();
        if (f != null && new File(f).isDirectory()) gamePicked(new File(f));
        else refresh();
    }

    /** The folder the games were last picked from (a folder holding several games: gamePicked), null when none was */
    private String libraryFolder() { return Prefs.open(this, "library").getString("folder", null); }

    /** The Ondevice card is added without a margin: give it the cards' gap */
    private void fixGap(LinearLayout col, int gapDp) {
        for (int k = 1; k < col.getChildCount(); k++) {
            View v = col.getChildAt(k);
            ViewGroup.LayoutParams p = v.getLayoutParams();
            if (p instanceof LinearLayout.LayoutParams && ((LinearLayout.LayoutParams) p).topMargin == 0) ((LinearLayout.LayoutParams) p).topMargin = dp(gapDp);
        }
    }

    /** All files access while it is missing; on a low window one row (the words, then Allow on the right), so the covers keep most of the height */
    private View accessCard() {
        LinearLayout c = Ui.card(this);
        c.setBackground(Ui.round(Ui.col(this, R.color.bn_warn_tint), dp(20), Ui.col(this, R.color.bn_banana_deep), dp(1)));
        if (compact()) {
            c.setOrientation(LinearLayout.HORIZONTAL);
            c.setGravity(Gravity.CENTER_VERTICAL);
            c.setPadding(dp(16), dp(6), dp(8), dp(6));
            LinearLayout words = new LinearLayout(this);
            words.setOrientation(LinearLayout.VERTICAL);
            words.addView(Ui.text(this, "Allow file access", 15, R.color.bn_text, 700));
            words.addView(Ui.small(this, "Needed to read your game dump."));
            c.addView(words, Ui.weight());
            LinearLayout.LayoutParams bl = Ui.wrap();
            bl.leftMargin = dp(12);
            c.addView(Ui.button(this, "Allow", Ui.Kind.PRIMARY, v -> openAccessSettings()), bl);
            return c;
        }
        c.addView(Ui.heading(this, "Allow file access"));
        Ui.add(c, Ui.body(this, "Needed to read your game dump."), 4);
        Ui.add(c, Ui.button(this, "Allow", Ui.Kind.PRIMARY, v -> openAccessSettings()), 14, Ui.wrap());
        return c;
    }

    // ---- Settings page ----

    /**
     * Settings, Console revision 6's general settings (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md, console-v4/mockups/settings-general-rich-v3.png) in
     * SettingsFrame: Interface (the theme's three live tiles, the opening, reduced motion, interface sounds and a link to their volume), Audio (interface sounds,
     * their volume, Follow Android's touch sounds, the effective state and Test sound), Controls (a connected gamepad, each game's touch layout), Performance (the defaults every game starts with: overlay, resolution, frame rate cap,
     * frame generation, FSR upscaling), GPU Drivers (the driver, the Readiness check, the graphics self-test), Storage (StorageUi) and About (this build, folders, the log). Every
     * change is stored at once in the existing preferences
     */
    private android.widget.ScrollView buildSettings(FrameLayout frame, java.util.function.Consumer<String> chosen, Runnable toList) {
        List<SettingsFrame.Category> cats = new ArrayList<>();
        cats.add(new SettingsFrame.Category("interface", R.drawable.s2_ic_display, getString(R.string.s2_interface), getString(R.string.s2_interface_intro), this::paneInterface));
        cats.add(new SettingsFrame.Category("audio", R.drawable.s2_ic_volume, getString(R.string.s2_audio), getString(R.string.s2_audio_intro), this::paneAudio));
        cats.add(new SettingsFrame.Category("controls", R.drawable.s2_ic_gamepad, getString(R.string.s2_dock_controls), getString(R.string.s2_controls_intro), this::paneControls));
        cats.add(new SettingsFrame.Category("performance", R.drawable.s2_ic_gauge, getString(R.string.s2_performance), getString(R.string.s2_performance_intro), this::panePerformance));
        cats.add(new SettingsFrame.Category("drivers", R.drawable.s2_ic_chip, getString(R.string.s2_gpu_drivers), getString(R.string.s2_drivers_intro), this::paneDrivers));
        cats.add(new SettingsFrame.Category("storage", R.drawable.s2_ic_folder, getString(R.string.s2_storage), getString(R.string.s2_storage_intro), p -> StorageUi.pane(this, p)));   // (StorageUi.java)
        cats.add(new SettingsFrame.Category("about", R.drawable.s2_ic_info, getString(R.string.s2_about), getString(R.string.s2_about_intro), this::paneAbout));
        View top = Ui.header(this, Ui.back(this, LauncherEffects.Cue.PANEL_CLOSE, v -> page(false)), getString(R.string.s2_settings), Ui.badge(this, 32));
        android.widget.ScrollView s = SettingsFrame.build(this, frame, top, cats, settingsCat, chosen, toList, compact() ? null : dock(true));
        refreshSettings();
        return s;
    }

    /** Interface: the theme card (Light, Dark, Follow the system: live miniatures, ThemePreview), then the opening, reduced motion and interface sounds */
    private void paneInterface(LinearLayout p) {
        boolean low = SettingsFrame.compact(this);   // a short window: tighter card (its tiles capped, ThemePreview) so the rows below stay in view
        LinearLayout theme = Ui.add(p, Ui.panel(this), 16);   // the pane's gaps: SettingsFrame.fill tightens them on a short window
        if (low) theme.setPadding(dp(14), dp(10), dp(14), dp(10));
        else theme.setPadding(dp(18), dp(14), dp(18), dp(16));
        theme.addView(Ui.heading(this, getString(R.string.s2_theme)));
        LinearLayout row = Ui.row(this);
        row.setGravity(Gravity.TOP);
        String cur = LauncherTheme.mode(this);
        String[] modes = {LauncherTheme.LIGHT, LauncherTheme.DARK, LauncherTheme.SYSTEM};
        int[] names = {R.string.s2_theme_light, R.string.s2_theme_dark, R.string.s2_theme_follow};
        List<ThemePreview> previews = new ArrayList<>();
        List<Game> shown = new ArrayList<>();   // the library's first covers, real ones only
        for (Game g : games.isEmpty() ? Game.load(this) : games) if (shown.size() < 4) shown.add(g);
        android.graphics.Bitmap[] covers = new android.graphics.Bitmap[shown.size()];   // each decoded once for the three tiles (the library's own when it has it)
        for (int i = 0; i < covers.length; i++) {
            int at = i;
            covers[i] = coverOf(shown.get(i), x -> { for (ThemePreview t : previews) t.cover(at, x); });
        }
        for (int k = 0; k < modes.length; k++) {
            String m = modes[k], label = getString(names[k]);
            LinearLayout col = new LinearLayout(this);
            col.setOrientation(LinearLayout.VERTICAL);
            col.setGravity(Gravity.CENTER_HORIZONTAL);
            ThemePreview tp = new ThemePreview(this, m);
            tp.setSelected(m.equals(cur));
            tp.setContentDescription(getString(R.string.s2_theme_tile, label));
            for (int i = 0; i < covers.length; i++) if (covers[i] != null) tp.cover(i, covers[i]);
            tp.setOnClickListener(v -> {
                if (m.equals(LauncherTheme.mode(this))) return;   // the theme already chosen: no change, no cue
                LauncherEffects.play(this, LauncherEffects.Cue.CONFIRM);
                for (ThemePreview t : previews) t.setSelected(t == tp);
                LauncherTheme.mode(this, m);   // the launcher is drawn again in it, on this page (saved state)
            });
            previews.add(tp);
            col.addView(tp, Ui.fill());
            TextView t = Ui.text(this, label, 15, R.color.bn_text, m.equals(cur) ? 700 : 500);
            t.setGravity(Gravity.CENTER);
            t.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            Ui.add(col, t, low ? 2 : 6, Ui.wrap());
            LinearLayout.LayoutParams cl = Ui.weight();
            if (k > 0) cl.leftMargin = dp(low ? 10 : 12);
            row.addView(col, cl);
        }
        Ui.add(theme, row, low ? 6 : 12);
        LinearLayout rows = Ui.add(p, Ui.panel(this), 12);
        rows.addView(new Ui.Setting(this, R.drawable.s2_ic_settings, getString(R.string.s2_language), v -> AppLanguage.pick(this))
                .value(AppLanguage.selectedLabel(this)).chevron(this).view);
        Ui.add(p, Ui.small(this, getString(R.string.s2_language_note)), 6);
        rows.addView(new Ui.Setting(this, R.drawable.s2_ic_play, getString(R.string.s2_opening), null)
                .value(getString(R.string.s2_opening_note)).toggle(this, LauncherTheme.opening(this), (b, on) -> LauncherTheme.opening(this, on)).view);
        rows.addView(new Ui.Setting(this, R.drawable.s2_ic_display, getString(R.string.s2_reduced_motion), null)
                .value(getString(R.string.s2_reduced_note)).toggle(this, LauncherEffects.reduced(this),
                    (b, on) -> LauncherEffects.preference(this, "reduced_motion", on)).view);
        rows.addView(soundsRow());
        volumeRow = new Ui.Setting(this, R.drawable.s2_ic_volume, getString(R.string.s2_volume), v -> openSettings("audio")).chevron(this);
        rows.addView(volumeRow.view);
        Ui.add(p, Ui.small(this, getString(R.string.s2_saved_auto)), 10);
    }

    /** Interface sounds on or off (Interface and Audio show the same switch) */
    private View soundsRow() {
        return new Ui.Setting(this, R.drawable.s2_ic_volume, getString(R.string.s2_sounds), null)
                .value(getString(R.string.s2_sounds_note)).toggle(this, LauncherEffects.sounds(this),
                    (b, on) -> { LauncherEffects.preference(this, "sounds", on); refreshSettings(); }).view;   // the volume row's and Audio's state follow
    }

    private Ui.Setting audioStateRow;   // Audio's effective state line (LauncherEffects.state), while that pane shows
    private final Runnable audioStateTick = this::refreshAudioState;

    /** Audio's state line from LauncherEffects.state(); while the samples load it looks again shortly (they load in well under a second, or fail) */
    private void refreshAudioState() {
        if (audioStateRow == null) return;
        LauncherEffects.State s = LauncherEffects.state(this);
        audioStateRow.value(s.describe(this));
        audioStateRow.view.removeCallbacks(audioStateTick);
        if (s == LauncherEffects.State.LOADING) audioStateRow.view.postDelayed(audioStateTick, 300);
    }

    /**
     * Audio: interface sounds and their volume (0..100 %, a release plays the Confirm cue at the new level), Follow Android's touch sounds (off by default), then
     * the effective state (LauncherEffects.state: why the cues are silent, or that they play and at what media volume) with Test sound; game sound and the
     * device's volumes are never changed here
     */
    private void paneAudio(LinearLayout p) {
        LinearLayout box = Ui.add(p, Ui.panel(this), 16);
        box.addView(soundsRow());
        LinearLayout vol = new LinearLayout(this);
        vol.setOrientation(LinearLayout.VERTICAL);
        vol.setPadding(dp(10), dp(8), dp(12), dp(8));
        LinearLayout head = Ui.row(this);
        ImageView ic = new ImageView(this);
        ic.setImageDrawable(Ui.icon(this, R.drawable.s2_ic_volume, R.color.bn_banana));
        ic.setPadding(dp(9), dp(9), dp(9), dp(9));
        ic.setBackground(Ui.round(Ui.col(this, R.color.bn_tint), dp(12), 0, 0));
        ic.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        head.addView(ic, new LinearLayout.LayoutParams(dp(40), dp(40)));
        TextView title = Ui.text(this, getString(R.string.s2_volume), 16, R.color.bn_text, 600);
        title.setPadding(dp(14), 0, dp(8), 0);
        title.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        head.addView(title, Ui.weight());
        TextView pct = Ui.text(this, getString(R.string.s2_volume_value, LauncherEffects.volume(this)), 15, R.color.bn_text, 700);
        pct.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        head.addView(pct);
        vol.addView(head);
        android.widget.SeekBar bar = new android.widget.SeekBar(this);
        bar.setMax(100);
        bar.setProgress(LauncherEffects.volume(this));
        bar.setContentDescription(getString(R.string.s2_volume));
        bar.setStateDescription(getString(R.string.s2_volume_value, LauncherEffects.volume(this)));
        bar.setProgressTintList(android.content.res.ColorStateList.valueOf(Ui.col(this, R.color.bn_text)));
        bar.setThumbTintList(android.content.res.ColorStateList.valueOf(Ui.col(this, R.color.bn_text)));
        bar.setProgressBackgroundTintList(android.content.res.ColorStateList.valueOf(Ui.col(this, R.color.bn_card_stroke)));
        bar.setMinHeight(dp(48));
        bar.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener() {
            private boolean dragging;
            @Override public void onProgressChanged(android.widget.SeekBar sb, int v, boolean user) {
                if (!user) return;
                boolean wasZero = LauncherEffects.volume(MainActivity.this) == 0;
                LauncherEffects.volume(MainActivity.this, v);
                String text = getString(R.string.s2_volume_value, v);
                pct.setText(text);
                sb.setStateDescription(text);
                if (wasZero != (v == 0)) refreshAudioState();   // to or from "interface volume at 0 %"
                if (!dragging) LauncherEffects.play(MainActivity.this, LauncherEffects.Cue.FOCUS);   // a key step: the level heard, throttled
            }
            @Override public void onStartTrackingTouch(android.widget.SeekBar sb) { dragging = true; }
            @Override public void onStopTrackingTouch(android.widget.SeekBar sb) {
                dragging = false;
                LauncherEffects.play(MainActivity.this, LauncherEffects.Cue.CONFIRM);   // the new level, once
            }
        });
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        bl.topMargin = dp(4);
        vol.addView(bar, bl);
        box.addView(vol);
        box.addView(new Ui.Setting(this, R.drawable.s2_ic_settings, getString(R.string.s2_follow_touch), null)
                .value(getString(R.string.s2_follow_touch_note)).toggle(this, LauncherEffects.followTouch(this),
                    (b, on) -> { LauncherEffects.followTouch(this, on); refreshSettings(); }).view);
        // The effective state, then Test sound: the line says why the cues are silent (or that they play, at what media volume); the test's result replaces it
        LinearLayout state = Ui.add(p, Ui.panel(this), 12);
        audioStateRow = new Ui.Setting(this, R.drawable.s2_ic_info, getString(R.string.s2_audio_state), null);
        audioStateRow.view.setClickable(false);
        audioStateRow.value.setMaxLines(3);
        audioStateRow.value.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);   // a test's result is read out
        Button test = Ui.button(this, getString(R.string.s2_sound_test), Ui.Kind.TONAL, null);
        test.setOnClickListener(v -> {   // its own cue is the test itself (no extra Confirm)
            LauncherEffects.State r = LauncherEffects.test(this);
            audioStateRow.view.removeCallbacks(audioStateTick);
            int text = r == LauncherEffects.State.BLUETOOTH ? R.string.s2_audio_state_played_bluetooth : r.plays ? R.string.s2_audio_state_played : r.text;
            audioStateRow.value(getString(text, LauncherEffects.mediaPercent(this)));
        });
        audioStateRow.view.addView(test, Ui.wrap());
        state.addView(audioStateRow.view);
        refreshAudioState();
        Ui.add(p, Ui.small(this, getString(R.string.s2_audio_note)), 10);
    }

    /** Controls: a connected gamepad (the device's own name), then each game's touch layout, which lives in that game's own settings */
    private void paneControls(LinearLayout p) {
        LinearLayout box = Ui.add(p, Ui.panel(this), 16);
        String pad = gamepadName();
        Ui.Setting gp = new Ui.Setting(this, R.drawable.s2_ic_gamepad, getString(R.string.s2_gamepad), null)
                .value(pad == null ? getString(R.string.s2_gamepad_none) : getString(R.string.s2_gamepad_connected, pad));
        gp.view.setClickable(false);
        box.addView(gp.view);
        Ui.add(p, Ui.section(this, getString(R.string.s2_touch_controls)), 24);
        LinearLayout list = Ui.add(p, Ui.panel(this), 8);
        for (Game g : Game.load(this)) {
            if (Profile.of(g.titleId) == null) continue;
            String choice = Prefs.open(this, "touch_controls").getString("profile@" + TouchProfile.gameKey(g.titleId), TouchProfile.AUTO);
            list.addView(new Ui.Setting(this, R.drawable.s2_ic_gamepad, g.name, v -> gameSettings(g, GameSettings.CONTROLS))
                    .value(getString(TouchControls.profileLabel(choice))).chevron(this).view);
        }
        if (list.getChildCount() == 0) {
            Ui.Setting none = new Ui.Setting(this, R.drawable.s2_ic_gamepad, getString(R.string.s2_touch_no_games), null);
            none.view.setClickable(false);
            list.addView(none.view);
        }
        Ui.add(p, Ui.small(this, getString(R.string.s2_touch_per_game)), 8);
    }

    /** The first real gamepad's name, null when none is connected */
    private static String gamepadName() {
        for (int id : android.view.InputDevice.getDeviceIds()) {
            android.view.InputDevice d = android.view.InputDevice.getDevice(id);
            if (d != null && !d.isVirtual() && (d.getSources() & android.view.InputDevice.SOURCE_GAMEPAD) == android.view.InputDevice.SOURCE_GAMEPAD) return d.getName();
        }
        return null;
    }

    /** Performance: the defaults every game starts with (a game's own settings override them) */
    private void panePerformance(LinearLayout p) {
        LinearLayout play = Ui.add(p, Ui.panel(this), 16);
        overlayRow = new Ui.Setting(this, R.drawable.s2_ic_display, this.getString(R.string.s2_overlay), v -> overlayItems())
                .toggle(this, Prefs.overlay(this), (b, on) -> { Prefs.overlay(this, on); refreshSettings(); });
        play.addView(overlayRow.view);
        resRow = new Ui.Setting(this, R.drawable.s2_ic_display, this.getString(R.string.s2_resolution), v -> gameRes()).chevron(this);
        play.addView(resRow.view);
        if (!Profile.anyResolution()) resRow.view.setVisibility(View.GONE);   // no game of this APK has a window_fn or graphics_scale lever: the default would do nothing
        capRow = new Ui.Setting(this, R.drawable.s2_ic_gauge, this.getString(R.string.s2_frame_cap), v -> fpsCap()).chevron(this);
        play.addView(capRow.view);
        lsfgRow = new Ui.Setting(this, R.drawable.s2_ic_sun, this.getString(R.string.s2_frame_generation), v -> frameGen()).chevron(this);
        play.addView(lsfgRow.view);
        Ui.add(p, Ui.section(this, getString(R.string.s2_fsr_head)), 24);
        LinearLayout up = Ui.add(p, Ui.panel(this), 8);
        fsrRow = new Ui.Setting(this, R.drawable.s2_ic_image, "Filtro da tela (não reduz render)", v -> GraphicsOptions.choice(this, null, "present_filter", this::refreshSettings)).chevron(this);
        up.addView(fsrRow.view);
        fsrSharpRow = new Ui.Setting(this, R.drawable.s2_ic_image, getString(R.string.s2_fsr_sharpness), v -> GraphicsOptions.choice(this, null, "fsr_sharp", this::refreshSettings)).chevron(this);
        up.addView(fsrSharpRow.view);
        aspectRow = new Ui.Setting(this, R.drawable.s2_ic_display, "Proporção da tela", v -> GraphicsOptions.choice(this, null, "picture_stretch", this::refreshSettings)).chevron(this);
        up.addView(aspectRow.view);
        pipelineRow = new Ui.Setting(this, R.drawable.s2_ic_gauge, "Pipelines em segundo plano", v -> GraphicsOptions.choice(this, null, "bg_pipelines", this::refreshSettings)).chevron(this);
        up.addView(pipelineRow.view);
        timingRow = new Ui.Setting(this, R.drawable.s2_ic_gauge, "Medição de GPU", v -> GraphicsOptions.choice(this, null, "gpu_timestamps", this::refreshSettings)).chevron(this);
        // GPU timing is diagnostic, not a release graphics-quality setting;
        // leave it to the explicit env.txt debugging interface.
        Ui.add(p, Ui.small(this, "Filtro e nitidez também podem ser alterados durante o jogo. Proporção, pipelines e timestamps exigem reiniciar o jogo."), 8);
        Ui.add(p, Ui.small(this, getString(R.string.s2_defaults_hint)), 8);
    }

    /** FSR's sharpness for the next starts (the in-game panel's choice, Fsr.SHARPS) */
    private void fsrSharp() {
        String[] labels = new String[Fsr.SHARPS.length];
        int checked = 0;
        float cur = Fsr.sharp(this);
        for (int k = 0; k < labels.length; k++) {
            labels[k] = getString(Fsr.sharpName(Fsr.SHARPS[k]));
            if (Math.abs(Fsr.SHARPS[k] - cur) < 1e-3f) checked = k;
        }
        new AlertDialog.Builder(this).setTitle(R.string.s2_fsr_sharpness).setSingleChoiceItems(labels, checked, (d, w) -> {
            Prefs.of(this).edit().putFloat("fsr_sharp", Fsr.SHARPS[w]).commit();
            refreshSettings();
            d.dismiss();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** GPU Drivers: the default driver (a game's own pick overrides it), the Readiness check and the graphics self-test */
    private void paneDrivers(LinearLayout p) {
        LinearLayout sys = Ui.add(p, Ui.panel(this), 16);
        gpuRow = new Ui.Setting(this, R.drawable.s2_ic_chip, this.getString(R.string.s2_driver), v -> GpuDriver.dialog(this, PICK_DRIVER)).chevron(this);   // custom GPU drivers (GpuDriver.java)
        sys.addView(gpuRow.view);
        sys.addView(new Ui.Setting(this, R.drawable.s2_ic_check, this.getString(R.string.s2_readiness), v -> startActivityForResult(new Intent(this, ReadinessActivity.class), ReadinessActivity.REQUEST))
                .value(getString(R.string.s2_readiness_note)).chevron(this).view);   // (ReadinessActivity.java)
        sys.addView(new Ui.Setting(this, R.drawable.s2_ic_info, this.getString(R.string.s2_graphics_test), v -> startActivity(new Intent(this, SelftestActivity.class)))
                .value(getString(R.string.s2_graphics_test_note)).chevron(this).view);
        Ui.add(p, Ui.small(this, getString(R.string.s2_drivers_note)), 8);
    }

    /** About: the mark and this build (also the first line of every log), the title IDs and credits, the folders and the newest log */
    private void paneAbout(LinearLayout p) {
        LinearLayout about = Ui.add(p, Ui.panel(this), 16);
        about.setPadding(dp(18), dp(16), dp(18), dp(16));
        LinearLayout brand = Ui.row(this);
        brand.addView(Ui.badge(this, 36));
        TextView word = Ui.text(this, getString(R.string.s2_wordmark), 20, R.color.bn_text, 600);
        word.setPadding(dp(14), 0, 0, 0);
        brand.addView(word, Ui.weight());
        about.addView(brand);
        // The About card identifies a RELEASE by version, not by the CI
        // checkout's temporary +dirty suffix. Full diagnostics remain in logs.
        TextView tag = Ui.chip(this, getString(R.string.s2_about_version, BuildConfig.VERSION_NAME));
        tag.setTextIsSelectable(true);
        Ui.add(about, tag, 12, Ui.wrap());
        String revision = BuildConfig.NX_COMMIT;
        if (revision.length() > 10 && !"unknown".equals(revision))
            revision = revision.substring(0, 10);
        TextView revisionLine = Ui.small(this,
                getString(R.string.s2_about_revision, revision) + "\n" +
                getString(R.string.s2_about_build_date, BuildConfig.NX_BUILD_TIME));
        revisionLine.setTextIsSelectable(true);
        Ui.add(about, revisionLine, 8);
        StringBuilder ids = new StringBuilder();
        for (Profile pr : Profile.all()) ids.append(ids.length() == 0 ? "" : ", ").append(pr.titleId);
        TextView t = Ui.small(this, getString(R.string.s2_about_ids, ids.toString()) + "\n" + getString(R.string.s2_about_credits) + (BuildConfig.NX_LSFG ? "" : " " + getString(R.string.s2_about_no_lsfg)));
        t.setTextIsSelectable(true);
        Ui.add(about, t, 10);
        LinearLayout help = Ui.add(p, Ui.panel(this), 12);
        help.addView(new Ui.Setting(this, R.drawable.s2_ic_folder, this.getString(R.string.s2_folders), v -> Folders.dialog(this)).value(getString(R.string.s2_folders_note)).chevron(this).view);   // the game, pack and save folders, kept across updates (Folders.java)
        help.addView(new Ui.Setting(this, R.drawable.s2_ic_external, this.getString(R.string.s2_share_log), v -> shareLog()).value(getString(R.string.s2_share_log_note)).chevron(this).view);
    }

    /** A settings group's card of rows, under its section label */
    private LinearLayout settingsCard(LinearLayout content) { return Ui.add(content, Ui.listCard(this), 8); }

    /** The settings rows' current values (after a dialog, on resume) */
    private void refreshSettings() {
        if (overlayRow != null) {
            boolean ov = Prefs.overlay(this);
            if (overlayRow.toggle.isChecked() != ov) overlayRow.toggle.setChecked(ov);
            int n = 0;
            for (String[] it : Overlay.ITEMS) if (Prefs.overlayItem(this, it[0])) n++;
            overlayRow.value(ov ? getString(R.string.s2_overlay_on_items, n, Overlay.ITEMS.length) : getString(R.string.s2_off));
        }
        if (resRow != null) resRow.value(resLabel());
        if (capRow != null) capRow.value(capLabel(Prefs.fpsCap(this)));
        if (lsfgRow != null) lsfgRow.value(!BuildConfig.NX_LSFG ? getString(R.string.s2_lsfg_not_built) : Lsfg.on(this)
                ? getString(R.string.s2_lsfg_on, Lsfg.multiplier(this)) + (Lsfg.find(this) == null ? " · " + getString(R.string.s2_lsfg_dll_missing) : "") : getString(R.string.s2_off));
        if (fsrRow != null) fsrRow.value(GraphicsOptions.modeLabel(this));
        if (fsrSharpRow != null) fsrSharpRow.value(GraphicsOptions.sharpLabel(Fsr.sharp(this)));
        if (aspectRow != null) aspectRow.value(GraphicsOptions.ASPECTS[GraphicsOptions.stretch(this)]);
        if (pipelineRow != null) pipelineRow.value(GraphicsOptions.BACKGROUND[GraphicsOptions.background(this)]);
        if (timingRow != null) timingRow.value(GraphicsOptions.TIMINGS[GraphicsOptions.timing(this)]);
        if (volumeRow != null) {   // Interface's link to Audio: the level, and why the cues are silent when they are (never an enabled switch that plays nothing unexplained)
            LauncherEffects.State st = LauncherEffects.state(this);
            String level = getString(R.string.s2_volume_value, LauncherEffects.volume(this));
            volumeRow.value(st.plays || st == LauncherEffects.State.LOADING || st == LauncherEffects.State.INACTIVE ? level : level + " · " + st.describe(this));
        }
        refreshAudioState();
        if (gpuRow != null) {
            GpuDriver.Info d = GpuDriver.selected(this);
            gpuRow.value(d == null ? getString(R.string.s2_driver_system) : d.label());
        }
    }

    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) refreshSettings();   // back from a dialog (GPU driver, Folders, …)
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        fromIntent(i);
    }

    /** adb: am start -n dev.nxnative.android/.MainActivity --es game <game folder> [--es pack <pack folder>] [--es save <save folder>] [--ez run true] adds the game without
     *  the pickers (android/TESTING.md); --es add_game <folder or .nup> takes Add game's own path instead (gamePicked: all of a folder's games added, Prepare asked); save is the save folder Folders would pick for it (test runs of a play or release app keep away from the user's saves/<id>) */
    private void fromIntent(Intent i) {
        if ((settingsPage || settingsGame != null) && (i.hasExtra("game") || i.hasExtra("add_game") || i.hasExtra("ondevice_dump") || i.hasExtra("ondevice_pause"))) page(false);   // these act on Home's cards
        Ondevice.fromIntent(this, i);   // --es ondevice_dump <dump folder> [--ez ondevice_start true] (Ondevice)
        GpuDriver.fromIntent(this, i);   // --es gpu_driver_zip <zip> / --es gpu_driver <name | system>
        PackUi.fromIntent(this, i);   // test app: --es pack_title <id> --es pack_export <folder> | --es pack_import <zip or folder>
        ShaderUi.fromIntent(this, i);   // test app: --es shaders_title <id> --es shaders_export <folder> | --es shaders_import <zip>
        String fg = i.getStringExtra("frontend_game");   // FrontendLaunch: a game it could not start at once
        if (fg != null) { fromFrontend(new File(fg)); return; }
        String ag = i.getStringExtra("add_game");   // Add game's own path for a picked folder or .nup (gamePicked), without the picker
        if (ag != null) { if (!needAccess()) gamePicked(new File(ag)); return; }
        String game = i.getStringExtra("game");
        if (game == null) return;
        File dir = new File(game);   // a game folder or a .nup (NUP.md)
        String id;
        try { id = Pack.titleIdOf(dir); } catch (IOException e) { error(e.getMessage()); return; }
        String p = i.getStringExtra("pack");
        File pack = p != null ? new File(p) : Folders.packFor(this, dir, id);
        if (pack == null) { error("No pack found for " + id + " next to " + game + "."); return; }
        if (!addWithPack(dir, id, pack)) return;
        String save = i.getStringExtra("save");
        if (save != null) Prefs.folder(this, "save_" + id, new File(save).getPath());
        if (i.getBooleanExtra("run", false)) for (Game g : games) if (g.gameDir.equals(dir.getPath())) { launch(g); break; }
    }

    /** A game a frontend sent that needs the user (FrontendLaunch.ready): its card's Play says what is missing and offers the fix; a new game takes the steps of a picked one */
    private void fromFrontend(File game) {
        if (settingsPage || settingsGame != null) page(false);
        refresh();   // FrontendLaunch may have added its card
        if (needAccess()) return;
        for (Game g : games) if (Frontend.same(g.gameDir, game.getPath())) { launch(g); return; }
        gamePicked(game);
    }

    private static volatile boolean leftoversChecked;   // once per process

    /**
     * The leftovers nothing uses (AppStorageReport.clean: the copies a stopped save restore, import or commit left beside the saves, stopped pack imports, packer
     * trees of older APKs, ...), removed off the main thread at the launcher's first resume, then the storage report written to the Switch2 folder: one such copy
     * filled a phone, and its owner could not reach Android/data to delete it. A save whose game runs is skipped (its lock)
     */
    private void clearSaveLeftovers() {
        if (leftoversChecked) return;
        leftoversChecked = true;
        // every save's copies (also of saves no card names), stale packer trees, stopped imports, old pipeline caches, then the report in the Switch2 folder
        // (AppStorageReport: anything in use is skipped)
        AppStorageReport.atStart(getApplicationContext(), msg -> runOnUiThread(() -> { if (!isDestroyed()) Toast.makeText(this, msg, Toast.LENGTH_LONG).show(); }));
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        clearSaveLeftovers();
        LauncherEffects.resume(this);
        Ondevice.listen(this::prepSummary);
        prepSummary(Ondevice.state());
        Profile.reload();   // a profile folder put in Switch2/profiles while the app was away (Profile.userDir)
        if (gameBox != null && Game.load(this).size() != games.size()) refresh();   // a card FrontendLaunch added while Home was in the background
        onResumeViews();
        if (headerStatus != null) headerStatus.start();   // the header's clock and battery follow the phone again
        getSystemService(android.hardware.input.InputManager.class).registerInputDeviceListener(padListener, null);
        hints(hintLibrary);   // a gamepad connected or removed while the app was away
        if (!settingsPage && settingsGame == null) Ondevice.resume(this);
        Switch2Migration.start(this, this::refresh);   // once All files access is on: the Switch2 folder into Games/, Work/<id>, Mods/ (Switch2Layout), the saved paths repointed
        GameSettings.builtinDefaults(this);   // the profiles' mods that are on by default (BuiltinMods), once per game
    }

    private void onResumeViews() {
        if (accessCard != null) accessCard.setVisibility(Environment.isExternalStorageManager() ? View.GONE : View.VISIBLE);
        refreshSettings();
    }

    @Override protected void onPause() {
        resumed = false;
        cueJob = null;   // a job's state on return is a fresh first sight: no late Ready / Error cue
        if (intro != null) intro.finish();   // never resumed half-way
        glow.cancel();
        if (headerStatus != null) headerStatus.stop();
        getSystemService(android.hardware.input.InputManager.class).unregisterInputDeviceListener(padListener);
        LauncherEffects.pause();
        for (Tile tl : tiles.values()) if (tl.border != null) tl.border.finishAnimation();
        Ondevice.listen(null);
        Ondevice.pause(this);
        super.onPause();
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    /** What the library shows of one game: its card and badge, and what the check found (problem, code), which the selected game's bar uses */
    private static final class Tile {
        final Game game;
        View card;
        FrameLayout art;          // the cover's rounded box (scaled 1.02x when selected)
        TextView caption;         // the one line under the cover
        android.graphics.Bitmap cover;   // the real cover once it is there (CoverGlow takes the selected one)
        CoverFrame frame;
        int jobColor;             // the preparing job's state color (prepSummary)
        TextView badge;
        CardProgressBorder border;
        boolean preparing;
        double progress;
        int progressColor;
        CharSequence baseBadge;
        int baseBadgeColor;
        PackFacts facts;          // what the card's check found in its pack (unchecked until it ran)
        PrepareState own;         // the game's own job as last seen (its job.json, or the service's state of it), null: none
        GameState state;          // what the card shows and does: one state, one button (GameState, docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow")

        Tile(Game g) { game = g; facts = PackFacts.unchecked(Profile.of(g.titleId) != null); }
    }

    /** Home's games: the empty library (no game and nothing being prepared) or the library: its title, the cards and the selected game's bar */
    void refresh() {
        games.clear();
        games.addAll(Game.load(this));
        if (gameBox == null) return;
        if (libraryScroll != null) homeScrollX = libraryScroll.getScrollX();
        gameBox.removeAllViews();
        libTop.removeAllViews();
        tiles.clear();
        boolean empty = games.isEmpty() && !Ondevice.showing();
        refreshButton.setVisibility(empty ? View.GONE : View.VISIBLE);
        if (empty) {
            libTop.setVisibility(View.GONE);
            glow.select(null, null);
            gameBox.addView(emptyLibrary());
            hints(false);
            updateDock();
            return;
        }
        libTop.setVisibility(View.VISIBLE);
        boolean small = compact(), nar = narrow();
        String count = getResources().getQuantityString(R.plurals.s2_games_count, games.size(), games.size());
        // The library's identity, one small line under the header (Library and its count); left out on a low window at the largest fonts, where the dock's
        // selected Library item still says it
        LinearLayout idRow = Ui.row(this);
        TextView label = Ui.section(this, getString(R.string.s2_library));
        label.setPadding(0, 0, 0, 0);
        label.setTextSize(small ? 11 : 12);
        label.setContentDescription(getString(R.string.s2_library) + ", " + count);
        idRow.addView(label);
        TextView counted = Ui.text(this, count, small ? 11 : 12, R.color.bn_text_2, 500);
        counted.setSingleLine(true);
        counted.setEllipsize(TextUtils.TruncateAt.END);
        counted.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);   // the label's description says it
        LinearLayout.LayoutParams cl = Ui.weight();
        cl.leftMargin = dp(8);
        idRow.addView(counted, cl);
        if (!small || getResources().getConfiguration().fontScale < 1.3f) libTop.addView(idRow);
        // The selected game: its name as it is spelled (never upper-cased), one line, ellipsized, so a long name never grows the block or moves the covers;
        // its state / version line beside it on the same baseline (under it on a narrow window)
        libTitle = Ui.text(this, "", small ? 18 : 26, R.color.bn_text, 800);
        libTitle.setSingleLine(true);
        libTitle.setEllipsize(TextUtils.TruncateAt.END);
        libTitle.setIncludeFontPadding(false);
        libTitle.setLetterSpacing(-0.01f);
        libTitle.setAccessibilityHeading(true);
        libLine = Ui.text(this, "", small ? 13 : 15, R.color.bn_text_2, 500);   // its one state / version line
        libLine.setSingleLine(true);
        libLine.setEllipsize(TextUtils.TruncateAt.END);
        if (nar) {
            Ui.add(libTop, libTitle, 2);
            Ui.add(libTop, libLine, 0);
        } else {
            LinearLayout line = new LinearLayout(this);   // top gravity: the two texts share a baseline
            line.setOrientation(LinearLayout.HORIZONTAL);
            int columnDp = Math.min(getResources().getConfiguration().screenWidthDp - 40, 1200);
            libTitle.setMaxWidth(dp(Math.round(columnDp * 0.62f)));   // the line keeps room beside the longest name
            line.addView(libTitle, Ui.wrap());
            LinearLayout.LayoutParams ml = Ui.weight();
            ml.leftMargin = dp(12);
            line.addView(libLine, ml);
            Ui.add(libTop, line, small ? 1 : 2);
        }
        if (games.isEmpty()) {   // the preparation card says what happens
            libTitle.setText(getString(R.string.s2_library));
            libLine.setText(count);
            glow.select(null, null);
            updateDock();
            return;
        }
        if (selected == null || games.stream().noneMatch(g -> g.gameDir.equals(selected))) selected = games.get(0).gameDir;
        android.widget.HorizontalScrollView hs = new android.widget.HorizontalScrollView(this);
        libraryScroll = hs;
        hs.setHorizontalScrollBarEnabled(false);
        hs.setClipToPadding(false);
        hs.setPadding(dp(2), dp(2), dp(2), dp(2));
        LinearLayout row = Ui.row(this);
        row.setGravity(Gravity.TOP);
        if (coverPx <= 0) coverPx = dp(COVER_MIN);
        int size = coverPx, pad = dp(COVER_PAD);   // the last fitted side (LibraryColumn fits it to this window); pad: the focus frame and 1.02x scale, never clipped
        for (Game g : games) {
            Tile tl = new Tile(g);
            tiles.put(g.gameDir, tl);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size + 2 * pad, ViewGroup.LayoutParams.WRAP_CONTENT);
            if (row.getChildCount() > 0) lp.leftMargin = dp(4);
            row.addView(card(tl, size, pad), lp);
            if (Profile.of(g.titleId) != null) check(tl);
        }
        hs.addView(row);
        gameBox.addView(hs, Ui.fill());
        int savedX = homeScrollX;
        hs.post(() -> hs.scrollTo(savedX, 0));
        Ui.add(gameBox, shelf(), small ? 2 : 8);
        hints(true);
        select(selected);
        prepSummary(Ondevice.state());
    }

    /**
     * The empty library (the empty concept): the illustration, the title, one line, Choose folder and what happens next; no frame around it. A low window takes
     * a smaller illustration and title, so the whole block and the pinned footer fit its height
     */
    private View emptyLibrary() {
        boolean small = compact();
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setGravity(Gravity.CENTER_HORIZONTAL);
        ImageView im = new ImageView(this);
        im.setImageResource(R.drawable.s2_library_folder);   // contain: the whole picture, its proportions kept (ui-kit README)
        im.setScaleType(ImageView.ScaleType.FIT_CENTER);
        im.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        c.addView(im, new LinearLayout.LayoutParams(dp(small ? 132 : 220), dp(small ? 120 : 200)));
        TextView h = Ui.text(this, getString(R.string.s2_empty_title), small ? 24 : 34, R.color.bn_text, 800);
        h.setGravity(Gravity.CENTER);
        h.setAccessibilityHeading(true);
        Ui.add(c, h, small ? 4 : 8, Ui.wrap());
        TextView t = Ui.text(this, getString(R.string.s2_empty_text), small ? 15 : 18, R.color.bn_text, 400);
        t.setGravity(Gravity.CENTER);
        Ui.add(c, t, small ? 2 : 6, Ui.wrap());
        Ui.Action pick = Ui.action(this, R.drawable.s2_ic_folder, getString(R.string.s2_choose_folder), Ui.Kind.PRIMARY, v -> addGame());
        LinearLayout.LayoutParams pl = new LinearLayout.LayoutParams(narrow() ? ViewGroup.LayoutParams.MATCH_PARENT : dp(small ? 320 : 360), dp(small ? 52 : 60));
        Ui.add(c, pick, small ? 12 : 22, pl);
        TextView cap = Ui.text(this, getString(R.string.s2_empty_caption), small ? 13 : 14, R.color.bn_text_2, 400);
        cap.setGravity(Gravity.CENTER);
        Ui.add(c, cap, small ? 6 : 12, Ui.wrap());
        return c;
    }

    /**
     * A game's slot in the carousel: its square cover (the real one from Covers; none yet: the controller and its name on the elevated surface), with the
     * preparation stroke on its bottom edge (CardProgressBorder), and one bounded caption under it (a job's state and percent, or a state that is not Ready); the
     * focus frame around the selected one (CoverFrame). The footprint never depends on the name. A tap selects it (it never starts the game: the shelf's action
     * does), a long press opens Manage
     */
    private View card(Tile tl, int size, int pad) {
        Game g = tl.game;
        LinearLayout slot = new LinearLayout(this);
        slot.setOrientation(LinearLayout.VERTICAL);
        slot.setPadding(pad, pad, pad, 0);
        slot.setClipChildren(false);
        slot.setClipToPadding(false);
        slot.setFocusable(true);
        slot.setClickable(true);
        slot.setDefaultFocusHighlightEnabled(false);   // the focus is the selection's frame
        FrameLayout art = new FrameLayout(this);
        art.setBackground(Ui.round(Ui.col(this, R.color.bn_tint), dp(12), 0, 0));
        art.setClipToOutline(true);
        art.setElevation(dp(2));
        LinearLayout ph = new LinearLayout(this);
        ph.setOrientation(LinearLayout.VERTICAL);
        ph.setGravity(Gravity.CENTER);
        ph.setPadding(dp(12), dp(12), dp(12), dp(12));
        ImageView pad48 = new ImageView(this);
        pad48.setImageDrawable(Ui.icon(this, R.drawable.s2_ic_gamepad, R.color.bn_text_2));
        pad48.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        ph.addView(pad48, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView name = Ui.text(this, g.name, 14, R.color.bn_text, 600);
        name.setMaxLines(2);
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setGravity(Gravity.CENTER);
        name.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        Ui.add(ph, name, 8, Ui.wrap());
        art.addView(ph, new FrameLayout.LayoutParams(-1, -1));
        tl.art = art;
        android.graphics.Bitmap cover = Covers.get(g.titleId, b -> { if (tiles.get(g.gameDir) == tl) showCover(tl, b); });
        if (cover != null) showCover(tl, cover);
        slot.addView(art, new LinearLayout.LayoutParams(size, size));
        tl.caption = Ui.text(this, "", 12, R.color.bn_text_2, 500);
        tl.caption.setSingleLine(true);
        tl.caption.setEllipsize(TextUtils.TruncateAt.END);
        tl.caption.setGravity(Gravity.CENTER);
        tl.caption.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);   // the slot's description says it
        // One line at the current font scale: a long state never grows the slot (its height is part of what LibraryColumn measures, not a fixed reservation)
        slot.addView(tl.caption, new LinearLayout.LayoutParams(size, tl.caption.getLineHeight() + dp(4)));
        boolean other = Profile.of(g.titleId) == null;
        // Status remains available to the existing readiness flow and accessibility, without a pill over the artwork.
        tl.badge = Ui.text(this, getString(other ? R.string.s2_badge_unsupported : R.string.s2_badge_checking), 12, R.color.bn_text, 500);
        tl.baseBadge = tl.badge.getText();
        tl.baseBadgeColor = other ? R.color.s2_coral : R.color.bn_text_2;
        tl.border = new CardProgressBorder(this);
        art.setForeground(tl.border);
        tl.frame = new CoverFrame(this, pad, size, dp(12));
        slot.setForeground(tl.frame);
        slot.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener() {
            @Override public void onViewAttachedToWindow(View v) {}
            @Override public void onViewDetachedFromWindow(View v) { tl.border.finishAnimation(); tl.art.animate().cancel(); }
        });
        slot.setContentDescription(g.name);
        slot.setSoundEffectsEnabled(false);
        slot.setOnClickListener(v -> userSelect(g.gameDir));
        slot.setOnFocusChangeListener((v, focused) -> {   // a gamepad or keyboard moved it: the Focus cue; focus given by a rebuild or the opening's end: silent
            if (!focused) return;
            if (android.os.SystemClock.uptimeMillis() - lastKeyAt < 500) userSelect(g.gameDir);
            else select(g.gameDir);
        });
        slot.setOnLongClickListener(v -> { LauncherEffects.play(this, LauncherEffects.Cue.PANEL_OPEN); manage(g); return true; });
        tl.card = slot;
        return slot;
    }

    /** Square eShop artwork fills the square tile. Other aspect ratios stay whole, without distortion. The selected game's also tints the background (CoverGlow) */
    private void showCover(Tile tl, android.graphics.Bitmap b) {
        tl.cover = b;
        tl.art.removeAllViews();
        ImageView front = new ImageView(this);
        front.setImageBitmap(b);
        front.setScaleType(ImageView.ScaleType.FIT_CENTER);
        front.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        tl.art.addView(front, new FrameLayout.LayoutParams(-1, -1));
        if (tl.game.gameDir.equals(selected)) glow.select(tl.game.titleId, b);
    }

    private void badge(TextView b, int colorRes) { b.setBackground(Ui.round(Ui.col(this, colorRes), dp(999), 0, 0)); }

    private long lastKeyAt = -1000;   // the last key pressed (a gamepad or keyboard), so a focus change it caused is told from one a rebuild caused

    @Override public boolean dispatchKeyEvent(android.view.KeyEvent e) {
        if (e.getAction() == android.view.KeyEvent.ACTION_DOWN) lastKeyAt = android.os.SystemClock.uptimeMillis();
        return super.dispatchKeyEvent(e);
    }

    /** A selection the user made (a tap, the focus moved by a gamepad or keyboard): the Focus cue when it changes, never for a restored or rebuilt selection */
    private void userSelect(String gameDir) {
        if (!gameDir.equals(selected)) LauncherEffects.play(this, LauncherEffects.Cue.FOCUS);
        select(gameDir);
    }

    /** Selects a card: its focus frame (CoverFrame), its art raised and, where motion is allowed, scaled 1.02x; the title block and the shelf show it */
    private void select(String gameDir) {
        selected = gameDir;
        boolean still = LauncherTheme.still(this);
        for (Tile tl : tiles.values()) {
            boolean on = tl.game.gameDir.equals(gameDir);
            tl.card.setSelected(on);
            tl.frame.setOn(on);
            tl.art.setElevation(dp(on ? 4 : 2));
            float scale = on && !still ? 1.02f : 1f;
            if (tl.art.getScaleX() != scale) {
                tl.art.animate().cancel();
                if (still || !tl.art.isAttachedToWindow()) { tl.art.setScaleX(scale); tl.art.setScaleY(scale); }
                else tl.art.animate().scaleX(scale).scaleY(scale).setDuration(90).start();
            }
            tl.border.update(on, tl.preparing, tl.progress, tl.progressColor);
        }
        Tile cur = tiles.get(gameDir);
        if (cur != null) glow.select(cur.game.titleId, cur.cover);
        showDetails();
    }

    private TextView libTitle, libLine;   // the selected game's name and its state / version line (refresh)
    private TextView shelfStatus;
    private View shelfDot;
    private Button shelfOptions;
    private Ui.Action detPlay;

    /**
     * The selected game's action strip (Console revision 6, slimmed by docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 2): a pale hairline pill, 44 dp inside
     * its 48 dp touch band, with its readable status (a colored dot and the words: the job's state, percent and step, the first-play note, or the check's state),
     * one compact Options whose icon is the ⋯ (the game's one menu, manage: its settings, folders, saves, pack, log and removal) and the one action its state
     * allows (libraryAction: Play only when ready, Prepare, Pause / Continue / Try again for a job). Every button keeps a 48 dp target; its plate is drawn
     * smaller inside it
     */
    private View shelf() {
        boolean nar = narrow(), small = compact();
        LinearLayout bar = Ui.row(this);
        int hair = Math.max(1, Math.round(0.75f * getResources().getDisplayMetrics().density));
        android.graphics.drawable.Drawable pill = Ui.round(Ui.col(this, R.color.s2_shelf), dp(22), Ui.col(this, R.color.s2_edge), hair);
        bar.setBackground(nar ? pill : new android.graphics.drawable.InsetDrawable(pill, 0, dp(2), 0, dp(2)));
        bar.setElevation(dp(1));
        LinearLayout status = Ui.row(this);
        shelfDot = new View(this);
        shelfDot.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        status.addView(shelfDot, new LinearLayout.LayoutParams(dp(8), dp(8)));
        shelfStatus = Ui.text(this, "", 14, R.color.bn_text, 600);
        shelfStatus.setMaxLines(nar ? 2 : 1);
        shelfStatus.setEllipsize(TextUtils.TruncateAt.END);
        shelfStatus.setPadding(dp(8), 0, dp(8), 0);
        status.addView(shelfStatus, Ui.weight());
        // The status of the game being prepared ("Preparando · 18% · Translating shaders") opens the preparation screen again; for any other game it does nothing
        status.setOnClickListener(v -> {
            Tile tl = tiles.get(selected);
            if (tl != null && tl.state != null && tl.state.job != null && tl.state.jobShown()) { LauncherEffects.play(this, LauncherEffects.Cue.PANEL_OPEN); Ondevice.openScreen(this, tl.state.job); }
        });
        LinearLayout buttons = Ui.row(this);
        // One Options, the ⋯ its icon: the game's one menu (manage), which holds both what Options opened (its settings, first) and what the separate ⋯ did
        shelfOptions = Ui.button(this, getString(R.string.s2_options), Ui.Kind.TONAL, null);
        shelfOptions.setOnClickListener(LauncherEffects.click(LauncherEffects.Cue.PANEL_OPEN, v -> { Tile tl = tiles.get(selected); if (tl != null) manage(tl.game); }));
        android.graphics.drawable.Drawable dots = Ui.icon(this, R.drawable.ic_more, R.color.bn_text);
        dots.setBounds(0, 0, dp(18), dp(18));
        shelfOptions.setCompoundDrawablesRelative(dots, null, null, null);
        shelfOptions.setCompoundDrawablePadding(dp(6));
        shelfOptions.setTextSize(14);
        shelfOptions.setBackground(new android.graphics.drawable.InsetDrawable(shelfOptions.getBackground(), 0, dp(6), 0, dp(6)));   // a 36 dp plate in its 48 dp target
        shelfOptions.setPaddingRelative(dp(12), 0, dp(14), 0);   // after the background: an InsetDrawable reports its insets as padding, which setBackground copies over the view's own
        buttons.addView(shelfOptions, nar ? new LinearLayout.LayoutParams(0, dp(48), 1) : new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(48)));
        detPlay = Ui.action(this, R.drawable.ic_play, getString(R.string.s2_play), Ui.Kind.PRIMARY, v -> {});
        detPlay.setOnClickListener(v -> playSelected());   // its cue depends on what the action does (playSelected)
        detPlay.setMinimumHeight(dp(48));
        detPlay.setMinimumWidth(dp(small ? 128 : 148));   // grows for a long state label (Needs attention), never wider than it needs
        detPlay.label.setTextSize(15);
        detPlay.label.setEllipsize(TextUtils.TruncateAt.END);
        detPlay.icon.getLayoutParams().width = detPlay.icon.getLayoutParams().height = dp(18);
        ((LinearLayout.LayoutParams) detPlay.label.getLayoutParams()).leftMargin = dp(8);
        slimPlate(detPlay);
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(nar ? 0 : ViewGroup.LayoutParams.WRAP_CONTENT, dp(48), nar ? 1.4f : 0);
        pp.leftMargin = dp(6);
        buttons.addView(detPlay, pp);
        if (nar) {
            bar.setOrientation(LinearLayout.VERTICAL);
            bar.setPadding(dp(14), dp(8), dp(8), dp(6));
            bar.addView(status, Ui.fill());
            LinearLayout.LayoutParams bl = Ui.fill();
            bl.topMargin = dp(4);
            bar.addView(buttons, bl);
        } else {
            bar.setPadding(dp(16), 0, dp(2), 0);
            bar.setMinimumHeight(dp(48));
            bar.addView(status, Ui.weight());
            bar.addView(buttons, Ui.wrap());
        }
        return bar;
    }

    /**
     * The state's action keeps its 48 dp target with a 40 dp plate (again after Ui.Action.setKind, which draws a new plate). The side padding is set after the
     * background, every time: an InsetDrawable reports its insets as padding, and setBackground replaces the view's own padding with it
     */
    private void slimPlate(Ui.Action a) {
        if (!(a.getBackground() instanceof android.graphics.drawable.InsetDrawable)) a.setBackground(new android.graphics.drawable.InsetDrawable(a.getBackground(), 0, dp(4), 0, dp(4)));
        a.setPaddingRelative(dp(14), 0, dp(16), 0);
    }

    /** The title block and the shelf for the selected game, from its one state (GameState) */
    private void showDetails() {
        updateDock();
        Tile tl = tiles.get(selected);
        if (tl == null || detPlay == null || libTitle == null) return;
        Game g = tl.game;
        shelfOptions.setContentDescription(getString(R.string.s2_options_menu, g.name));   // always enabled: the menu serves a game without a profile too
        long v = -1;
        try { v = Long.parseLong(Pack.read(new File(g.packDir)).version); } catch (IOException | NumberFormatException e) { /* no pack yet: the version shows once it is prepared */ }
        String version = v < 0 ? "" : v == 0 ? getString(R.string.s2_version_base) : getString(R.string.s2_version_update, v);
        GameState st = tl.state != null ? tl.state : GameState.of(g, Ondevice.state(), tl.own, tl.facts);
        String caption = st.caption(this), state = caption.isEmpty() ? st.badge(this) : caption;
        libTitle.setText(g.name);   // as the game spells it; one line, ellipsized (refresh)
        libLine.setText(version.isEmpty() ? state : state + "  ·  " + version);
        shelfStatus.setText(st.status(this));
        // From the state itself: a rebuild (a rotation, onConfigurationChanged) makes new tiles and shows them before the next job tick
        shelfDot.setBackground(Ui.round(Ui.col(this, st.color()), dp(5), 0, 0));
        detPlay.setKind(st.kind());
        slimPlate(detPlay);
        detPlay.setText(getString(st.labelRes()));
        detPlay.setIcon(st.iconRes());
        detPlay.setEnabled(st.action != GameFlow.Action.CHECKING);   // every other state does something, with a reason and a fix
    }

    /** The selected game's one action: the card's state decides both its label and what it does (GameFlow) */
    private void playSelected() {
        Tile tl = tiles.get(selected);
        if (tl == null) return;
        Game g = tl.game;
        GameState st = tl.state != null ? tl.state : GameState.of(g, Ondevice.state(), tl.own, tl.facts);
        File gd = new File(g.gameDir);
        // One cue for the action: Launch when the game starts (start), Error with a refusal's message (error), Confirm for the job's actions, Panel open for a sheet
        switch (st.action) {
            case PLAY:
                if (!st.auto) { launch(g, true); break; }
                // its code no longer fits (its mods changed, another game build) while its shader library does: rewritten in a short job, then the game starts; no
                // question. Code that other tools made plays as it is (GameFlow), so the short job never rewrites a pack that plays
                if (needAccess() || playBusy(g)) break;
                LauncherEffects.play(this, LauncherEffects.Cue.CONFIRM);
                Ondevice.fixCodeThenPlay(this, gd, new File(g.packDir), false);
                break;
            case PREPARE:
                LauncherEffects.play(this, LauncherEffects.Cue.CONFIRM);
                if (!needAccess()) Ondevice.play(this, gd);
                break;
            case CONTINUE:
            case RETRY:
                LauncherEffects.play(this, LauncherEffects.Cue.CONFIRM);
                Ondevice.resumeJob(this, st.job);
                break;
            case VIEW:
                LauncherEffects.play(this, LauncherEffects.Cue.PANEL_OPEN);
                Ondevice.openScreen(this, st.job);
                break;
            case FIX:
                LauncherEffects.play(this, LauncherEffects.Cue.PANEL_OPEN);
                ProblemSheet.show(this, g, st);
                break;
            default: break;
        }
    }

    /** A save or an export / import of the game works now: Play waits for it (said) */
    private boolean playBusy(Game g) {
        if (SaveUi.busy(g.titleId)) { error(getString(R.string.s2_save_err_play_waits, g.name)); return true; }
        if (PackUi.busy(g.titleId)) { error(getString(R.string.s2_err_pack_busy, g.name)); return true; }
        return false;
    }

    private String cueJob;               // the job last seen while the library was in the foreground (its game, title and version), null after a pause
    private boolean cueReady, cueFailed;  // what it was then

    /** The Ready cue once when the job seen becomes ready to play, the Error cue once when it is interrupted; nothing for the first sight of a job, a repeat or a restore */
    private void prepCue(PrepareState s) {
        if (s == null) { cueJob = null; return; }
        String job = s.dump.getPath() + "|" + s.titleId + "|" + s.version;
        boolean ready = s.canPlay, failed = s.phase == PrepareState.Phase.FAILED;
        if (job.equals(cueJob)) {
            if (ready && !cueReady) LauncherEffects.play(this, LauncherEffects.Cue.READY);
            else if (failed && !cueFailed) LauncherEffects.play(this, LauncherEffects.Cue.ERROR);
        }
        cueJob = job;
        cueReady = ready;
        cueFailed = failed;
    }

    /** A preparing job's state colour: warm yellow while it runs or is paused (the stroke stops, the words say paused), green when ready, coral when interrupted */
    private static int jobColorOf(PrepareState s) {
        return s.canPlay ? R.color.bn_leaf : s.phase == PrepareState.Phase.FAILED ? R.color.s2_coral : R.color.s2_prepare;
    }

    /** Every card's state from the job the launcher follows (s), in place; never rebuild covers or move the carousel on a job tick. */
    private void prepSummary(PrepareState s) {
        if (resumed) prepCue(s);
        for (Tile tl : tiles.values()) render(tl, s);
        showDetails();
    }

    /** A card's one state (GameState: its facts, its own job, the live job), then its badge, the caption under its cover and its progress border */
    private void render(Tile tl, PrepareState live) {
        GameState st = GameState.of(tl.game, live, tl.own, tl.facts);
        tl.state = st;
        if (live != null && live.isFor(tl.game.gameDir)) tl.own = live;   // the newest state seen of this game's job (the live one may move to another game)
        int color = st.color();
        String badge = st.badge(this), caption = st.caption(this);
        tl.baseBadge = badge;
        tl.baseBadgeColor = color;
        tl.badge.setText(badge);
        badge(tl.badge, color);
        tl.caption.setText(caption);
        boolean active = st.jobShown();
        tl.preparing = active;
        tl.jobColor = color;
        tl.card.setContentDescription(tl.game.name + ", " + (caption.isEmpty() ? badge : caption) + (active ? ", " + st.job.stepName : ""));
        if (active) {
            tl.progress = st.job.overall;
            tl.progressColor = Ui.col(this, color);
            tl.border.update(tl.card.isSelected(), true, st.job.overall, tl.progressColor);
        } else tl.border.update(tl.card.isSelected(), false, 0, 0);
    }

    /**
     * The gamepad hints (docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 3), in the footer centered under the dock, only while a gamepad is connected (its
     * row's height goes back to the covers otherwise; padListener follows a connection or a removal). Each names what its button does here: A presses the focused
     * item (the selected cover, or Choose folder in the empty library), B is Back. They are not touch targets
     */
    private void hints(boolean library) {
        hintLibrary = library;
        if (hintRow == null) return;
        hintRow.removeAllViews();
        boolean on = gamepad();
        hintRow.setVisibility(on ? View.VISIBLE : View.GONE);
        if (!on) return;
        hintRow.addView(hint("A", getString(library ? R.string.s2_hint_select : R.string.s2_choose_folder)));
        if (library) {
            LinearLayout.LayoutParams lp = Ui.wrap();
            lp.leftMargin = dp(compact() ? 18 : 24);
            hintRow.addView(hint("B", getString(R.string.s2_hint_back)), lp);
        }
    }

    /** A gamepad connected or removed while Home shows: its hints come or go, and the covers take or give back their row's height */
    private final android.hardware.input.InputManager.InputDeviceListener padListener = new android.hardware.input.InputManager.InputDeviceListener() {
        @Override public void onInputDeviceAdded(int id) { hints(hintLibrary); }
        @Override public void onInputDeviceRemoved(int id) { hints(hintLibrary); }
        @Override public void onInputDeviceChanged(int id) { hints(hintLibrary); }
    };

    /** A real gamepad is connected (the hints and their room in the layout are for it only) */
    private static boolean gamepad() {
        for (int id : android.view.InputDevice.getDeviceIds()) {
            android.view.InputDevice d = android.view.InputDevice.getDevice(id);
            if (d != null && !d.isVirtual() && (d.getSources() & android.view.InputDevice.SOURCE_GAMEPAD) == android.view.InputDevice.SOURCE_GAMEPAD) return true;
        }
        return false;
    }

    /** One hint: a small round keycap and what it does (20 dp high on a low window) */
    private View hint(String button, String what) {
        boolean small = compact();
        LinearLayout h = Ui.row(this);
        TextView k = Ui.text(this, button, small ? 11 : 12, R.color.bn_banana, 800);
        k.setGravity(Gravity.CENTER);
        k.setIncludeFontPadding(false);
        k.setBackground(Ui.round(0, dp(999), Ui.col(this, R.color.bn_banana), Math.max(1, Math.round(1.5f * getResources().getDisplayMetrics().density))));
        h.addView(k, new LinearLayout.LayoutParams(dp(small ? 18 : 22), dp(small ? 18 : 22)));
        TextView t = Ui.text(this, what, small ? 12 : 13, R.color.bn_text_2, 500);
        t.setSingleLine(true);
        t.setPadding(dp(6), 0, 0, 0);
        h.addView(t);
        return h;
    }

    /** What a card's check finds in its pack (off the main thread: NSO headers, the stamp, the mods' digests, and for a fitting pack the rewriter's key) */
    private PackFacts facts(Game g) {
        PackFacts f = new PackFacts();
        f.checked = true;
        Profile prof = Profile.of(g.titleId);
        f.profile = prof != null;
        f.mapShaders = prof != null ? prof.shaderTotal : 0;
        File pd = new File(g.packDir), gd = new File(g.gameDir);
        f.dump = Ondevice.isDump(gd);
        Pack p;
        try { p = Pack.read(pd); } catch (IOException e) {
            f.shadersImported = ShaderZip.ready(pd, g.titleId);
            f.rewrite = true;   // a whole Prepare: the code, and every shader unless they were imported
            f.toTranslate = f.shadersImported ? 0 : f.mapShaders;
            f.shaders = !f.shadersImported;
            return f;
        }
        f.pack = true;
        f.unfinished = p.unfinishedModule() != null;
        if (f.unfinished) { f.rewrite = true; f.shaders = true; f.toTranslate = f.mapShaders; return f; }
        f.build = PackCheck.build(p, gd) != null;
        f.mods = !f.build && PackCheck.mods(p, gd) != null;   // the code lacks a mod the mods folder has now, or has one it no longer has
        f.shadersMissing = Pack.libraryProblem(pd, g.titleId) != null;
        f.shaders = f.shadersMissing;   // the split and the library run even when the manifest keeps every shader (0 to translate)
        if (f.shadersMissing) {
            f.playable = Pack.playableLibrary(pd, g.titleId) != null;
            f.legacy = !f.playable && Pack.legacyLibrary(pd, g.titleId) != null;
            int delta = Ondevice.deltaShaders(pd, g.titleId);
            f.deltaKnown = delta >= 0;
            f.toTranslate = delta >= 0 ? delta : f.mapShaders;   // the manifest's count for the pack's older library, else all of them
        } else f.toTranslate = 0;
        f.rewrite = f.build || f.mods;
        if (!f.build && !f.mods && !f.shadersMissing) f.code = PackCheck.code(this, p, gd);
        return f;
    }

    /** The game's own job (its job.json in its work folder), as the card shows it; null when it has none */
    private PrepareState ownJob(Game g) {
        File jf = Job.fileOf(DumpCheck.workOf(new File(g.gameDir), g.titleId));
        if (!jf.isFile()) return null;
        try {
            Job j = Job.read(jf);
            return j.dump().getPath().equals(g.gameDir) ? PrepareState.of(this, j, false, Ondevice.ready(j)) : null;
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /** A game's state, checked off the main thread: its pack's facts and its own job, then its one state (render), and the bar */
    private void check(Tile tl) {
        Game g = tl.game;
        new Thread(() -> {
            // An APK update whose shaders did not change: the pack's older library becomes this version's by its header (Pack.restamp), before anything else is decided
            String restamped = Pack.restamp(new File(g.packDir), g.titleId);
            if (restamped != null) android.util.Log.i("Swap2Native", g.titleId + ": shader library v-" + restamped + " taken over as v-" + BuildConfig.NX_DMSH_VK_CHAIN + " (restamp)");
            PackFacts f;
            try { f = facts(g); } catch (RuntimeException e) { android.util.Log.w("Swap2Native", g.titleId + ": check: " + e); f = new PackFacts(); f.checked = true; }
            PackFacts facts = f;
            PrepareState own = ownJob(g);
            runOnUiThread(() -> {
                if (tiles.get(g.gameDir) != tl) return;   // the library was built again meanwhile
                tl.facts = facts;
                tl.own = own;
                // An APK update's new shaders: made in the background with no question when the pack's older library is one the delta manifest knows (Ondevice.autoUpdate)
                if (facts.dump && facts.pack && facts.shadersMissing && !facts.build && !facts.mods && facts.deltaKnown)
                    Ondevice.autoUpdate(this, new File(g.gameDir), new File(g.packDir), g.titleId);
                render(tl, Ondevice.state());
                if (g.gameDir.equals(selected)) showDetails();
                if (Boolean.FALSE.equals(facts.code)) android.util.Log.i("Swap2Native", g.titleId + ": its pack's code was made by other tools (Play rewrites it first)");
            });
        }, "nx-pack-check").start();
    }

    /**
     * A game's one menu, its Manage sheet (the action strip's Options, or a long press on its cover): a list of actions (its folders, its settings, its log, its saves, Prepare again for a dump), its facts
     * (title ID, folders) below, and, apart at the bottom, Remove from the list (asked first; it deletes nothing on the storage). Play never sits next to it.
     */
    void manage(Game g) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        File save = Folders.save(this, g);
        String lp = Pack.libraryProblem(new File(g.packDir), g.titleId);
        String noProfile = Profile.missing(g.titleId, g.name);
        AlertDialog[] d = new AlertDialog[1];
        if (noProfile != null) Ui.add(box, Ui.small(this, noProfile), 0);
        // The game's own job (running, paused, interrupted or stopped): its preparation screen, first (the screen opens by itself only when Prepare starts the job)
        Tile own = tiles.get(g.gameDir);
        PrepareState prep = own != null && own.state != null && own.state.job != null && own.state.job.phase != PrepareState.Phase.DONE ? own.state.job : null;
        if (prep != null)
            Ui.add(box, new Ui.Setting(this, R.drawable.ic_build, getString(R.string.s2_prep_view), v -> { d[0].dismiss(); Ondevice.openScreen(this, prep); }).chevron(this).view, 0);
        // First its settings page (what the strip's Options opened before it took this whole menu: docs/REVISAO-UI-AUDIO-CONSOLE-2026-11-07.md section 2)
        if (noProfile == null) Ui.add(box, new Ui.Setting(this, R.drawable.s2_ic_settings, getString(R.string.s2_game_settings), v -> { d[0].dismiss(); GameSettings.dialog(this, g); }).chevron(this).view, 0);
        Ui.add(box, new Ui.Setting(this, R.drawable.s2_ic_folder, this.getString(R.string.s2_folders), v -> { d[0].dismiss(); Folders.dialog(this, g); }).chevron(this).view, 0);
        Ui.add(box, new Ui.Setting(this, R.drawable.s2_ic_external, this.getString(R.string.s2_share_log), v -> { d[0].dismiss(); shareLog(g.titleId); }).chevron(this).view, 0);
        // Save, under its own heading, each with what it does: the app's own backups (<Switch2>/save-backups/<id>/, verified; a restore or import backs up the current
        // save first) and a save as one .zip, in from another emulator or phone, out for one (SaveUi, SaveStore, SaveZip). Import takes a .zip, never a folder
        Ui.add(box, Ui.section(this, getString(R.string.s2_saves)), 16);
        Ui.add(box, new Ui.Setting(this, "💾", getString(R.string.s2_save_backup), v -> { d[0].dismiss(); SaveUi.backup(this, g); }).value(getString(R.string.s2_save_backup_note, SaveUi.backups(g).getPath())).chevron(this).view, 8);
        Ui.add(box, new Ui.Setting(this, "↩️", getString(R.string.s2_save_restore), v -> { d[0].dismiss(); SaveUi.restoreList(this, g); }).value(getString(R.string.s2_save_restore_note)).chevron(this).view, 0);
        Ui.add(box, new Ui.Setting(this, "📥", getString(R.string.s2_save_import), v -> { d[0].dismiss(); SaveUi.importPick(this, g); }).value(getString(R.string.s2_save_import_note)).chevron(this).view, 0);
        Ui.add(box, new Ui.Setting(this, "📤", getString(R.string.s2_save_export), v -> { d[0].dismiss(); SaveUi.exportPick(this, g); }).value(getString(R.string.s2_save_export_note)).chevron(this).view, 0);
        // Advanced, apart: Prepare again, the pack folder, the shaders' and the full pack's export and import (Ondevice.advancedRows, the same rows as Game settings'
        // Preparation): choices the one button never asks for
        Ui.add(box, Ui.section(this, getString(R.string.s2_advanced)), 16);
        LinearLayout adv = new LinearLayout(this);
        adv.setOrientation(LinearLayout.VERTICAL);
        Ondevice.advancedRows(this, g, adv, () -> d[0].dismiss());
        Ui.add(box, adv, 8);
        TextView info = Ui.small(this, "Title ID: " + g.titleId + "\nGame: " + g.gameDir + (Nup.isNup(new File(g.gameDir)) ? " (.nup)" : "") + "\nPack: " + g.packDir
                + "\nShaders: " + (lp == null ? "present (" + BuildConfig.NX_DMSH_VK_CHAIN + ")" + (ShaderZip.imported(new File(g.packDir)) ? getString(R.string.s2_shaders_facts_imported) : "") : lp) + "\nSaves: " + (save != null ? save.getPath() : "not set"));
        info.setTextIsSelectable(true);
        info.setTextSize(12);
        info.setPadding(dp(4), 0, dp(4), 0);
        Ui.add(box, info, 16);
        Ui.add(box, Ui.divider(this), 16, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)));
        Ui.add(box, Ui.button(this, "Remove from list", Ui.Kind.DANGER, v -> { d[0].dismiss(); confirmRemove(g); }), 16);
        d[0] = Ui.sheet(this, g.name, box).setPositiveButton("Done", null).show();
    }

    private void openAccessSettings() {
        try {
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:" + getPackageName())));
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        }
    }

    boolean needAccess() {
        if (Environment.isExternalStorageManager()) return false;
        new AlertDialog.Builder(this).setTitle(R.string.s2_access_title).setMessage(R.string.s2_access_text)
                .setPositiveButton(R.string.s2_access_open, (d, w) -> openAccessSettings()).setNegativeButton(android.R.string.cancel, null).show();
        return true;
    }

    /** Swap2-Native: the pickers start at the phone's Switch2 folder (/sdcard/Switch2), Add game's at its Games/ where the games are kept: picking either adds
     *  every game inside (gamePicked; the Switch2 folder's own and its Games/'s: PackFind.gamesIn); Android's own folder for the app is removed with it, so games never go there */
    static final Uri SWITCH2_URI = Uri.parse("content://com.android.externalstorage.documents/document/primary%3ASwitch2");
    /** The games' own folder, Switch2/Games (Switch2Layout): where Add game's pickers start when it is there */
    static final Uri GAMES_URI = Uri.parse("content://com.android.externalstorage.documents/document/primary%3ASwitch2%2FGames");

    private static Uri gamesStart() { return Switch2Layout.gamesDir(Switch2Layout.root()).isDirectory() ? GAMES_URI : SWITCH2_URI; }

    void pickFolder(int request, String title) {
        Toast.makeText(this, title, Toast.LENGTH_LONG).show();
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, request == PICK_GAME ? gamesStart() : SWITCH2_URI);
        startActivityForResult(i, request);
    }

    /** Add game: the dump is a folder (base/, updates/) or one .nup file (NUP.md); the user says which, then the system picker opens for it */
    void addGame() {
        if (needAccess()) return;
        new AlertDialog.Builder(this).setTitle(R.string.s2_add_title)
                .setItems(new String[] {getString(R.string.s2_add_folder), getString(R.string.s2_add_nup)}, (d, w) -> {
                    if (w == 0) pickFolder(PICK_GAME, getString(R.string.s2_add_pick_folder));
                    else pickNup();
                })
                .setNegativeButton(android.R.string.cancel, null).show();
    }

    /** The system file picker for a .nup; its document is turned into its /storage path (PathUtil.documentToPath), as a picked folder is */
    private void pickNup() {
        Toast.makeText(this, getString(R.string.s2_add_pick_nup), Toast.LENGTH_LONG).show();
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, gamesStart());
        startActivityForResult(i, PICK_NUP);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (Ondevice.activityResult(this, request, result, data)) return;
        if (request == ReadinessActivity.REQUEST) { if (result == ReadinessActivity.FIX_DRIVER) GpuDriver.dialog(this, PICK_DRIVER); return; }   // its "Pick a GPU driver"
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        if (request == PICK_DRIVER) { GpuDriver.picked(this, data.getData()); return; }
        if (GameSettings.activityResult(this, request, data.getData())) return;   // Add mod's file or folder (a game's settings, Mods)
        if (PackUi.documentResult(this, request, data.getData())) return;
        if (ShaderUi.documentResult(this, request, data.getData())) return;
        if (SaveUi.documentResult(this, request, data.getData())) return;   // Import save…'s .zip
        if (request == PICK_NUP) {
            String p = PathUtil.documentToPath(data.getData());
            if (p == null) { error("That file is not on this phone's storage by a path the app can read (" + data.getData() + "). Pick it from the phone's storage (☰ › the phone's name), not from Recent or Downloads."); return; }
            gamePicked(new File(p));
            return;
        }
        if (request == PICK_DLL) {
            String err = Lsfg.install(this, data.getData());
            Toast.makeText(this, err == null ? "Lossless.dll installed" : "Lossless.dll not installed: " + err, Toast.LENGTH_LONG).show();
            return;
        }
        String path = PathUtil.treeToPath(data.getData());
        if (path == null) { error("That folder is not on this phone's storage (" + data.getData() + ")."); return; }
        File dir = new File(path);
        if (Folders.activityResult(this, request, dir)) return;
        if (SaveUi.activityResult(this, request, dir)) return;
        if (PackUi.activityResult(this, request, dir)) return;
        if (ShaderUi.activityResult(this, request, dir)) return;
        if (request == PICK_GAME) gamePicked(dir);
        else if (request == PICK_PACK && pendingGame != null) { pendingPackPick = dir; addWithPack(pendingGame, pendingId, dir); }
    }

    /**
     * A picked game: one .nup, one dump folder (base/exefs/main.npdm or exefs/main.npdm), or a folder that holds games (PackFind.gamesIn: its .nup files and
     * dump subfolders), all of which are added (addAll); a folder with one game is that game
     */
    private void gamePicked(File game) {
        if (Nup.isNup(game) || Nup.wrongCase(game)) { nupPicked(game); return; }
        if (Pack.npdmOf(game) != null) { addAll(List.of(game), true); return; }
        List<File> found = PackFind.gamesIn(game);
        if (!found.isEmpty()) Prefs.open(this, "library").edit().putString("folder", game.getPath()).apply();   // the library folder (Refresh, the folder bar)
        if (found.size() == 1) { gamePicked(found.get(0)); return; }
        if (found.isEmpty()) {
            error(game + " has neither base/exefs/main.npdm nor exefs/main.npdm, no .nup file and no game folder in it. Pick the game's own folder, its .nup file, or the folder that holds your games.");
            return;
        }
        addAll(found, false);
    }

    /** A single .nup (NUP.md): its name and access checked here, the rest as every game (addAll) */
    private void nupPicked(File nup) {
        if (Nup.wrongCase(nup)) { error(nup.getName() + ": rename it so that its name ends in \".nup\" (lower case); the game and the tools read only that name."); return; }
        if (!nup.canRead()) { error(nup + " cannot be read. Check that All files access is on."); return; }
        addAll(List.of(nup), true);
    }

    /** What the background check of Add game found for one game */
    private static final class Pick {
        final File game;
        String id, name, error;   // error: why it cannot be added (unreadable, no profile in this APK), in a sentence
        boolean unsupported;      // no profile in this APK
        boolean dump;             // a dump Prepare starts from (Pack.isDump)
        PackFind.Found pack;      // a pack that plays now or after the automatic shader update (Folders.find), null: none

        Pick(File game) { this.game = game; name = game.getName(); }
    }

    /**
     * Add game for one or more games: each is identified off the main thread (a .nup's TOC is hashed) with its best pack (Folders.find: the picked folder,
     * the app's, beside the game, &lt;id&gt;-work/&lt;any&gt; above it) and checked (PackCheck.blocking), then added on the main thread. A game with a pack that plays
     * now or after the automatic shader update is added with it, with no question. single: one picked game, as before: a dump without such a pack goes to Prepare
     * (Ondevice asks first; it offers an existing pack folder or Import pack… too), a one-version folder to the pack folder picker, and a problem is one message.
     * Several (a picked folder's games): a dump without a usable pack gets a card with its Prepare button (one job at a time is the user's to start), and one
     * message sums up what was added, what this app cannot run and what needs Prepare
     */
    private void addAll(List<File> picked, boolean single) {
        Toast.makeText(this, single ? "Checking " + picked.get(0).getName() + "…" : "Checking " + picked.size() + " games…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            List<Pick> out = new ArrayList<>();
            for (File g : picked) {
                Pick k = new Pick(g);
                out.add(k);
                if (Nup.wrongCase(g)) { k.error = g.getName() + ": rename it so that its name ends in \".nup\" (lower case)."; continue; }
                try { k.id = Pack.titleIdOf(g); } catch (IOException e) { k.error = e.getMessage(); continue; }
                String why = Profile.missing(k.id, single ? "This game" : g.getName());
                if (why != null) { k.unsupported = true; k.error = why; continue; }
                k.name = Profile.of(k.id).name;
                k.dump = Pack.isDump(g);
                String pp = Folders.pickedPack(this, k.id);
                File pd = pp == null ? null : new File(pp);
                try { if (pd != null && !Pack.read(pd).titleId.equals(k.id)) pd = null; } catch (IOException e) { pd = null; }
                k.pack = Folders.find(this, pd, g, k.id);
                android.util.Log.i("Swap2Native", "Add game: " + g + " (" + k.id + "): " + (k.pack == null ? "no usable pack" : "pack " + k.pack.dir + (k.pack.tier == PackFind.READY ? " (ready)" : " (shader update)")));
            }
            runOnUiThread(() -> { if (!isFinishing()) added(out, single); });
        }, "nx-add-game").start();
    }

    private void added(List<Pick> picks, boolean single) {
        if (single) {
            Pick k = picks.get(0);
            if (k.error != null) { error(k.error); return; }
            if (k.pack != null) { addWithPack(k.game, k.id, k.pack.dir); return; }
            if (k.dump) {   // Swap2-Native: added now, prepared the first time it is played (its card's Play)
                cardFor(k.game, k.id);
                refresh();
                Toast.makeText(this, getString(R.string.s2_add_added_dump, k.name), Toast.LENGTH_LONG).show();
                return;
            }
            pendingGame = k.game;
            pendingId = k.id;
            new AlertDialog.Builder(this).setTitle(R.string.s2_add_no_pack_title).setMessage(R.string.s2_add_no_pack)
                    .setPositiveButton(R.string.s2_pick_pack, (d, w) -> pickFolder(PICK_PACK, getString(R.string.s2_pick_pack_title)))
                    .setNegativeButton(android.R.string.cancel, null).show();
            return;
        }
        List<String> ok = new ArrayList<>(), unsupported = new ArrayList<>(), prepare = new ArrayList<>(), noPack = new ArrayList<>(), failed = new ArrayList<>();
        for (Pick k : picks) {
            if (k.unsupported) { unsupported.add(k.game.getName() + " (" + k.id + ")"); continue; }
            if (k.error != null) { failed.add(k.error); continue; }
            if (k.pack != null) {
                String err = add(k.game, k.id, k.pack.dir);
                if (err == null) ok.add(k.pack.pack.name.isEmpty() ? k.name : k.pack.pack.name);
                else failed.add(k.game.getName() + ": " + err);
            } else if (k.dump) {
                cardFor(k.game, k.id);
                prepare.add(k.name);
            } else noPack.add(k.game.getName());
        }
        refresh();
        StringBuilder m = new StringBuilder();
        if (!ok.isEmpty()) m.append("Added: ").append(TextUtils.join(", ", ok)).append(".");
        if (!prepare.isEmpty()) m.append(m.length() > 0 ? "\n\n" : "").append("Prepared the first time you play them: ").append(TextUtils.join(", ", prepare))
                .append(" (once, on this phone, one game at a time).");
        if (!unsupported.isEmpty()) m.append(m.length() > 0 ? "\n\n" : "").append("Not supported by this app: ").append(TextUtils.join(", ", unsupported))
                .append(". This app runs: ").append(TextUtils.join(", ", profileIds())).append(".");
        if (!noPack.isEmpty()) m.append(m.length() > 0 ? "\n\n" : "").append("No pack found: ").append(TextUtils.join(", ", noPack))
                .append(". Add it on its own to pick its pack folder.");
        if (!failed.isEmpty()) m.append(m.length() > 0 ? "\n\n" : "").append("Not added: ").append(TextUtils.join(" ", failed));
        android.util.Log.i("Swap2Native", "Add game: " + m.toString().replace("\n\n", " | "));
        new AlertDialog.Builder(this).setTitle(ok.isEmpty() && prepare.isEmpty() ? "No game added" : "Games added").setMessage(m).setPositiveButton("OK", null).show();
    }

    private static List<String> profileIds() {
        List<String> ids = new ArrayList<>();
        for (Profile p : Profile.all()) ids.add(p.titleId);
        return ids;
    }

    /**
     * The list entry of a game, made when it has none: a game that still needs its pack gets a card whose pack folder is the app's packs/&lt;id&gt;, where Prepare
     * and Import pack… put it (the card says "Needs preparing" and its button prepares). An existing entry of the same game path is kept as it is
     */
    Game cardFor(File game, String id) {
        List<Game> list = Game.load(this);
        for (Game g : list) if (g.gameDir.equals(game.getPath())) return g;
        Profile p = Profile.of(id);
        Game g = new Game(id, p == null ? id : p.name, game.getPath(), AppStorage.pack(this, id).getPath());
        list.add(g);
        Game.save(this, list);
        refresh();
        return g;
    }

    /** Prepare's "Use an existing pack…": the picked pack folder becomes the game's (addWithPack; remembered for this title like a pack picked in Folders) */
    void pickPackFor(File game, String id) {
        pendingGame = game;
        pendingId = id;
        pickFolder(PICK_PACK, getString(R.string.s2_pick_pack_title));
    }

    private boolean addWithPack(File game, String id, File packDir) {
        String err = add(game, id, packDir);
        if (err != null) { error(err); return false; }
        refresh();
        if (packDir.equals(pendingPackPick)) Folders.pickedPack(this, id, packDir.getPath());   // a pack folder the user picked is remembered for this game's next pick and updates
        String note = "";
        String lp = Pack.libraryProblem(packDir, id);
        if (lp != null) note += " " + lp;
        String name;
        try { name = Pack.read(packDir).name; } catch (IOException e) { name = id; }
        Toast.makeText(this, getString(R.string.s2_add_added, name.isEmpty() ? id : name) + note, Toast.LENGTH_LONG).show();
        return true;
    }

    /** The game into the list with this pack folder (replacing an entry of the same game path); null when added, else why not in a sentence */
    private String add(File game, String id, File packDir) {
        Pack pack;
        try { pack = Pack.read(packDir); } catch (IOException e) { return e.getMessage(); }
        if (!pack.titleId.equals(id)) return "The pack is for " + pack.titleId + ", the game " + (Nup.isNup(game) ? ".nup" : "folder") + " holds " + id + ".";
        String why = Profile.missing(id, pack.name.isEmpty() ? null : pack.name);
        if (why != null) return why;
        if (Nup.isNup(game)) {
            String romfs;
            try { romfs = pack.romfsPath(game); } catch (IOException e) { return game.getName() + " cannot be used: " + e.getMessage(); }
            if (romfs == null) return game.getName() + " has no " + pack.romfsSelector() + " with a RomFS (the pack is for version " + pack.version + ").";
        } else if (pack.romfs(game) == null) return "No RomFS in " + game + " (looked for " + pack.romfsRel + ", romfs/ and updates/<version>/romfs).";
        List<Game> list = Game.load(this);
        list.removeIf(g -> g.gameDir.equals(game.getPath()));
        list.add(new Game(id, pack.name.isEmpty() ? id : pack.name, game.getPath(), packDir.getPath()));
        Game.save(this, list);
        return null;
    }

    /** Remove from the list (the Manage sheet): says exactly what goes (the list entry) and what stays (the folders and the saves) */
    private void confirmRemove(Game g) {
        File save = Folders.save(this, g);
        Ui.confirmDanger(this, "Remove " + g.name + "?",
                "Only the list entry goes. Your dump, its pack and your saves" + (save != null ? " (" + save.getPath() + ")" : "") + " stay on the phone; Add game brings it back.",
                "Remove", () -> {
                    List<Game> list = Game.load(this);
                    list.removeIf(x -> x.gameDir.equals(g.gameDir));
                    Game.save(this, list);
                    refresh();
                });
    }

    void launch(Game g) { launch(g, true); }

    /**
     * Play: the game starts when its pack fits. fix: what the dump can remake is remade first (the code in a short job that then starts the game, a missing pack
     * or library by Prepare); false (after a job, Ondevice.Panel.play) says why instead, so a pack that a job could not fix never loops. Every refusal is one
     * sentence from the resources with its fix (ProblemSheet); the checks' own words are in the log
     */
    void launch(Game g, boolean fix) {
        if (needAccess()) return;
        if (Profile.of(g.titleId) == null) { ProblemSheet.show(this, g, GameFlow.Why.NO_PROFILE, false, Profile.missing(g.titleId, g.name)); return; }
        if (playBusy(g)) return;
        File gd = new File(g.gameDir);
        boolean dump = Ondevice.isDump(gd);
        Pack p;
        try {
            p = Pack.read(new File(g.packDir));
        } catch (IOException e) {
            android.util.Log.i("Swap2Native", g.titleId + ": " + e.getMessage());
            if (dump && fix) { Ondevice.play(this, gd); return; }
            ProblemSheet.show(this, g, GameFlow.Why.NO_PACK, dump, e.getMessage());
            return;
        }
        // The pack's code must be of the game build in the folder (else the game crashes at once), of a build this app supports and with the mods there are now
        String bad = PackCheck.playBlocking(this, p, gd);
        if (bad != null) {
            android.util.Log.i("Swap2Native", g.titleId + ": " + bad);
            boolean unfinished = p.unfinishedModule() != null;
            if (dump && fix) {
                if (unfinished) Ondevice.play(this, gd);
                else Ondevice.fixCodeThenPlay(this, gd, new File(g.packDir), false);
                return;
            }
            ProblemSheet.show(this, g, unfinished ? GameFlow.Why.UNFINISHED : PackCheck.build(p, gd) != null ? GameFlow.Why.BUILD : GameFlow.Why.MODS, dump, bad);
            return;
        }
        // The host loads <pack>/shaders/v-<its DMSH_VK_CHAIN>/dmsh_vk.lib: without it the game runs but draws nothing
        String lp = Pack.libraryProblem(new File(g.packDir), g.titleId);
        if (lp != null && Pack.playableLibrary(new File(g.packDir), g.titleId) != null) {   // the older library plays while the update makes this version's (vka_shader.c lib_load)
            if (dump) Ondevice.autoUpdate(this, gd, new File(g.packDir), g.titleId);
            start(g);
            return;
        }
        if (lp != null && Pack.legacyLibrary(new File(g.packDir), g.titleId) != null) {   // made before versioned updates: never blocks Play, says so (the host warns in its log too)
            if (dump) Ondevice.autoUpdate(this, gd, new File(g.packDir), g.titleId);
            Toast.makeText(this, getString(R.string.s2_shaders_legacy), Toast.LENGTH_LONG).show();
            start(g);
            return;
        }
        if (lp != null) {
            android.util.Log.i("Swap2Native", g.titleId + ": " + lp);
            if (dump && fix) { Ondevice.play(this, gd); return; }
            ProblemSheet.show(this, g, GameFlow.Why.SHADERS, dump, lp);
            return;
        }
        start(g);
    }

    private void start(Game g) {
        LauncherEffects.play(this, LauncherEffects.Cue.LAUNCH);   // once, as the game starts (the pool stops with the launcher's pause)
        startActivity(new Intent(this, GameActivity.class).putExtra("title_id", g.titleId).putExtra("name", g.name).putExtra("game", g.gameDir).putExtra("pack", g.packDir));
    }

    /** The overlay's master switch and its items (Overlay.rows); the main screen's switch follows the master switch */
    private void overlayItems() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        Overlay.rows(this, box, null);
        Ui.sheet(this, "Overlay", box).setPositiveButton("Done", null).setOnDismissListener(d -> refreshSettings()).show();
    }

    private String resLabel() { return Prefs.windowName(Prefs.window(this), true); }

    /** Game resolution: the window size the host gives the game (DM_WINDOW), from the next start */
    private void gameRes() {
        int i = Math.max(0, java.util.Arrays.asList(Prefs.WINDOWS).indexOf(Prefs.window(this)));
        new AlertDialog.Builder(this).setTitle("Game resolution").setSingleChoiceItems(Prefs.WINDOW_NAMES, i, (d, w) -> { Prefs.window(this, Prefs.WINDOWS[w]); refreshSettings(); d.dismiss(); })
                .setNegativeButton("Cancel", null).show();
    }

    static String capLabel(int v) { return v < 0 ? "Default" : v == 0 ? "The game's own" : v + " fps"; }

    /** The frame rate cap the next start uses (Prefs.fpsCap, DM_FPS_TARGET); the in-game panel changes it while the game runs */
    private void fpsCap() {
        int cur = Prefs.fpsCap(this), n = Prefs.FPS_CAPS.length;
        String[] labels = new String[n + 1];
        labels[0] = capLabel(-1);
        int checked = 0;
        for (int k = 0; k < n; k++) {
            int v = Prefs.FPS_CAPS[k];
            labels[k + 1] = capLabel(v);
            if (v == cur) checked = k + 1;
        }
        new AlertDialog.Builder(this).setTitle("Frame rate cap")
                .setSingleChoiceItems(labels, checked, (d, w) -> { Prefs.fpsCap(this, w == 0 ? -1 : Prefs.FPS_CAPS[w - 1]); refreshSettings(); d.dismiss(); })
                .setNegativeButton("Cancel", null).show();
    }

    /** Frame generation's settings and the Lossless.dll found (or a manual pick when it is in none of the known places) */
    private void frameGen() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        File dll = Lsfg.find(this);
        Lsfg.rows(this, box, Lsfg.note + (dll != null ? "" : ". Put it in Documents/Emulation/bios or Switch2, or pick it."), () -> {});
        Ui.add(box, Ui.small(this, "Ported from Eden (GPL-3.0-or-later). Lossless.dll is yours; it is never part of the app."), 10);
        Ui.sheet(this, "Frame generation", box).setPositiveButton("Done", null).setOnDismissListener(d -> refreshSettings())
                .setNeutralButton("Pick Lossless.dll", (d, w) -> {
                    Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                    startActivityForResult(i, PICK_DLL);
                }).show();
    }

    private void shareLog() { shareLog(null); }

    /** The newest log of a game (titleId), or of any run (null) */
    void shareLog(String titleId) {
        File log = LogProvider.newest(this, titleId);
        if (log == null) { error(titleId == null ? "No log yet." : "No log of this game yet."); return; }
        Uri uri = LogProvider.uri(log);
        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_STREAM, uri).putExtra(Intent.EXTRA_SUBJECT, "nxnative log " + log.getName());
        send.setClipData(ClipData.newRawUri(log.getName(), uri));
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        startActivity(Intent.createChooser(send, "Share " + log.getName()));
    }

    void error(String msg) {
        LauncherEffects.play(this, LauncherEffects.Cue.ERROR);
        new AlertDialog.Builder(this).setMessage(msg).setPositiveButton(android.R.string.ok, null).show();
    }

    /** A game's settings › Preparation › Prepare again: on Home, where its job shows (the same as Manage's Prepare again) */
    void prepareAgain(Game g) {
        page(false);
        Ondevice.prepare(this, new File(g.gameDir), true);
    }

    /** A game's cover: the library's decoded one when it has it, else Covers' (later arrives on the main thread once downloaded) */
    android.graphics.Bitmap coverOf(Game g, java.util.function.Consumer<android.graphics.Bitmap> later) {
        for (Tile tl : tiles.values()) if (tl.game.gameDir.equals(g.gameDir) && tl.cover != null) return tl.cover;
        return Covers.get(g.titleId, later);
    }
}
