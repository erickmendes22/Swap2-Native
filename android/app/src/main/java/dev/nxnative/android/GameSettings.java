package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * A game's own settings (the shelf's Options, its Manage sheet › Game settings, the dock's Controls), Console revision 6 "Per-game settings"
 * (docs/SWAP2-NATIVE-CONSOLE-REVISAO-v6.md, console-v4/mockups/settings-game-rich-v3.png), in SettingsFrame's rail and pane: a header with the game's real cover,
 * its name, the Per-game badge and the sentence that these settings affect only this title, then six categories. General: GPU driver, pause on return, extra
 * environment lines and Restore defaults (this game's overrides only, asked first). Graphics: resolution and frame rate cap, the Upscaler (agl's NDSR network or
 * FSR 1 in its place, for a game whose shaders have the networks: Profile.ndsrEnv) and the Scene resolution (the game's palette or 720p, an overlay made on the phone
 * from the player's files: SceneOverlay, SceneService), and the profile's mods. Controls: the touch layout (and Mario
 * Kart World's auto-accelerate). Audio: what this game has (nothing of its own). Preparation: the pack's state, Prepare again, export and import. Files: its
 * folders, its mods, its saves and its log. Values are stored per title ID (Prefs.gameKey, GpuDriver.choice); each option shows Inherit global with the value it
 * inherits from the general settings, or Custom with the value set here, which wins for this game only. The in-game panel's frame rate cap is this game's too.
 * GameActivity reads them at start. Its Mods section lists the game's mod folders (ExefsMods; android/README.md "Mods (exefs patches)"): on and off, Remove,
 * Add mod; a change makes the game's code be rewritten at the next Play or Prepare (PackCheck.mods).
 */
final class GameSettings {
    private GameSettings() {}

    static final int PICK_MOD = 50, PICK_MOD_FOLDER = 51;
    private static final String PENDING = "mods_pick";   // Prefs.of: the game folder whose Add mod picker is open (survives the app's process being ended meanwhile)
    private static final Handler UI = new Handler(Looper.getMainLooper());
    /** The categories' ids (MainActivity keeps the one showing in its saved state) */
    static final String GENERAL = "general", GRAPHICS = "graphics", CONTROLS = "controls", AUDIO = "audio", PREPARATION = "preparation", FILES = "files";

    static void dialog(MainActivity a, Game g) {
        a.gameSettings(g);
    }

    /**
     * Builds the page into frame (SettingsFrame.build: category is the one showing, chosen and toList its navigation, dock the lower dock or null); again builds it
     * again after a change, back returns to the library. Returns the scroll view that holds the options
     */
    static ScrollView populate(MainActivity a, Game g, FrameLayout frame, String category, Consumer<String> chosen, Runnable toList, Runnable again, Runnable back, View dock) {
        List<SettingsFrame.Category> cats = new ArrayList<>();
        cats.add(new SettingsFrame.Category(GENERAL, R.drawable.s2_ic_settings, a.getString(R.string.s2_cat_general), a.getString(R.string.s2_game_general_intro),
                p -> general(a, g, p, again)));
        cats.add(new SettingsFrame.Category(GRAPHICS, R.drawable.s2_ic_image, a.getString(R.string.s2_cat_graphics), a.getString(R.string.s2_game_graphics_intro),
                p -> graphics(a, g, p, again)));
        cats.add(new SettingsFrame.Category(CONTROLS, R.drawable.s2_ic_gamepad, a.getString(R.string.s2_dock_controls), a.getString(R.string.s2_game_controls_intro),
                p -> controls(a, g, p, again)));
        cats.add(new SettingsFrame.Category(AUDIO, R.drawable.s2_ic_volume, a.getString(R.string.s2_audio), null, p -> audio(a, p)));
        cats.add(new SettingsFrame.Category(PREPARATION, R.drawable.ic_build, a.getString(R.string.s2_cat_preparation), a.getString(R.string.s2_game_prep_intro),
                p -> preparation(a, g, p)));
        cats.add(new SettingsFrame.Category(FILES, R.drawable.s2_ic_folder, a.getString(R.string.s2_dock_files), a.getString(R.string.s2_game_files_intro),
                p -> files(a, g, p, again)));
        return SettingsFrame.build(a, frame, identity(a, g, back), cats, category, chosen, toList, dock);
    }

    /** The page's header: back, the game's real cover (the controller on the surface until Covers has one), its name with the Per-game badge, and what the page is */
    private static View identity(MainActivity a, Game g, Runnable back) {
        boolean low = SettingsFrame.compact(a);   // a short window: a 44 dp cover and a one-line note, so the rail and pane keep the height
        LinearLayout h = Ui.row(a);
        h.setMinimumHeight(Ui.dp(a, 56));
        h.addView(Ui.back(a, LauncherEffects.Cue.PANEL_CLOSE, v -> back.run()));
        FrameLayout art = new FrameLayout(a);
        art.setBackground(Ui.round(Ui.col(a, R.color.bn_tint), Ui.dp(a, 12), 0, 0));
        art.setClipToOutline(true);
        art.setElevation(Ui.dp(a, 2));
        ImageView im = new ImageView(a);
        im.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        im.setScaleType(ImageView.ScaleType.CENTER);
        im.setImageDrawable(Ui.icon(a, R.drawable.s2_ic_gamepad, R.color.bn_text_2));
        Bitmap cover = a.coverOf(g, b -> { im.setScaleType(ImageView.ScaleType.FIT_CENTER); im.setImageBitmap(b); });
        if (cover != null) { im.setScaleType(ImageView.ScaleType.FIT_CENTER); im.setImageBitmap(cover); }
        art.addView(im, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        int side = Ui.dp(a, low ? 44 : 72);
        LinearLayout.LayoutParams al = new LinearLayout.LayoutParams(side, side);
        al.leftMargin = Ui.dp(a, 12);
        h.addView(art, al);
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(Ui.dp(a, 14), 0, Ui.dp(a, 4), 0);
        LinearLayout nameRow = Ui.row(a);
        TextView name = Ui.text(a, g.name, low ? 20 : 24, R.color.bn_text, 800);
        name.setTypeface(Typeface.create(Typeface.SANS_SERIF, 800, true));
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setAccessibilityHeading(true);
        name.setMaxWidth(Math.round(a.getResources().getConfiguration().screenWidthDp * a.getResources().getDisplayMetrics().density * 0.5f));
        nameRow.addView(name, Ui.wrap());
        TextView badge = Ui.chip(a, a.getString(R.string.s2_per_game));
        badge.setSingleLine(true);
        LinearLayout.LayoutParams bl = Ui.wrap();
        bl.leftMargin = Ui.dp(a, 10);
        nameRow.addView(badge, bl);
        col.addView(nameRow, Ui.fill());
        TextView note = Ui.small(a, a.getString(R.string.s2_per_game_note));
        note.setMaxLines(low ? 1 : 2);
        note.setEllipsize(TextUtils.TruncateAt.END);
        Ui.add(col, note, 2);
        h.addView(col, Ui.weight());
        return h;
    }

    /** General: the GPU driver, pause on return, the extra environment lines, and Restore defaults (this game's overrides only) */
    private static void general(MainActivity a, Game g, LinearLayout p, Runnable again) {
        String id = g.titleId;
        LinearLayout box = Ui.add(p, Ui.panel(a), 16);
        GpuDriver.Info eff = GpuDriver.selected(a, id);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_chip, a.getString(R.string.s2_driver), v -> driver(a, g, again)).value(a.getString(R.string.s2_driver_note))
                .override(a, GpuDriver.choice(a, id) != null, eff == null ? a.getString(R.string.s2_driver_system) : eff.label()).chevron(a).view);
        Ui.Setting ret = new Ui.Setting(a, R.drawable.s2_ic_stop, a.getString(R.string.s2_pause_return), null).toggle(a, Prefs.pauseOnReturn(a, id), (b, on) -> Prefs.pauseOnReturn(a, id, on));
        ret.value(a.getString(R.string.s2_pause_return_note));
        box.addView(ret.view);
        String env = Prefs.gameEnv(a, id);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_info, a.getString(R.string.s2_environment), v -> env(a, g, again))
                .value(env.isEmpty() ? a.getString(R.string.s2_environment_none) : a.getResources().getQuantityString(R.plurals.s2_environment_lines, env.split("\n").length, env.split("\n").length) + ": " + env.replace('\n', ' '))
                .chevron(a).view);
        Ui.Action restore = Ui.action(a, 0, a.getString(R.string.s2_restore_game), Ui.Kind.SOFT, v -> restore(a, g, again));
        LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(a, SettingsFrame.compact(a) ? 48 : 52));   // the pane's gaps: SettingsFrame.fill
        rl.gravity = Gravity.CENTER_HORIZONTAL;
        Ui.add(p, restore, 20, rl);
        TextView rn = Ui.small(a, a.getString(R.string.s2_restore_game_note));
        rn.setGravity(Gravity.CENTER);
        Ui.add(p, rn, 6);
    }

    /**
     * Restore defaults: this game's own resolution, frame rate cap, upscaler, scene resolution, GPU driver, pause on return and extra environment lines go, after the confirmation; never its
     * touch controls (their profile and edits), its mods, saves, pack or shader caches, the general settings or another game's
     */
    private static void restore(MainActivity a, Game g, Runnable again) {
        Ui.confirmDanger(a, a.getString(R.string.s2_restore_game_title, g.name), a.getString(R.string.s2_restore_game_message), a.getString(R.string.s2_restore), () -> {
            String id = g.titleId;
            Prefs.gameWindow(a, id, null);
            Prefs.fpsCap(a, id, null);
            GpuDriver.choice(a, id, null);
            Prefs.gameEnv(a, id, null);
            Prefs.ndsr(a, id, null);
            GraphicsOptions.reset(a, id);  // restore only per-game graphics overrides
            sceneWant(id, null);
            Prefs.scene720(a, id, false);
            Prefs.renderProfile(a,id,0);
            Prefs.classicPasses(a,id,false);
            Prefs.setSceneScale(a, id, null); // restore only this game's resolution choice
            // Experimental GPU skips must not survive Restore defaults.
            Prefs.of(a).edit()
                    .remove(Prefs.gameKey("oot_mesh_route", id))
                    .remove(Prefs.gameKey("oot_hidden_layers", id))
                    .remove(Prefs.gameKey("oot_skip_heavy_fs", id))
                    .remove(Prefs.gameKey("pause_return", id)).commit();
            again.run();
        });
    }

    /** Graphics: resolution (where the profile has a lever for it), frame rate cap (unless the game paces itself), Upscaler and Scene resolution (where they apply) */
    private static void graphics(MainActivity a, Game g, LinearLayout p, Runnable again) {
        String id = g.titleId;
        LinearLayout box = Ui.add(p, Ui.panel(a), 16);
        Profile prof = Profile.of(id);
        if (prof != null && prof.hasResolution())   // only where it does something: a profile with window_fn or graphics_scale rows
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_display, a.getString(R.string.s2_game_resolution), v -> resolution(a, g, again)).value(a.getString(R.string.s2_resolution_note))
                    .override(a, Prefs.ownWindow(a, id), Prefs.windowName(Prefs.gameWindow(a, id), true)).chevron(a).view);
        if (Prefs.ownRate(a, id)) {   // the host found no limiter it can hold for this game: choices would do nothing
            Ui.Setting fixed = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_frame_cap), null).value(a.getString(R.string.s2_frame_cap_own));
            fixed.view.setClickable(false);
            fixed.view.setAlpha(0.6f);
            box.addView(fixed.view);
        } else box.addView(new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_frame_cap), v -> cap(a, g, again)).value(a.getString(R.string.s2_frame_cap_note))
                .override(a, Prefs.ownFpsCap(a, id), MainActivity.capLabel(Prefs.fpsCap(a, id))).chevron(a).view);
        if (prof != null && prof.hasNdsr()) {   // only where agl's NDSR networks are in the game's shaders (Profile.ndsrEnv)
            String choice = Prefs.ndsr(a, id);
            String cur = Prefs.NDSR_SGSR_COMPUTE.equals(choice) ? "SGSR 1 · NDSR interno (teste)"
                    : Prefs.NDSR_SGSR.equals(choice) ? "SGSR 1 · saída 720p (anterior)"
                    : Prefs.NDSR_FSR.equals(choice) ? "Rápida (EASU, menos GPU)" : "Rede original NDSR";
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_image, "Reconstrução da cena (GPU)", v -> upscaler(a, g, again))
                    .value(cur + " · depois do render interno, antes da imagem final").chevron(a).view);
        }
        // The 0.1.2 output controls are independent of the game's shader library:
        // nearest/bilinear/FSR scale the final image, not the GMEM shaders.
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_image, "Filtro da tela (não reduz render)", v -> GraphicsOptions.choice(a, id, "present_filter", again))
                .value(GraphicsOptions.modeLabel(a, id)).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_image, "Nitidez FSR (saída)", v -> GraphicsOptions.choice(a, id, "fsr_sharp", again))
                .value(GraphicsOptions.sharpLabel(GraphicsOptions.sharp(a, id))).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_display, "Proporção da tela", v -> GraphicsOptions.choice(a, id, "picture_stretch", again))
                .value(GraphicsOptions.aspectLabel(a, id)).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_gauge, "Pipelines em segundo plano", v -> GraphicsOptions.choice(a, id, "bg_pipelines", again))
                .value(GraphicsOptions.BACKGROUND[GraphicsOptions.background(a, id)]).chevron(a).view);
        if (Prefs.OCARINA_TITLE.equals(id)) {
            Ui.Setting vegetation = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_full_vegetation), null)
                    .toggle(a, Prefs.fullVegetation(a, id), (b, on) -> Prefs.fullVegetation(a, id, on));
            vegetation.value(a.getString(R.string.s2_full_vegetation_note));
            box.addView(vegetation.view);
            String[] meshNames = {"Híbrido atual", "Compute integral", "Mesh nativo experimental"};
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_gauge,
                    "Execução da vegetação (GPU)", v -> meshRouteDialog(a, g, again))
                    .value(meshNames[Prefs.ocarinaMeshRoute(a, id)] +
                           " · teste A/B; reinicie o jogo").chevron(a).view);
            // Both switches are deliberately experimental. The heavy
            // fragment option is a subset of Hidden layers off; users can
            // benchmark each independently without touching shader packs.
            Ui.Setting hiddenLayers = new Ui.Setting(a, R.drawable.s2_ic_gauge,
                    "Ocultar camadas (teste)", null)
                    .toggle(a, Prefs.hiddenLayersOff(a, id),
                            (b, on) -> Prefs.hiddenLayersOff(a, id, on));
            hiddenLayers.value("Omite os shaders 5684f5e6 e 47eb514f. Pode faltar ceu, neblina ou objetos. Desligado por padrao; reinicie o jogo.");
            box.addView(hiddenLayers.view);
            Ui.Setting heavyFragment = new Ui.Setting(a, R.drawable.s2_ic_gauge,
                    "Descartar fragment shader pesado (teste)", null)
                    .toggle(a, Prefs.skipHeavyFragment(a, id),
                            (b, on) -> Prefs.skipHeavyFragment(a, id, on));
            heavyFragment.value("Omite apenas 5684f5e658eda176. Ja incluido em Ocultar camadas; nao soma o ganho. Pode faltar imagem. Desligado por padrao; reinicie.");
            box.addView(heavyFragment.view);
            Ui.Setting vegetationOptimization = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_vegetation_optimized), null)
                    .toggle(a, Prefs.vegetationOptimized(a, id), (b, on) -> Prefs.vegetationOptimized(a, id, on));
            vegetationOptimization.value(a.getString(R.string.s2_vegetation_optimized_note));
            box.addView(vegetationOptimization.view);
            Ui.Setting contiguous = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_vegetation_contiguous), null)
                    .toggle(a, Prefs.vegetationContiguous(a, id), (b, on) -> Prefs.vegetationContiguous(a, id, on));
            contiguous.value(a.getString(R.string.s2_vegetation_contiguous_note));
            box.addView(contiguous.view);
            Ui.Setting compute = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_compute_optimized), null)
                    .toggle(a, Prefs.computeOptimized(a, id), (b, on) -> Prefs.computeOptimized(a, id, on));
            compute.value(a.getString(R.string.s2_compute_optimized_note));
            box.addView(compute.view);
            Ui.Setting fragment = new Ui.Setting(a, R.drawable.s2_ic_gauge, a.getString(R.string.s2_fragment_optimized), null)
                    .toggle(a, Prefs.fragmentOptimized(a, id), (b, on) -> Prefs.fragmentOptimized(a, id, on));
            fragment.value(a.getString(R.string.s2_fragment_optimized_note));
            box.addView(fragment.view);
            // Internal A/B: same APK/driver/scene, compare original GPU
            // bitmap copy+fill against direct writing into fenced ring slots.
            // Does NOT remove texture ID discovery or downscale the image.
            Ui.Setting feedback = new Ui.Setting(a, R.drawable.s2_ic_gauge,
                    a.getString(R.string.s2_texture_feedback_direct), null)
                    .toggle(a, Prefs.poolFeedbackDirect(a, id),
                            (b, on) -> Prefs.poolFeedbackDirect(a, id, on));
            feedback.value(a.getString(R.string.s2_texture_feedback_direct_note));
            box.addView(feedback.view);
        }
        Ui.Setting ram = new Ui.Setting(a, R.drawable.s2_ic_chip, "Economia de RAM (usa armazenamento)", null)
                .toggle(a, Prefs.ramSaver(a, id), (b, on) -> Prefs.ramSaver(a, id, on));
        ram.value("Guarda pools grandes de texturas no cache em armazenamento. Pode gravar ~2 GB "
                + "a cada carregamento de area; precisa de espaco livre. Padrao: desligado. "
                + "Reinicie o jogo para aplicar.");
        box.addView(ram.view);
        // Selective HDR VRS, including driver-queried 4x2/4x4 modes.
        // The game retains all original shaders and output dimensions.
        if (Prefs.OCARINA_TITLE.equals(id)) {
            box.addView(new Ui.Setting(a, R.drawable.s2_ic_gauge,
                    a.getString(R.string.s2_vrs_heavy_title),
                    v -> GraphicsOptions.choice(a, id, "oot_hotpass_vrs", again))
                    .value(GraphicsOptions.vrsLabel(a, id)).chevron(a).view);
            Ui.add(box, Ui.small(a, a.getString(R.string.s2_vrs_heavy_note)), 6);
        }
        if (Prefs.OCARINA_TITLE.equals(id) && prof != null && prof.hasScene()) {
            box.addView(new Ui.Setting(a,R.drawable.s2_ic_display,a.getString(R.string.s2_oot_classic_passes),null)
                .toggle(a,Prefs.classicPasses(a,id),(button,on)->Prefs.classicPasses(a,id,on)).view);
            Ui.add(box,Ui.small(a,a.getString(R.string.s2_oot_classic_passes_note)),6);
            String[] names=renderProfileNames(a);
            box.addView(new Ui.Setting(a,R.drawable.s2_ic_display,a.getString(R.string.s2_oot_render_profile),
                    v -> renderProfile(a,g,again)).value(names[Prefs.renderProfile(a,id)]).chevron(a).view);
            Ui.add(box,Ui.small(a,a.getString(R.string.s2_oot_render_profile_note)),6);
        }
        if (prof != null && prof.hasScene() && Prefs.renderProfile(a,id)==0) {   // only where the profile names the palette's scale (scene_scale_palette; SceneOverlay)
            boolean on = Prefs.scene720(a, id);
            String cur = on ? Prefs.sceneLabel(Prefs.sceneScale(a, id, prof.sceneScale())) : a.getString(R.string.s2_scene_game);
            Ui.Setting row = new Ui.Setting(a, R.drawable.s2_ic_display, "Resolução interna da cena (GPU)", v -> scene(a, g, again))
                    .value(cur + " · " + a.getString(R.string.s2_scene_note));
            box.addView(row.chevron(a).view);
            if (on) sceneCheck(a, g, prof, row, cur);
        }
        builtinMods(a, g, box);
        Ui.add(p, Ui.small(a, a.getString(R.string.s2_game_graphics_hint)), 8);
    }

    /** The APK's assets as BuiltinMods reads them (assets/mods/&lt;title ID&gt;/&lt;folder&gt;/…, build.gradle nxProfileMods) */
    static BuiltinMods.Source assets(Context c) {
        android.content.res.AssetManager am = c.getApplicationContext().getAssets();
        return new BuiltinMods.Source() {
            @Override public String[] list(String dir) throws IOException {
                String[] l = am.list(dir);
                return l == null ? new String[0] : l;
            }

            @Override public InputStream open(String path) throws IOException { return am.open(path); }
        };
    }

    /** A string resource by name (a profile's mod.tsv names its label and note), else fallback */
    private static String named(Context c, String res, String fallback) {
        int rid = res.isEmpty() ? 0 : c.getResources().getIdentifier(res, "string", c.getPackageName());
        return rid == 0 ? fallback : c.getString(rid);
    }

    /**
     * The mods the game's profile ships (BuiltinMods: Zelda: Ocarina of Time's plain movie player), each a switch: on copies it into the mods folder (an ordinary
     * mod from then on, in the Mods section too), off gives its folder the '-'; either way the next Play or Prepare rewrites the code (PackCheck.mods)
     */
    private static void builtinMods(MainActivity a, Game g, LinearLayout box) {
        BuiltinMods.Source src = assets(a);
        File root = PackCheck.modsRoot();
        for (BuiltinMods.Builtin b : BuiltinMods.of(src, g.titleId)) {
            String label = named(a, b.label, BuiltinMods.fallbackLabel(b));
            Ui.Setting row = new Ui.Setting(a, R.drawable.s2_ic_image, label, null).value(named(a, b.note, ""));
            row.toggle(a, BuiltinMods.isOn(root, b), (button, on) -> button.post(() -> {   // after the switch's own change: the page is built again
                if (a.needAccess()) { a.gameSettingsChanged(g); return; }   // the mods folder is on the shared storage
                Prefs.of(a).edit().putBoolean(b.decidedKey(), true).commit();   // chosen: BuiltinMods.applyDefaults leaves it alone from now on
                modJob(a, g, "nx-mod-builtin", () -> {
                    BuiltinMods.set(root, b, on, src);
                    return a.getString(on ? R.string.s2_mods_on : R.string.s2_mods_off, label);
                });
            }));
            box.addView(row.view);
        }
    }

    private static final java.util.concurrent.atomic.AtomicBoolean DEFAULTS = new java.util.concurrent.atomic.AtomicBoolean();

    /**
     * Once per process, at the launcher's start (onResume) once All files access is on and the Switch2 folder has its layout (Switch2Migration.DONE): the
     * profile mods whose mod.tsv says android_default on are installed for each game in the list that never had them decided (BuiltinMods.applyDefaults)
     */
    static void builtinDefaults(MainActivity a) {
        if (!android.os.Environment.isExternalStorageManager() || !Prefs.of(a).getBoolean(Switch2Migration.DONE, false)) return;
        if (!DEFAULTS.compareAndSet(false, true)) return;
        Context c = a.getApplicationContext();
        List<Game> games = Game.load(c);
        new Thread(() -> {
            BuiltinMods.Source src = assets(c);
            java.util.Set<String> decided = new java.util.HashSet<>();
            for (Map.Entry<String, ?> e : Prefs.of(c).getAll().entrySet()) if (e.getKey().startsWith("builtin_mod_") && Boolean.TRUE.equals(e.getValue())) decided.add(e.getKey());
            java.util.Set<String> seen = new java.util.HashSet<>();
            boolean any = false;
            for (Game g : games) {
                if (!seen.add(g.titleId)) continue;
                try {
                    for (String k : BuiltinMods.applyDefaults(PackCheck.modsRoot(), g.titleId, src, decided)) { Prefs.of(c).edit().putBoolean(k, true).commit(); any = true; }
                } catch (IOException | RuntimeException e) { android.util.Log.w("nxmods", "profile mods of " + g.titleId + ": " + e); }
            }
            // a mod installed: the cards check again, so a pack whose mods changed shows Play with its short job, not a Play that then refuses
            if (any) a.runOnUiThread(() -> { if (!a.isDestroyed()) a.refresh(); });
        }, "nx-mod-defaults").start();
    }

    /** Controls: the touch layout this game uses (its per-game layout, size, opacity and vibration stay with it) and Mario Kart World's auto-accelerate */
    private static void controls(MainActivity a, Game g, LinearLayout p, Runnable again) {
        String id = g.titleId;
        LinearLayout touch = Ui.add(p, Ui.panel(a), 16);
        String touchChoice = Prefs.open(a, "touch_controls").getString("profile@" + TouchProfile.gameKey(id), TouchProfile.AUTO);
        int touchLabel = TouchControls.profileLabel(touchChoice);
        touch.addView(new Ui.Setting(a, R.drawable.s2_ic_gamepad, a.getString(R.string.s2_touch_profile), v -> touchProfile(a, g, again))
                .value(a.getString(touchLabel)).chevron(a).view);
        if (TouchProfile.MKW.equals(TouchProfile.gameKey(id))) {
            String autoKey = "race_auto@" + TouchProfile.gameKey(id);
            touch.addView(new Ui.Setting(a, R.drawable.s2_ic_gamepad, a.getString(R.string.s2_race_auto), null)
                    .toggle(a, Prefs.open(a, "touch_controls").getBoolean(autoKey, false),
                            (button, on) -> Prefs.open(a, "touch_controls").edit().putBoolean(autoKey, on).commit()).view);
        }
        Ui.add(p, Ui.small(a, a.getString(R.string.s2_touch_per_game)), 8);
        if (TouchProfile.MKW.equals(TouchProfile.gameKey(id))) Ui.add(p, Ui.small(a, a.getString(R.string.s2_race_hint)), 8);
    }

    /** Audio: no per-game audio option exists; says so and where the sound's level comes from, instead of showing switches that would do nothing */
    private static void audio(MainActivity a, LinearLayout p) {
        LinearLayout box = Ui.add(p, Ui.panel(a), 16);
        Ui.Setting none = new Ui.Setting(a, R.drawable.s2_ic_volume, a.getString(R.string.s2_game_audio_none), null).value(a.getString(R.string.s2_game_audio_note));
        none.view.setClickable(false);
        box.addView(none.view);
    }

    /** Preparation: the pack's real state (version, shader library, imported or not), Prepare again from a dump (on Home, where its job shows), the shaders' and the pack's export and import */
    private static void preparation(MainActivity a, Game g, LinearLayout p) {
        LinearLayout box = Ui.add(p, Ui.panel(a), 16);
        File pd = new File(g.packDir), gd = new File(g.gameDir);
        String version;
        try {
            long v = Long.parseLong(Pack.read(pd).version);
            version = v == 0 ? a.getString(R.string.s2_version_base) : a.getString(R.string.s2_version_update, v);
        } catch (IOException | NumberFormatException e) { version = a.getString(R.string.s2_pack_none); }
        Ui.Setting pack = new Ui.Setting(a, R.drawable.s2_ic_file, a.getString(R.string.s2_pack_state), null).value(version);
        pack.view.setClickable(false);
        box.addView(pack.view);
        String lp = Pack.libraryProblem(pd, g.titleId);
        File playable = Pack.libraryOf(pd) == null ? Pack.playableLibrary(pd, g.titleId) : null;
        String libraryText = lp != null ? lp : playable != null
                ? "Biblioteca anterior compatível (ABI " + BuildConfig.NX_DMSH_VK_ABI + "): "
                        + playable.getParentFile().getName().substring(2)
                        + ". O Vulkan já a utiliza; shaders faltantes aparecem no log."
                : a.getString(ShaderZip.imported(pd) ? R.string.s2_shaders_state_imported : R.string.s2_shaders_present, BuildConfig.NX_DMSH_VK_CHAIN);
        Ui.Setting shaders = new Ui.Setting(a, R.drawable.s2_ic_image, a.getString(R.string.s2_shaders_state), null)
                .value(libraryText);
        shaders.view.setClickable(false);
        box.addView(shaders.view);
        // Advanced, the same rows as the game's Options (Ondevice.advancedRows): Prepare again, the pack folder, the shaders' and the full pack's export and import
        Ui.add(p, Ui.section(a, a.getString(R.string.s2_advanced)), 16);
        LinearLayout acts = Ui.add(p, Ui.panel(a), 8);
        Ondevice.advancedRows(a, g, acts, null);
    }

    /** Files: the game's folders, its mods (the Mods section), its saves and its newest log */
    private static void files(MainActivity a, Game g, LinearLayout p, Runnable again) {
        LinearLayout box = Ui.add(p, Ui.panel(a), 16);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_folder, a.getString(R.string.s2_folders), v -> Folders.dialog(a, g)).value(a.getString(R.string.s2_folders_game_note)).chevron(a).view);
        box.addView(new Ui.Setting(a, R.drawable.s2_ic_external, a.getString(R.string.s2_share_log), v -> a.shareLog(g.titleId)).chevron(a).view);
        mods(a, g, p, again);
        Ui.add(p, Ui.section(a, a.getString(R.string.s2_saves)), 24);
        LinearLayout saves = Ui.add(p, Ui.panel(a), 8);
        // the same four as the game's Options menu, with the same names and notes (SaveUi): the app's own backups, and a save as a .zip in and out
        saves.addView(new Ui.Setting(a, R.drawable.s2_ic_file, a.getString(R.string.s2_save_backup), v -> SaveUi.backup(a, g)).value(a.getString(R.string.s2_save_backup_note, SaveUi.backups(g).getPath())).chevron(a).view);
        saves.addView(new Ui.Setting(a, R.drawable.s2_ic_retry, a.getString(R.string.s2_save_restore), v -> SaveUi.restoreList(a, g)).value(a.getString(R.string.s2_save_restore_note)).chevron(a).view);
        saves.addView(new Ui.Setting(a, R.drawable.s2_ic_folder_open, a.getString(R.string.s2_save_import), v -> SaveUi.importPick(a, g)).value(a.getString(R.string.s2_save_import_note)).chevron(a).view);
        saves.addView(new Ui.Setting(a, R.drawable.s2_ic_external, a.getString(R.string.s2_save_export), v -> SaveUi.exportPick(a, g)).value(a.getString(R.string.s2_save_export_note)).chevron(a).view);
    }

    /**
     * The Mods section: each mod folder of the game (ExefsMods.list, on and off, Atmosphere's too) with its patch files and the modules of the game's build they
     * are for (filled in off the main thread: moduleIds), an on/off switch (the folder's '-') and Remove; then Add mod and where the folder is
     */
    private static void mods(MainActivity a, Game g, LinearLayout page, Runnable again) {
        File root = PackCheck.modsRoot();
        Ui.add(page, Ui.section(a, a.getString(R.string.s2_mods)), 24);
        LinearLayout box = Ui.add(page, Ui.panel(a), 8);
        List<ExefsMods.Mod> list = ExefsMods.list(root, g.titleId);
        List<Ui.Setting> rows = new ArrayList<>();
        if (list.isEmpty()) {
            Ui.Setting none = new Ui.Setting(a, R.drawable.s2_ic_file, a.getString(R.string.s2_mods_none), null);
            none.view.setClickable(false);
            Ui.add(box, none.view, 0);
        }
        for (ExefsMods.Mod m : list) {
            Ui.Setting row = new Ui.Setting(a, R.drawable.s2_ic_file, m.name, null);
            row.view.addView(Ui.iconButton(a, R.drawable.s2_ic_close, a.getString(R.string.s2_mods_remove), Ui.Kind.QUIET, v -> removeMod(a, g, m, again)));
            row.toggle(a, m.on, (b, on) -> b.post(() -> toggleMod(a, g, m, on, again)));   // after the switch's own change: the page is built again
            row.value(modStatus(a, m, null));
            Ui.add(box, row.view, 0);
            rows.add(row);
        }
        Ui.add(page, Ui.button(a, a.getString(R.string.s2_mods_add), Ui.Kind.TONAL, v -> addMod(a, g)), 8, Ui.wrap());
        Ui.add(page, Ui.small(a, a.getString(R.string.s2_mods_hint, new File(root, g.titleId).getPath())), 8);
        if (list.isEmpty()) return;
        new Thread(() -> {
            Map<String, String> ids = moduleIds(g);
            List<String> labels = new ArrayList<>();
            for (ExefsMods.Mod m : list) labels.add(modStatus(a, m, ids));
            UI.post(() -> { for (int i = 0; i < rows.size(); i++) rows.get(i).value(labels.get(i)); });
        }, "nx-mods-check").start();
    }

    /**
     * The game's modules and their build IDs, as the rewrite sees them (PackCheck.mods): the modules of the pack's version in the game, else, before the first
     * Prepare, the dump's of the build Prepare would take (DumpCheck). Empty when neither can be read. Reads NSO headers: off the main thread
     */
    static Map<String, String> moduleIds(Game g) {
        Map<String, String> out = new LinkedHashMap<>();
        File gd = new File(g.gameDir);
        try {
            Pack p = Pack.read(new File(g.packDir));
            for (String m : p.modules) {
                PackCheck.Mod nso = PackCheck.mod(gd, p.version, m);
                if (nso.exists()) out.put(m, DumpCheck.nsoBuildId(nso.head(0x60), m));
            }
        } catch (IOException | RuntimeException e) { out.clear(); }   // no pack yet, or one that cannot be read: the dump's
        if (out.isEmpty() && Ondevice.isDump(gd)) {
            try { out.putAll(DumpCheck.check(gd, 0).buildIds); } catch (RuntimeException e) { /* a dump that cannot be read: no modules */ }
        }
        return out;
    }

    /** A mod's row value: its patch files and the modules they are for ("applies to main"), or that none of this build's is ("a mod for another version"); ids null: still checking */
    private static String modStatus(Context a, ExefsMods.Mod m, Map<String, String> ids) {
        int n = m.patches().size();
        String s;
        if (n == 0) s = a.getString(R.string.s2_mods_no_files);
        else {
            String match;
            if (ids == null) match = a.getString(R.string.s2_mods_checking);
            else if (ids.isEmpty()) match = a.getString(R.string.s2_mods_unknown);
            else {
                List<String> hit = new ArrayList<>();
                for (Map.Entry<String, String> e : ids.entrySet()) {
                    try { if (!m.matching(e.getValue()).isEmpty()) hit.add(e.getKey()); } catch (IOException x) { /* a .pchtxt that cannot be read matches nothing */ }
                }
                match = hit.isEmpty() ? a.getString(R.string.s2_mods_no_match) : a.getString(R.string.s2_mods_applies, String.join(", ", hit));
            }
            s = a.getResources().getQuantityString(R.plurals.s2_mods_files, n, n) + " · " + match;
        }
        return m.atmosphere ? a.getString(R.string.s2_mods_atmosphere, s) : s;
    }

    private static void modToast(Context a, String s) { Toast.makeText(a.getApplicationContext(), s, Toast.LENGTH_LONG).show(); }

    private interface ModJob { String run() throws IOException; }

    /** A change to the mod folders off the main thread (a mod with a large romfs can take a while to delete), then its line and the page again */
    private static void modJob(MainActivity a, Game g, String thread, ModJob job) {
        new Thread(() -> {
            String msg;
            try { msg = job.run() + " " + a.getString(R.string.s2_mods_changed); }
            catch (Throwable e) { msg = a.getString(R.string.s2_mods_error, GpuDriver.why(e)); }   // SecurityException, an unreadable folder: never the app's end
            final String m = msg;
            UI.post(() -> {
                modToast(a, m);
                if (!a.isFinishing() && !a.isDestroyed()) a.gameSettingsChanged(g);
            });
        }, thread).start();
    }

    /** On or off: the folder renamed without or with its leading '-' (ExefsMods.setEnabled: a clash takes the first free name) */
    private static void toggleMod(MainActivity a, Game g, ExefsMods.Mod m, boolean on, Runnable again) {
        modJob(a, g, "nx-mod-toggle", () -> a.getString(on ? R.string.s2_mods_on : R.string.s2_mods_off, ExefsMods.setEnabled(m, on).name));
    }

    /** Remove, asked first: that mod's folder only (ExefsMods.remove checks it is one of the game's mod folders) */
    private static void removeMod(MainActivity a, Game g, ExefsMods.Mod m, Runnable again) {
        Ui.confirmDanger(a, a.getString(R.string.s2_mods_remove_title, m.name), a.getString(R.string.s2_mods_remove_message, m.dir.getPath()),
                a.getString(R.string.s2_mods_remove), () -> modJob(a, g, "nx-mod-remove", () -> {
                    ExefsMods.remove(PackCheck.modsRoot(), g.titleId, m);
                    return a.getString(R.string.s2_mods_removed, m.name);
                }));
    }

    /** Add mod: a .zip, .ips or .pchtxt (the document picker: Downloads too) or a folder (the folder picker), into the game's mods folder (activityResult) */
    private static void addMod(MainActivity a, Game g) {
        if (a.needAccess()) return;   // the mods folder is on the shared storage
        new AlertDialog.Builder(a).setTitle(R.string.s2_mods_add_title)
                .setItems(new String[] {a.getString(R.string.s2_mods_add_file), a.getString(R.string.s2_mods_add_folder)}, (d, w) -> {
                    Prefs.of(a).edit().putString(PENDING, g.gameDir).commit();
                    if (w == 1) { a.pickFolder(PICK_MOD_FOLDER, a.getString(R.string.s2_mods_pick_folder)); return; }
                    Toast.makeText(a, R.string.s2_mods_pick_file, Toast.LENGTH_LONG).show();
                    a.startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")   // some providers label zips and .ips otherwise
                            .putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed", "application/octet-stream", "text/plain", "*/*"}), PICK_MOD);
                }).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** MainActivity.onActivityResult: the file or folder Add mod picked; false when the request is not Add mod's */
    static boolean activityResult(MainActivity a, int request, Uri uri) {
        if (request != PICK_MOD && request != PICK_MOD_FOLDER) return false;
        String gameDir = Prefs.of(a).getString(PENDING, null);
        Prefs.of(a).edit().remove(PENDING).commit();
        Game g = null;
        if (gameDir != null) for (Game x : Game.load(a)) if (x.gameDir.equals(gameDir)) g = x;
        if (g == null) { a.error(a.getString(R.string.s2_mods_lost)); return true; }
        File root = PackCheck.modsRoot();
        if (request == PICK_MOD) {
            String name = displayName(a, uri);
            stageMod(a, g, name, () -> {
                try (InputStream in = a.getContentResolver().openInputStream(uri)) {
                    if (in == null) throw new IOException("cannot open " + uri);
                    return ExefsMods.stage(root, in, name);
                }
            });
        } else {
            String p = PathUtil.treeToPath(uri);
            if (p == null) { a.error(a.getString(R.string.s2_mods_not_local)); return true; }
            File dir = new File(p);
            stageMod(a, g, dir.getName(), () -> ExefsMods.stage(root, dir));
        }
        return true;
    }

    /** A picked document's name (its provider's DISPLAY_NAME), else the end of its URI */
    private static String displayName(Context c, Uri uri) {
        try (Cursor k = c.getContentResolver().query(uri, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (k != null && k.moveToFirst() && !k.isNull(0)) return k.getString(0);
        } catch (RuntimeException e) { /* a provider without the column: the URI's name */ }
        String last = uri.getLastPathSegment();
        return last == null ? "mod" : last.replaceAll(".*[/:]", "");
    }

    private interface StageJob { ExefsMods.Staged run() throws IOException; }

    /** Unpacks the pick off the main thread behind a wait dialog (ExefsMods.stage: names checked, MAX_BYTES), then asks Replace / Keep both when a mod of that name is there */
    private static void stageMod(MainActivity a, Game g, String what, StageJob job) {
        AlertDialog wait = new AlertDialog.Builder(a).setMessage(a.getString(R.string.s2_mods_adding, what)).setCancelable(false).create();
        wait.show();
        new Thread(() -> {
            ExefsMods.Staged got = null;
            List<String> clash = new ArrayList<>(), both = new ArrayList<>();
            String fail = null;
            try {
                got = job.run();
                clash = ExefsMods.clashes(PackCheck.modsRoot(), g.titleId, got);
                both = ExefsMods.keepBothNames(PackCheck.modsRoot(), g.titleId, got);
            } catch (Throwable e) { fail = GpuDriver.why(e); }   // never let an add end the app (a damaged zip throws unchecked exceptions)
            final ExefsMods.Staged st = got;
            final List<String> c = clash, kb = both;
            final String f = fail;
            UI.post(() -> {
                boolean gone = a.isFinishing() || a.isDestroyed();
                if (!gone) { try { wait.dismiss(); } catch (RuntimeException ignored) { /* its window is gone */ } }
                if (f != null) {
                    if (gone) modToast(a, a.getString(R.string.s2_mods_failed, f));
                    else a.error(a.getString(R.string.s2_mods_failed, f));
                    return;
                }
                if (c.isEmpty()) { commitMod(a, g, st, false); return; }   // the page reopened meanwhile too: nothing to ask, so it is added (commitMod says so)
                if (gone) {   // a question with no page to ask it on (the screen was made again, dark mode say): nothing added, and it says so
                    new Thread(() -> ExefsMods.discard(st), "nx-mod-discard").start();
                    modToast(a, a.getString(R.string.s2_mods_failed, a.getString(R.string.s2_mods_interrupted)));
                    return;
                }
                List<String> renamed = new ArrayList<>();   // the clashing ones' names under Keep both
                List<String> staged = st.names();
                for (int i = 0; i < staged.size() && i < kb.size(); i++) if (c.contains(staged.get(i))) renamed.add(kb.get(i));
                new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_mods_clash_title, String.join(", ", c)))
                        .setMessage(a.getString(R.string.s2_mods_clash_message, String.join(", ", renamed))).setCancelable(false)
                        .setPositiveButton(R.string.s2_mods_replace, (d, w) -> commitMod(a, g, st, true))
                        .setNeutralButton(R.string.s2_mods_keep_both, (d, w) -> commitMod(a, g, st, false))
                        .setNegativeButton(android.R.string.cancel, (d, w) -> new Thread(() -> ExefsMods.discard(st), "nx-mod-discard").start()).show();
            });
        }, "nx-mod-add").start();
    }

    /** Moves the staged mods into the game's folder (ExefsMods.commit), says so in one line (and what was left out), and shows the page again */
    private static void commitMod(MainActivity a, Game g, ExefsMods.Staged st, boolean replace) {
        new Thread(() -> {
            List<String> got = null;
            String fail = null;
            try { got = ExefsMods.commit(PackCheck.modsRoot(), g.titleId, st, replace); }
            catch (Throwable e) { fail = GpuDriver.why(e); }
            final List<String> names = got;
            final String f = fail;
            UI.post(() -> {
                boolean gone = a.isFinishing() || a.isDestroyed();
                if (f != null) {
                    if (gone) modToast(a, a.getString(R.string.s2_mods_failed, f));
                    else a.error(a.getString(R.string.s2_mods_failed, f));
                } else {
                    String msg = a.getString(R.string.s2_mods_added, String.join(", ", names)) + " " + a.getString(R.string.s2_mods_changed);
                    if (st.skipped.isEmpty() || gone) modToast(a, msg);
                    else {
                        List<String> l = st.skipped.size() > 12 ? new ArrayList<>(st.skipped.subList(0, 12)) : st.skipped;
                        if (l != st.skipped) l.add("…");
                        new AlertDialog.Builder(a).setTitle(R.string.s2_mods_skipped_title)
                                .setMessage(msg + "\n\n" + a.getString(R.string.s2_mods_skipped, String.join("\n", l))).setPositiveButton(android.R.string.ok, null).show();
                    }
                }
                if (!gone) a.gameSettingsChanged(g);
            });
        }, "nx-mod-commit").start();
    }

    static String windowLabel(MainActivity a, String id) {
        String w = Prefs.gameWindow(a, id);
        String l = Prefs.windowName(w, false);
        return Prefs.ownWindow(a, id) ? l : "Default · " + l;
    }

    private static void touchProfile(MainActivity a, Game g, Runnable done) {
        String[] values = TouchProfile.choices(g.titleId);
        String[] labels = new String[values.length];
        for (int i = 0; i < values.length; i++) labels[i] = a.getString(TouchControls.profileLabel(values[i]));
        String key = "profile@" + TouchProfile.gameKey(g.titleId);
        String selected = Prefs.open(a, "touch_controls").getString(key, TouchProfile.AUTO);
        int checked = Math.max(0, Arrays.asList(values).indexOf(selected));
        new AlertDialog.Builder(a).setTitle(R.string.s2_touch_profile).setSingleChoiceItems(labels, checked, (dialog, index) -> {
            Prefs.open(a, "touch_controls").edit().putString(key, values[index]).commit();
            dialog.dismiss(); done.run();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    static String capLabel(MainActivity a, String id) {
        String l = MainActivity.capLabel(Prefs.fpsCap(a, id));
        return Prefs.ownFpsCap(a, id) ? l : "Default · " + l;
    }

    static String driverLabel(MainActivity a, String id) {
        GpuDriver.Info i = GpuDriver.selected(a, id);
        String l = i == null ? "System (the phone's own driver)" : i.label();
        return GpuDriver.choice(a, id) != null ? l : "Default · " + l;
    }

    private static void resolution(MainActivity a, Game g, Runnable done) {
        String[] labels = new String[Prefs.WINDOWS.length + 1];
        labels[0] = a.getString(R.string.s2_inherit_choice, Prefs.windowName(Prefs.window(a), false));
        System.arraycopy(Prefs.WINDOW_NAMES, 0, labels, 1, Prefs.WINDOW_NAMES.length);
        int checked = Prefs.ownWindow(a, g.titleId) ? 1 + Math.max(0, Arrays.asList(Prefs.WINDOWS).indexOf(Prefs.gameWindow(a, g.titleId))) : 0;
        new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_game_resolution) + " · " + g.name).setSingleChoiceItems(labels, checked, (x, w) -> {
            Prefs.gameWindow(a, g.titleId, w == 0 ? null : Prefs.WINDOWS[w - 1]);
            x.dismiss();
            done.run();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    private static void cap(MainActivity a, Game g, Runnable done) {
        int n = Prefs.FPS_CAPS.length;
        String[] labels = new String[n + 2];
        labels[0] = a.getString(R.string.s2_inherit_choice, MainActivity.capLabel(Prefs.fpsCap(a)));
        labels[1] = MainActivity.capLabel(-1);
        int checked = 0;
        boolean own = Prefs.ownFpsCap(a, g.titleId);
        int cur = Prefs.fpsCap(a, g.titleId);
        if (own && cur < 0) checked = 1;
        for (int k = 0; k < n; k++) {
            labels[k + 2] = MainActivity.capLabel(Prefs.FPS_CAPS[k]);
            if (own && Prefs.FPS_CAPS[k] == cur) checked = k + 2;
        }
        new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_frame_cap) + " · " + g.name).setSingleChoiceItems(labels, checked, (x, w) -> {
            Prefs.fpsCap(a, g.titleId, w == 0 ? null : w == 1 ? -1 : Prefs.FPS_CAPS[w - 2]);
            x.dismiss();
            done.run();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** Upscaler: the game's NDSR network or FSR 1 in its place (Prefs.ndsr, the profile's ndsr_default without a choice; the host's lines at the next start, Profile.ndsrEnv) */
    /** Ocarina-only mesh route experiment: do not change a running Vulkan device. */
    private static void meshRouteDialog(MainActivity a, Game g, Runnable done) {
        if (!Prefs.OCARINA_TITLE.equals(g.titleId)) return;
        String[] names = {
            "Híbrido atual (padrão; mesh base nativo + vegetação em compute)",
            "Compute integral (todos os mesh draws; comparar com Banana)",
            "Mesh nativo integral (experimental; pode mostrar espinhos/falhas)"
        };
        int selected = Prefs.ocarinaMeshRoute(a, g.titleId);
        new AlertDialog.Builder(a)
            .setTitle("Execução da vegetação · " + g.name)
            // Android AlertDialog does NOT display list items when a message
            // is also assigned: AlertController chooses the message view
            // instead of the list. Keep this dialog list-only.
            .setSingleChoiceItems(names, selected, (dialog, which) -> {
                Prefs.ocarinaMeshRoute(a, g.titleId, which);
                dialog.dismiss();
                done.run();
            })
            .setNegativeButton(android.R.string.cancel, null)
            .show();
    }

    private static void upscaler(MainActivity a, Game g, Runnable done) {
        // A/B requires the old 720p presentation route to stay available:
        // full internal SGSR1 currently works at the game's 2048x1152 NDSR
        // target and may cost more GPU. No automatic migration of settings.
        String[] labels = {"Rede original NDSR (mais pesada)",
                "Modo rápido EASU (menos GPU)",
                "SGSR 1 anterior · reconstrução na saída 720p",
                "SGSR 1 interno · NDSR completo (teste de performance)"};
        String selected = Prefs.ndsr(a, g.titleId);
        int checked = Prefs.NDSR_SGSR_COMPUTE.equals(selected) ? 3
                    : Prefs.NDSR_SGSR.equals(selected) ? 2
                    : Prefs.NDSR_FSR.equals(selected) ? 1 : 0;
        new AlertDialog.Builder(a).setTitle("Reconstrução da cena · " + g.name).setSingleChoiceItems(labels, checked, (x, w) -> {
            Prefs.ndsr(a, g.titleId, w == 3 ? Prefs.NDSR_SGSR_COMPUTE
                    : w == 2 ? Prefs.NDSR_SGSR
                    : w == 1 ? Prefs.NDSR_FSR : Prefs.NDSR_NET);
            if (w == 2) GraphicsOptions.setMode(a, g.titleId, 4, false);
            if (w == 3) GraphicsOptions.setMode(a, g.titleId, 2, false);
            x.dismiss();
            done.run();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** Patches the engine's original dynamic-resolution palette in a RomFS overlay.
     * Output FSR / bilinear remain separate post-render filters, not scene resolution. */
    private static void scene(MainActivity a, Game g, Runnable done) {
        Profile prof = Profile.of(g.titleId);
        if (prof == null || !prof.hasScene()) return;
        String current = Prefs.sceneScale(a, g.titleId, prof.sceneScale());
        boolean oot = Prefs.OCARINA_TITLE.equals(g.titleId);
        String[] labels;
        int checked = 0;
        if (oot) {
            labels = new String[Prefs.OCARINA_SCENE_SCALES.length + 1];
            labels[0] = a.getString(R.string.s2_scene_game);
            System.arraycopy(Prefs.OCARINA_SCENE_NAMES, 0, labels, 1, Prefs.OCARINA_SCENE_NAMES.length);
            if (Prefs.scene720(a, g.titleId)) for (int i = 0; i < Prefs.OCARINA_SCENE_SCALES.length; i++)
                if (Prefs.OCARINA_SCENE_SCALES[i].equals(current)) checked = i + 1;
        } else {
            labels = new String[] {a.getString(R.string.s2_scene_game), a.getString(R.string.s2_scene_720p)};
            checked = Prefs.scene720(a, g.titleId) ? 1 : 0;
        }
        new AlertDialog.Builder(a).setTitle("Resolução interna da cena · " + g.name).setSingleChoiceItems(labels, checked, (x, w) -> {
            x.dismiss();
            if (w == 0) {
                sceneWant(g.titleId, null);
                Prefs.scene720(a, g.titleId, false);
                done.run();
            } else makeScene(a, g, prof, oot ? Prefs.OCARINA_SCENE_SCALES[w - 1] : prof.sceneScale());
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    /** The pack's version and the RomFS as the host takes it ({version, romfs}), or null with no pack or RomFS. Reads pack.tsv and the .nup: off the main thread */
    private static String[] sceneInputs(Game g) {
        try {
            Pack p = Pack.read(new File(g.packDir));
            String romfs = p.romfsPath(new File(g.gameDir));
            return romfs == null ? null : new String[] {p.version, romfs};
        } catch (IOException | RuntimeException e) { return null; }
    }

    /** A 720p row whose overlay no longer matches the pack (an update, another scale in the profile): says so; a tap on 720p makes it again */
    private static void sceneCheck(MainActivity a, Game g, Profile prof, Ui.Setting row, String cur) {
        File files = a.getExternalFilesDir(null);
        new Thread(() -> {
            String[] in = sceneInputs(g);
            boolean ok = files != null && in != null && SceneOverlay.current(files, g.titleId, Prefs.renderSceneScale(a, g.titleId, prof.sceneScale()), prof.sceneExpect(), in[0]);
            if (!ok) UI.post(() -> row.value(a.getString(R.string.s2_scene_stale)));
        }, "nx-scene-check").start();
    }

    /**
     * 720p chosen: the overlay is made from the player's own RomFS by gsys_dynres.py in the packer's process (SceneService) unless the one there matches, behind
     * a wait dialog; the setting is on only once the overlay is there. Refused while a Prepare step runs (BUSY), and with no pack yet
     */
    /**
     * The player's last Scene resolution choice per game in this process (true: 720p): an overlay's answer turns 720p on only while that is still the choice, so
     * "Game default" or Restore defaults while it is being made win, and a second 720p (answered RUNNING) is turned on by the first run's answer
     */
    private static final java.util.Map<String, String> SCENE_WANT = new java.util.HashMap<>();
    private static void sceneWant(String id, String scale) {
        synchronized (SCENE_WANT) { if (scale == null) SCENE_WANT.remove(id); else SCENE_WANT.put(id, scale); }
    }
    private static boolean sceneWanted(String id, String scale) {
        synchronized (SCENE_WANT) { return scale.equals(SCENE_WANT.get(id)); }
    }

    private static void makeScene(MainActivity a, Game g, Profile prof, String selectedScale) {
        makeScene(a,g,prof,selectedScale,Prefs.renderProfile(a,g.titleId));
    }
    private static String[] renderProfileNames(MainActivity a) {
        return new String[]{a.getString(R.string.s2_oot_render_profile_current),
            a.getString(R.string.s2_oot_render_profile_360),a.getString(R.string.s2_oot_render_profile_540)};
    }
    private static void renderProfile(MainActivity a, Game g, Runnable done) {
        Profile prof=Profile.of(g.titleId);if(prof==null || !prof.hasScene())return;
        int current=Prefs.renderProfile(a,g.titleId);
        new AlertDialog.Builder(a).setTitle(R.string.s2_oot_render_profile)
            .setSingleChoiceItems(renderProfileNames(a),current,(dialog,which)->{
                dialog.dismiss();
                if(which==current){done.run();return;}
                // Commit the new mode only after its exact scene overlay is
                // successfully prepared; a failed job keeps the old mode.
                makeScene(a,g,prof,Prefs.sceneScale(a,g.titleId,prof.sceneScale()),which);
            }).setNegativeButton(android.R.string.cancel,null).show();
    }
    private static void makeScene(MainActivity a, Game g, Profile prof, String selectedScale, int mode) {
        File files = a.getExternalFilesDir(null);
        String token=selectedScale+":"+mode;
        sceneWant(g.titleId, token);
        // Back closes it (the :pack process could end without an answer: the first run there also unpacks the packer); the answer still turns 720p on and says so
        AlertDialog wait = new AlertDialog.Builder(a).setMessage(R.string.s2_scene_making).setCancelable(true).create();
        wait.show();
        String id = g.titleId, scale = OcarinaRenderProfile.scale(mode,selectedScale), expect = prof.sceneExpect();
        new Thread(() -> {
            String[] in = sceneInputs(g);
            boolean have = files != null && in != null && SceneOverlay.current(files, id, scale, expect, in[0]);
            UI.post(() -> {
                boolean gone = a.isFinishing() || a.isDestroyed();
                if (in == null || files == null || have) {
                    if (!gone) { try { wait.dismiss(); } catch (RuntimeException ignored) { /* its window is gone */ } }
                    if (have) { if (sceneWanted(id, token)) { Prefs.setSceneScale(a, id, selectedScale); Prefs.renderProfile(a,id,mode); Prefs.scene720(a, id, true); modToast(a, Prefs.OCARINA_TITLE.equals(id)
                                    ? "Perfil " + (mode==0 ? Prefs.sceneLabel(selectedScale) : renderProfileNames(a)[mode]) + " preparado; vale no próximo início (tamanho dinâmico)"
                                    : a.getString(R.string.s2_scene_made)); } }
                    else if (gone) modToast(a, a.getString(R.string.s2_scene_failed, a.getString(R.string.s2_scene_no_pack)));
                    else a.error(a.getString(R.string.s2_scene_failed, a.getString(R.string.s2_scene_no_pack)));
                    if (!gone) a.gameSettingsChanged(g);
                    return;
                }
                SceneService.start(a, id, in[1], scale, expect, in[0], new android.os.ResultReceiver(UI) {
                    @Override protected void onReceiveResult(int code, android.os.Bundle data) {
                        String msg = data == null ? null : data.getString(SceneService.MESSAGE);
                        boolean end = a.isFinishing() || a.isDestroyed();
                        if (!end) { try { wait.dismiss(); } catch (RuntimeException ignored) { /* its window is gone */ } }
                        if (code == 0) {
                            // made, but turned on only when the player has not chosen otherwise meanwhile (the overlay stays: a later 720p takes it at once)
                            if (sceneWanted(id, token)) { Prefs.setSceneScale(a, id, selectedScale); Prefs.renderProfile(a,id,mode); Prefs.scene720(a, id, true); modToast(a, Prefs.OCARINA_TITLE.equals(id)
                                    ? "Perfil " + (mode==0 ? Prefs.sceneLabel(selectedScale) : renderProfileNames(a)[mode]) + " preparado; vale no próximo início (tamanho dinâmico)"
                                    : a.getString(R.string.s2_scene_made)); }
                        } else if (code == SceneService.RUNNING) {
                            // an earlier run (its wait dialog closed with Back) is still making it; its answer turns 720p on while 720p is still the choice
                            modToast(a, a.getString(R.string.s2_scene_running));
                        } else {
                            String why = code == SceneService.BUSY ? a.getString(R.string.s2_scene_busy) : msg != null ? msg : "exit " + code;
                            if (end) modToast(a, a.getString(R.string.s2_scene_failed, why));
                            else a.error(a.getString(R.string.s2_scene_failed, why));
                        }
                        if (!end) a.gameSettingsChanged(g);
                    }
                });
            });
        }, "nx-scene-make").start();
    }

    private static void driver(MainActivity a, Game g, Runnable done) {
        List<GpuDriver.Info> inst = GpuDriver.installed(a);
        GpuDriver.Info def = GpuDriver.selected(a);
        List<String> labels = new ArrayList<>();
        labels.add(a.getString(R.string.s2_inherit_choice, def == null ? a.getString(R.string.s2_driver_system) : def.label()));
        labels.add(a.getString(R.string.s2_driver_system_long));
        String c = GpuDriver.choice(a, g.titleId);
        int checked = c == null ? 0 : c.equals(GpuDriver.SYSTEM) ? 1 : 0;
        for (int k = 0; k < inst.size(); k++) {
            labels.add(inst.get(k).label());
            if (c != null && inst.get(k).dir.getName().equals(c)) checked = k + 2;
        }
        new AlertDialog.Builder(a).setTitle(a.getString(R.string.s2_driver) + " · " + g.name).setSingleChoiceItems(labels.toArray(new String[0]), checked, (x, w) -> {
            GpuDriver.choice(a, g.titleId, w == 0 ? null : w == 1 ? GpuDriver.SYSTEM : inst.get(w - 2).dir.getName());
            x.dismiss();
            done.run();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }

    private static void env(MainActivity a, Game g, Runnable done) {
        EditText t = new EditText(a);
        t.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        t.setMinLines(4);
        t.setTypeface(android.graphics.Typeface.MONOSPACE);
        t.setTextSize(13);
        t.setHint("DM_WATCH_STALL=25");
        t.setText(Prefs.gameEnv(a, g.titleId));
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(Ui.small(a, "KEY=VALUE lines for the host, one a line (# starts a comment). They come after env.txt and win over it, for " + g.name + " only."));
        Ui.add(box, t, 8);
        Ui.sheet(a, "Extra environment · " + g.name, box).setPositiveButton("Save", (x, w) -> { Prefs.gameEnv(a, g.titleId, t.getText().toString()); done.run(); })
                .setNeutralButton("Clear", (x, w) -> { Prefs.gameEnv(a, g.titleId, null); done.run(); }).setNegativeButton(android.R.string.cancel, null).show();
    }
}
