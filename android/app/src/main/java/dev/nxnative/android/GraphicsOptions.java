package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.List;

/**
 * Output-only graphics controls from the 0.1.2-beta feature set.
 * They use existing host Vulkan presentation shaders and driver pipeline compilation.
 * No game shader library regeneration or GMEM shader ABI changes are required.
 */
final class GraphicsOptions {
    private GraphicsOptions() {}

    // 0 native; 1 nearest; 2 bilinear; 3 FSR EASU+RCAS 720p; 4 Qualcomm SGSR1 single-pass 720p.
    static final String[] MODES = {"Automático (bilinear se suportado)", "Vizinho mais próximo", "Bilinear", "FSR 1 (EASU + RCAS até 720p)", "SGSR 1 (1 passagem até 720p)"};
    static final String[] SHARP_NAMES = {"Desligado", "Máxima", "Padrão", "Suave", "Muito suave"};
    static final float[] SHARPS = {-1f, 0f, 0.25f, 0.5f, 1f};
    static final String[] ASPECTS = {"Preservar proporção", "Esticar para preencher"};
    static final String[] BACKGROUND = {"Desativada", "Ativada"};
    static final String[] TIMINGS = {"Perfil do jogo", "Por segmento", "Por submissão"};
    static final String[] REGISTRY = {"Desativada (padrão)", "Ativada (experimental)"};
    static final String[] ENCODER_IDLE = {"Normal (padrão)", "Dormir quando vazio (experimental)"};
    static final String[] FPS_BOOST = {"Desligado (padrão)", "Leve: sincronização GPU + VRS 2×1 se suportado", "Agressivo: sincronização GPU + VRS 2×2 se suportado"};

    static int mode(Context c) {
        SharedPreferences p = Prefs.of(c);
        if (p.contains("present_filter")) return clamp(p.getInt("present_filter", 0), 0, 4);
        // Keep old FSR setting from previously installed V11.
        return p.getBoolean("fsr", false) ? 3 : 0;
    }
    static int mode(Context c, String id) {
        SharedPreferences p = Prefs.of(c);
        String key = Prefs.gameKey("present_filter", id);
        if (p.contains(key)) return clamp(p.getInt(key, 0), 0, 4);
        int previous = mode(c);
        // Ocarina's final output is already 2048x1152 before Vulkan presents
        // it. Prefer the real 720p FSR pipeline rather than the old native-size
        // blit. Respect explicit per-game choices and non-default global mode.
        return Prefs.OCARINA_TITLE.equals(id) && previous == 0 ? 3 : previous;
    }
    static int stretch(Context c) { return clamp(Prefs.of(c).getInt("picture_stretch", 0), 0, 1); }
    static int stretch(Context c, String id) {
        return Prefs.of(c).getInt(Prefs.gameKey("picture_stretch", id), stretch(c));
    }
    static int background(Context c) { return clamp(Prefs.of(c).getInt("bg_pipelines", 1), 0, 1); }
    static int background(Context c, String id) {
        return Prefs.of(c).getInt(Prefs.gameKey("bg_pipelines", id), background(c));
    }
    static int timing(Context c) { return clamp(Prefs.of(c).getInt("gpu_timestamps", 0), 0, 2); }
    static int timing(Context c, String id) {
        return Prefs.of(c).getInt(Prefs.gameKey("gpu_timestamps", id), timing(c));
    }
    static int regDedup(Context c) { return clamp(Prefs.of(c).getInt("reg_dedup", 0), 0, 1); }
    static int regDedup(Context c, String id) {
        return clamp(Prefs.of(c).getInt(Prefs.gameKey("reg_dedup", id), regDedup(c)), 0, 1);
    }
    static int encoderIdle(Context c) { return clamp(Prefs.of(c).getInt("encoder_idle", 0), 0, 1); }
    static int encoderIdle(Context c, String id) {
        return clamp(Prefs.of(c).getInt(Prefs.gameKey("encoder_idle", id), encoderIdle(c)), 0, 1);
    }
    static int fpsBoost(Context c) { return clamp(Prefs.of(c).getInt("oot_fps_boost", 0), 0, 2); }
    static int fpsBoost(Context c, String id) {
        return clamp(Prefs.of(c).getInt(Prefs.gameKey("oot_fps_boost", id), fpsBoost(c)), 0, 2);
    }
    static float sharp(Context c) { return Fsr.sharp(c); }
    static float sharp(Context c, String id) {
        return Prefs.of(c).getFloat(Prefs.gameKey("fsr_sharp", id), sharp(c));
    }
    private static int clamp(int x, int lo, int hi) { return x < lo ? lo : Math.min(x, hi); }

    private static Boolean runningFsr;
    private static int runningMode = -1;
    private static float runningSharp = Float.NaN;
    static int runningMode(Context c, String id) { return runningMode >= 0 ? runningMode : mode(c, id); }
    static float runningSharp(Context c, String id) { return Float.isNaN(runningSharp) ? sharp(c, id) : runningSharp; }

