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

    // 0 game/native (unchanged host scaling); 1 nearest; 2 bilinear; 3 FSR 1 EASU+RCAS.
    static final String[] MODES = {"Automático (bilinear se suportado)", "Vizinho mais próximo", "Bilinear", "FSR 1 (filtro final)"};
    static final String[] SHARP_NAMES = {"Desligado", "Máxima", "Padrão", "Suave", "Muito suave"};
    static final float[] SHARPS = {-1f, 0f, 0.25f, 0.5f, 1f};
    static final String[] ASPECTS = {"Preservar proporção", "Esticar para preencher"};
    static final String[] BACKGROUND = {"Desativada", "Ativada"};
    static final String[] TIMINGS = {"Perfil do jogo", "Por segmento", "Por submissão"};
    static final String[] REGISTRY = {"Desativada (padrão)", "Ativada (experimental)"};
    static final String[] ENCODER_IDLE = {"Normal (padrão)", "Dormir quando vazio (experimental)"};

    static int mode(Context c) {
        SharedPreferences p = Prefs.of(c);
        if (p.contains("present_filter")) return clamp(p.getInt("present_filter", 0), 0, 3);
        // Keep old FSR setting from previously installed V11.
        return p.getBoolean("fsr", false) ? 3 : 0;
    }
    static int mode(Context c, String id) {
        return Prefs.of(c).getInt(Prefs.gameKey("present_filter", id), mode(c));
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
        boolean fsr = m == 3;
        float sh = sharp(c, id);
        for (String v : env) {
            try {
                if (v.startsWith("DM_VK_PRESENT_FILTER=")) m = clamp(Integer.parseInt(v.substring(21).trim()), 0, 3);
                else if (v.startsWith("DM_VK_FSR=")) fsr = Double.parseDouble(v.substring(10).trim()) != 0;
                else if (v.startsWith("DM_VK_FSR_SHARP=")) sh = Float.parseFloat(v.substring(16).trim());
            } catch (RuntimeException ignored) { /* unrecognized env.txt value: keep the last valid one */ }
        }
        runningFsr = fsr;
        runningMode = fsr ? 3 : m == 3 ? 0 : m;
        runningSharp = sh;
    }

    /** Applies to the next launch; game-specific settings override global defaults.
     * Existing user env.txt remains last and takes precedence. */
    static void env(Context c, String id, List<String> out) {
        int m = clamp(mode(c, id), 0, 3);
        out.add("DM_VK_PRESENT_FILTER=" + m);
        out.add("DM_VK_FSR=" + (m == 3 ? 1 : 0));
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
        int ts = timing(c, id);
        if (ts != 0) out.add("DM_NVN_GPU_TS=" + (ts == 1 ? "segment" : "submission"));
    }

    private static void live(Context c, int m, float sharp) {
        File dir = c.getExternalFilesDir(null);
        if (dir == null) return;
        try (FileWriter f = new FileWriter(new File(dir, "ctl.txt"), true)) {
            f.write("env DM_VK_PRESENT_FILTER=" + m + "\n");
            f.write("env DM_VK_FSR=" + (m == 3 ? 1 : 0) + "\n");
            f.write("env DM_VK_FSR_SHARP=" + sharp + "\n");
        } catch (IOException e) {
            Native.note("[RED] Graphics: live output setting unavailable (" + e.getMessage() + ")");
        }
    }

    static void setMode(Context c, String id, int value, boolean updateLive) {
        value = clamp(value, 0, 3);
        String key = id == null ? "present_filter" : Prefs.gameKey("present_filter", id);
        Prefs.of(c).edit().putInt(key, value).commit();
        if (updateLive && id != null) {
            runningMode = value;
            runningFsr = value == 3;
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
        for (String k : new String[] {"present_filter", "picture_stretch", "bg_pipelines", "gpu_timestamps", "fsr_sharp", "reg_dedup", "encoder_idle"})
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
            values = MODES; current = mode(c, id); title = "Filtro da tela (não reduz render)"; break;
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
        l.setText("Nitidez FSR (saída)");
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
        note.setText("Este filtro atua depois da cena já renderizada. Para ganhar FPS, reduza a Resolução interna da cena no launcher. Filtro e nitidez aplicam ao vivo.");
        note.setTextSize(12);
        box.addView(note);
    }
}
