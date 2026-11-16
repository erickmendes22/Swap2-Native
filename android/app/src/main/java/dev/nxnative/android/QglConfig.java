package dev.nxnative.android;

import android.app.AlertDialog;
import android.content.Context;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;

/**
 * Opt-in per-game overrides for Qualcomm proprietary Vulkan's qgl_config.txt.
 * The system/vendor configuration is NEVER modified. A driver-side fopen hook
 * redirects ONLY qgl_config.txt to the per-game file in this app's private data.
 * The driver may ignore these undocumented settings (particularly on new GPUs).
 */
final class QglConfig {
    private QglConfig() {}
    private static final String TAG = "Swap2QGL";
    private static final String[] MODES = {
            "Automático (driver)", "0 · Sysmem sem binning",
            "1 · GMEM com binning", "2 · GMEM sem binning",
            "3 · Sysmem com binning"
    };
    private static final String[] BOOLS = {
            "Automático (driver)", "Forçar desligado (0)", "Forçar ligado (1)"
    };
    private static String key(String name, String id) { return Prefs.gameKey(name, id); }
    /** -1: absent / unchanged, 0..3: explicit driver's render mode. */
    static int renderMode(Context c, String id) {
        int v = Prefs.of(c).getInt(key("qgl_render_mode", id), -1);
        return v < -1 || v > 3 ? -1 : v;
    }
    /** -1: absent, 0: off, 1: on. */
    private static int bool(Context c, String id, String name) {
        int v = Prefs.of(c).getInt(key(name, id), -1);
        return v < -1 || v > 1 ? -1 : v;
    }
    static String summary(Context c, String id) {
        int r = renderMode(c, id);
        int load = bool(c, id, "qgl_force_load");
        int store = bool(c, id, "qgl_force_store");
        if (r < 0 && load < 0 && store < 0) return "Padrão Qualcomm (sem intervenção)";
        return (r < 0 ? "Render automático" : MODES[r + 1])
                + (load < 0 ? "" : " · Load " + load)
                + (store < 0 ? "" : " · Store " + store);
    }
    private static void select(MainActivity a, String id, int field, Runnable refresh) {
        String pref = field == 0 ? "qgl_render_mode" :
                field == 1 ? "qgl_force_load" : "qgl_force_store";
        String[] labels = field == 0 ? MODES : BOOLS;
        int current = field == 0 ? renderMode(a, id) : bool(a, id, pref);
        new AlertDialog.Builder(a)
                .setTitle(field == 0 ? "Qualcomm · Render mode" :
                        field == 1 ? "Qualcomm · Forçar GMEM load" : "Qualcomm · Forçar GMEM store")
                .setSingleChoiceItems(labels, current + 1, (d, choice) -> {
                    int v = choice - 1;
                    if (v == -1) Prefs.of(a).edit().remove(key(pref, id)).commit();
                    else Prefs.of(a).edit().putInt(key(pref, id), v).commit();
                    d.dismiss();
                    refresh.run();
                })
                .setNegativeButton(android.R.string.cancel, null).show();
    }
    static void dialog(MainActivity a, String id, Runnable refresh) {
        int r = renderMode(a, id);
        int l = bool(a, id, "qgl_force_load"), s = bool(a, id, "qgl_force_store");
        String[] options = {
                "Render mode: " + MODES[r + 1],
                "Force GMEM load: " + BOOLS[l + 1],
                "Force GMEM store: " + BOOLS[s + 1],
                "ℹ Como funciona / compatibilidade"
        };
        // Android AlertController gives setMessage priority over setItems.
        // Keep the list visible; place the explanation in a separate item.
        new AlertDialog.Builder(a).setTitle("Qualcomm · qgl_config.txt")
                .setItems(options, (d, which) -> {
                    if (which < 3) {
                        select(a, id, which, refresh);
                    } else {
                        new AlertDialog.Builder(a)
                                .setTitle("Qualcomm · qgl_config.txt")
                                .setMessage("Configurações experimentais do driver proprietário. "
                                        + "Sem alteração no sistema ou necessidade de root. "
                                        + "Reinicie o jogo. O driver pode ignorar os parâmetros; "
                                        + "Turnip/Mesa não utiliza esse mecanismo.")
                                .setPositiveButton("Voltar às opções",
                                        (x, w) -> dialog(a, id, refresh))
                                .setNegativeButton("Fechar", null).show();
                    }
                })
                .setNegativeButton("Fechar", null).show();
    }
    static void reset(Context c, String id) {
        Prefs.of(c).edit()
                .remove(key("qgl_render_mode", id))
                .remove(key("qgl_force_load", id))
                .remove(key("qgl_force_store", id)).commit();
    }
    /** Only set the host redirect after BOTH expected vendor paths are writable. */
    static void env(Context c, String id, List<String> out) {
        int r = renderMode(c, id), load = bool(c, id, "qgl_force_load"),
                store = bool(c, id, "qgl_force_store");
        if (r < 0 && load < 0 && store < 0) return;
        GpuDriver.Info driver = GpuDriver.selected(c, id);
        if (driver != null) {
            String metadata = (driver.name + " " + driver.vendor + " " + driver.library)
                    .toLowerCase(Locale.ROOT);
            if (metadata.contains("turnip") || metadata.contains("mesa") ||
                    metadata.contains("freedreno") || metadata.contains("panvk")) {
                Log.w(TAG, "qgl override ignored for open-source GPU driver: " + driver.name);
                return;
            }
        }
        StringBuilder b = new StringBuilder("0x0=0x8675309\n");
        if (r >= 0) b.append("rendermode=").append(r).append('\n');
        if (load >= 0) b.append("forcegmemload=").append(load).append('\n');
        if (store >= 0) b.append("forcegmemstore=").append(store).append('\n');
        File root = new File(c.getFilesDir(), "qgl_override/" + id);
        byte[] payload = b.toString().getBytes(StandardCharsets.US_ASCII);
        try {
            for (String path : new String[]{"data/vendor/gpu", "data/misc/gpu"}) {
                File dir = new File(root, path);
                if (!dir.isDirectory() && !dir.mkdirs())
                    throw new IOException("Could not create " + dir);
                try (FileOutputStream output = new FileOutputStream(new File(dir, "qgl_config.txt"))) {
                    output.write(payload);
                    output.getFD().sync();
                }
            }
            out.add("DM_QGL_REDIRECT=" + root.getAbsolutePath());
            Log.i(TAG, "qgl per-game override prepared; render mode=" + r +
                    " load=" + load + " store=" + store + "; driver support unverified");
        } catch (IOException e) {
            // The game must never fail to boot just because an optional QGL test failed.
            Log.w(TAG, "qgl override preparation failed; using unmodified driver", e);
        }
    }
}