    static void started(Context c, String id, List<String> env) {
        int m = mode(c, id);
        boolean fsr = m == 3 || m == 4;
        float sh = sharp(c, id);
        for (String v : env) {
            try {
                if (v.startsWith("DM_VK_PRESENT_FILTER=")) m = clamp(Integer.parseInt(v.substring(21).trim()), 0, 4);
                else if (v.startsWith("DM_VK_FSR=")) fsr = Double.parseDouble(v.substring(10).trim()) != 0;
                else if (v.startsWith("DM_VK_FSR_SHARP=")) sh = Float.parseFloat(v.substring(16).trim());
            } catch (RuntimeException ignored) { /* unrecognized env.txt value: keep the last valid one */ }
        }
        runningFsr = fsr;
        runningMode = fsr ? (m == 4 ? 4 : 3) : m >= 3 ? 0 : m;
        runningSharp = sh;
    }

    /** Applies to the next launch; game-specific settings override global defaults.
     * Existing user env.txt remains last and takes precedence. */
    static void env(Context c, String id, List<String> out) {
        int m = clamp(mode(c, id), 0, 4);
        out.add("DM_VK_PRESENT_FILTER=" + m);
        out.add("DM_VK_FSR=" + (m == 3 || m == 4 ? 1 : 0));
        out.add("DM_VK_FSR_SHARP=" + sharp(c, id));
        out.add("DM_VK_PICTURE_STRETCH=" + (stretch(c, id) != 0 ? 1 : 0));
        // 0: avoid optimization thread and prewarm; 1: retain driver-supported
        // GPL background optimizer and the existing 2-thread prewarm policy.
        if (background(c, id) == 0) {
            out.add("DM_VK_GPL=0");
            out.add("DM_VK_PREWARM=0");
        } else {
            out.add("DM_VK_GPL=1");
            out.add("DM_VK_PREWARM=2");
        }
        // Optional: skip redundant registration of unchanged texture/sampler descriptors.
        // This is not NX2navi\'s lazy GPU writeback boost, which needs separate validation.
        if (regDedup(c, id) != 0) out.add("DM_VK_REG_DEDUP=1");
        if (encoderIdle(c, id) != 0) out.add("DM_VK_ENC_SPIN_US=0");
        // Zelda-specific GPU FPS Boost: opt-in coarse Vulkan shading for two
        // hot fragment shaders, not NX2navi's incompatible mirror write-back.
        // The native host checks driver feature support and logs fallback.
        if (Prefs.OCARINA_TITLE.equals(id)) {
            out.add("DM_VK_OOT_FPS_BOOST=" + fpsBoost(c, id));
            // Backported from iOS: independent consecutive NVN compute dispatches
            // no longer force individual GPU barriers. Does not rebuild shaders.
            out.add("DM_VK_OOT_DISPATCH_OVERLAP=1");
        }
        int ts = timing(c, id);
        if (ts != 0) out.add("DM_NVN_GPU_TS=" + (ts == 1 ? "segment" : "submission"));
    }

    private static void live(Context c, int m, float sharp) {
        File dir = c.getExternalFilesDir(null);
        if (dir == null) return;
        try (FileWriter f = new FileWriter(new File(dir, "ctl.txt"), true)) {
            f.write("env DM_VK_PRESENT_FILTER=" + m + "\n");
            f.write("env DM_VK_FSR=" + (m == 3 || m == 4 ? 1 : 0) + "\n");
            f.write("env DM_VK_FSR_SHARP=" + sharp + "\n");
        } catch (IOException e) {
            Native.note("[RED] Graphics: live output setting unavailable (" + e.getMessage() + ")");
        }
    }

    static void setMode(Context c, String id, int value, boolean updateLive) {
        value = clamp(value, 0, 4);
        String key = id == null ? "present_filter" : Prefs.gameKey("present_filter", id);
        Prefs.of(c).edit().putInt(key, value).commit();
        if (updateLive && id != null) {
            runningMode = value;
            runningFsr = value == 3 || value == 4;
            live(c, value, runningSharp(c, id));
        }
    }
    static void setSharp(Context c, String id, float value, boolean updateLive) {
        String key = id == null ? "fsr_sharp" : Prefs.gameKey("fsr_sharp", id);
        Prefs.of(c).edit().putFloat(key, value).commit();
        if (updateLive && id != null) {
            runningSharp = value;
            live(c, runningMode(c, id), value);
        }
    }
    static void reset(Context c, String id) {
        SharedPreferences.Editor e = Prefs.of(c).edit();
        for (String k : new String[] {"present_filter", "picture_stretch", "bg_pipelines", "gpu_timestamps", "fsr_sharp", "reg_dedup", "encoder_idle", "oot_fps_boost"})
            e.remove(Prefs.gameKey(k, id));
        e.commit();
    }
    private static String label(String[] a, int i) { return a[clamp(i, 0, a.length - 1)]; }
    static String modeLabel(Context c) { return label(MODES, mode(c)); }
    static String modeLabel(Context c, String id) { return label(MODES, mode(c, id)); }
    static String aspectLabel(Context c, String id) { return label(ASPECTS, stretch(c, id)); }
    static String sharpLabel(float v) {
        for (int i = 0; i < SHARPS.length; i++) if (Math.abs(v - SHARPS[i]) < 0.001f) return SHARP_NAMES[i];
        return String.valueOf(v);
    }

    /** One dialog with a genuine inherit option for per-game overrides. */
    static void choice(Context c, String id, String key, Runnable done) {
        final String[] values;
        final int current;
        final String title;
        switch (key) {
        case "present_filter":
            values = MODES; current = mode(c, id); title = "Upscale de saída (processamento GPU até 720p)"; break;
        case "picture_stretch":
            values = ASPECTS; current = stretch(c, id); title = "Proporção da tela"; break;
        case "bg_pipelines":
            values = BACKGROUND; current = background(c, id); title = "Pipelines em segundo plano"; break;
        case "gpu_timestamps":
            values = TIMINGS; current = timing(c, id); title = "Medição de GPU"; break;
        case "reg_dedup":
            values = REGISTRY; current = regDedup(c, id); title = "Registro de texturas otimizado"; break;
        case "encoder_idle":
            values = ENCODER_IDLE; current = encoderIdle(c, id); title = "Espera do encoder"; break;
        case "oot_fps_boost":
            values = FPS_BOOST; current = fpsBoost(c, id); title = "FPS Boost — VRS (pode reduzir detalhes)"; break;
        case "fsr_sharp":
            values = SHARP_NAMES; current = sharpIndex(sharp(c, id)); title = "Nitidez FSR (saída)"; break;
        default: return;
        }
        boolean own = id != null && Prefs.of(c).contains(Prefs.gameKey(key, id));
        String[] options = id == null ? values : new String[values.length + 1];
        if (id != null) {
            options[0] = "Padrão global";
            System.arraycopy(values, 0, options, 1, values.length);
        }
        new AlertDialog.Builder(c).setTitle(title)
                .setSingleChoiceItems(options, id == null ? current : own ? current + 1 : 0, (d, which) -> {
                    if (id != null && which == 0) {
                        Prefs.of(c).edit().remove(Prefs.gameKey(key, id)).commit();
                    } else {
                        int v = id == null ? which : which - 1;
                        if ("present_filter".equals(key)) setMode(c, id, v, false);
                        else if ("fsr_sharp".equals(key)) setSharp(c, id, SHARPS[v], false);
                        else if ("picture_stretch".equals(key)) integer(c, id, key, v);
                        else if ("bg_pipelines".equals(key)) integer(c, id, key, v);
                        else integer(c, id, key, v);
                    }
                    d.dismiss();
                    if (done != null) done.run();
                }).setNegativeButton(android.R.string.cancel, null).show();
    }
    private static void integer(Context c, String id, String key, int value) {
        Prefs.of(c).edit().putInt(id == null ? key : Prefs.gameKey(key, id), value).commit();
    }
    private static int sharpIndex(float v) {
        for (int i = 0; i < SHARPS.length; i++) if (Math.abs(SHARPS[i] - v) < .001f) return i;
        return 2;
    }
    /** In-game controls: final output upscaler and sharpness change live; other settings restart the game. */
    static void rows(Context c, LinearLayout box, String id) {
        TextView title = new TextView(c);
        title.setText("Imagem final · 0.1.2");
        title.setPadding(0, 24, 0, 0);
        box.addView(title);
        RadioGroup m = new RadioGroup(c);
        int selected = runningMode(c, id);
        for (int i = 0; i < MODES.length; i++) {
            RadioButton b = new RadioButton(c);
            b.setId(4200 + i);
            b.setText(MODES[i]);
            m.addView(b);
            if (selected == i) b.setChecked(true);
        }
        m.setOnCheckedChangeListener((group, checked) -> {
            if (checked < 4200 || checked >= 4200 + MODES.length) return;
            setMode(c, id, checked - 4200, true);
        });
        box.addView(m);
        TextView l = new TextView(c);
        l.setText("Nitidez FSR (saída; não se aplica ao SGSR)");
        box.addView(l);
        RadioGroup sh = new RadioGroup(c);
        for (int i = 0; i < SHARPS.length; i++) {
            RadioButton b = new RadioButton(c);
            b.setId(4300 + i);
            b.setText(SHARP_NAMES[i]);
            sh.addView(b);
            if (Math.abs(runningSharp(c, id) - SHARPS[i]) < .001f) b.setChecked(true);
        }
        sh.setOnCheckedChangeListener((group, checked) -> {
            if (checked >= 4300 && checked < 4300 + SHARPS.length)
                setSharp(c, id, SHARPS[checked - 4300], true);
        });
        box.addView(sh);
        TextView note = new TextView(c);
        note.setText("FSR usa 2 passagens de GPU, SGSR usa 1 passagem até 720p. A resolução interna continua separada; trocar o filtro aplica ao vivo.");
        note.setTextSize(12);
        box.addView(note);
    }
}
