"""JVM contract checks for opt-in Qualcomm QGL config without an Android device."""
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
QGL = ROOT / "android/app/src/main/java/dev/nxnative/android/QglConfig.java"
DRIVER = ROOT / "dm/gfx/vk_android/vka_driver.c"
HOOK = ROOT / "dm/third_party/libadrenotools/src/hook/hook_impl.cpp"


class QualcommQglConfigTest(unittest.TestCase):
    def test_vulkan_fallback_and_narrow_hook(self):
        d = DRIVER.read_text()
        h = HOOK.read_text()
        self.assertEqual(d.count("#if defined(__ANDROID__)"), 1)
        self.assertTrue(d.rstrip().endswith("#endif // __ANDROID__"))
        self.assertIn('if (!custom && !qgl) return NULL;', d)
        self.assertIn('DM_QGL_REDIRECT', d)
        self.assertIn('"/data/vendor/gpu/qgl_config.txt"', h)
        self.assertIn('"/data/misc/gpu/qgl_config.txt"', h)
        self.assertIn("return fopen(filename, mode);", h)
        self.assertIn("ADRENOTOOLS_DRIVER_FILE_REDIRECT", h)

    def test_java_launch_contract(self):
        game = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameActivity.java").read_text()
        settings = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameSettings.java").read_text()
        cmake = (ROOT / "android/host/CMakeLists.txt").read_text()
        gradle = (ROOT / "android/app/build.gradle").read_text()
        # QGL remains a dormant standalone compatibility helper, but no
        # game startup can inject driver-wide GMEM/Sysmem overrides.
        self.assertNotIn('QglConfig.env(this, id, env);', game)
        self.assertIn('QglConfig.reset(a, id);', settings)
        self.assertNotIn('QglConfig.dialog(a, id, again)', settings)
        self.assertIn('add_library(file_redirect_hook SHARED', cmake)
        self.assertIn("'file_redirect_hook'", gradle)

    def test_compile_and_execute_actual_java_config(self):
        sources = {
            "android/content/Context.java": """
package android.content;
import java.io.File;
public class Context {
    public File getFilesDir() { return new File(System.getProperty("qgl.test.root")); }
}
""",
            "android/content/SharedPreferences.java": """
package android.content;
import java.util.HashMap;
import java.util.Map;
public class SharedPreferences {
    private final Map<String,Integer> settings = new HashMap<>();
    public int getInt(String key, int defaultValue) { return settings.getOrDefault(key, defaultValue); }
    public Editor edit() { return new Editor(); }
    public class Editor {
        public Editor putInt(String key, int value) { settings.put(key,value); return this; }
        public Editor remove(String key) { settings.remove(key); return this; }
        public boolean commit() { return true; }
    }
}
""",
            "android/content/DialogInterface.java": """
package android.content;
public interface DialogInterface {
    void dismiss();
    interface OnClickListener { void onClick(DialogInterface dialog, int which); }
}
""",
            "android/app/AlertDialog.java": """
package android.app;
import android.content.Context;
import android.content.DialogInterface;
public class AlertDialog {
    public static int lastListLength = 0, mixedMessageList = 0;
    public static DialogInterface.OnClickListener lastItemsCallback, lastChoiceCallback;
    public static class Builder {
        private boolean hasMessage, hasList;
        private int listLength;
        public Builder(Context ctx) {}
        public Builder setTitle(String t) { return this; }
        public Builder setMessage(String t) { hasMessage = true; return this; }
        public Builder setSingleChoiceItems(String[] v,int current,DialogInterface.OnClickListener cb) {
            hasList = true; listLength = v.length; lastChoiceCallback = cb; return this;
        }
        public Builder setItems(String[] v,DialogInterface.OnClickListener cb) {
            hasList = true; listLength = v.length; lastItemsCallback = cb; return this;
        }
        public Builder setPositiveButton(String v,DialogInterface.OnClickListener cb) { return this; }
        public Builder setNegativeButton(int v,DialogInterface.OnClickListener cb) { return this; }
        public Builder setNegativeButton(String v,DialogInterface.OnClickListener cb) { return this; }
        public AlertDialog show() {
            if (hasMessage && hasList) mixedMessageList++;
            if (hasList) lastListLength = listLength;
            return new AlertDialog();
        }
    }
}
""",
            "android/R.java": """
package android;
public final class R { public static final class string { public static final int cancel = 0; } }
""",
            "android/util/Log.java": """
package android.util;
public class Log {
    public static int i(String tag,String s) { return 0; }
    public static int w(String tag,String s) { return 0; }
    public static int w(String tag,String s,Throwable t) { return 0; }
}
""",
            "dev/nxnative/android/MainActivity.java": """
package dev.nxnative.android;
public class MainActivity extends android.content.Context {}
""",
            "dev/nxnative/android/Prefs.java": """
package dev.nxnative.android;
public class Prefs {
    private static final android.content.SharedPreferences instance = new android.content.SharedPreferences();
    static android.content.SharedPreferences of(android.content.Context c) { return instance; }
    static String gameKey(String name, String id) { return name+"@"+id; }
}
""",
            "dev/nxnative/android/GpuDriver.java": """
package dev.nxnative.android;
public class GpuDriver {
    public static Info mock;
    static Info selected(android.content.Context c,String id) { return mock; }
    static final class Info {
        final String name,vendor,library;
        Info(String n,String v,String l) { name=n; vendor=v; library=l; }
    }
}
""",
            "dev/nxnative/android/QglSmoke.java": """
package dev.nxnative.android;
import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
public class QglSmoke {
    static void check(boolean yes, String s) { if (!yes) throw new AssertionError(s); }
    static void choice(MainActivity c, String name, int val) {
        Prefs.of(c).edit().putInt(Prefs.gameKey(name,"OCARINA"),val).commit();
    }
    public static void main(String[] args) throws Exception {
        MainActivity c = new MainActivity();
        QglConfig.dialog(c, "OCARINA", () -> {});
        check(android.app.AlertDialog.lastListLength == 4, "GMEM/Sysmem menu has no selectable rows");
        check(android.app.AlertDialog.mixedMessageList == 0, "message hides QGL menu items");
        // Select main menu item 0, then choose index 2 = rendermode 1 (GMEM+binning).
        android.app.AlertDialog.lastItemsCallback.onClick(null, 0);
        check(android.app.AlertDialog.lastListLength == 5, "render mode picker missing");
        android.app.AlertDialog.lastChoiceCallback.onClick(new android.content.DialogInterface() {
            public void dismiss() {}
        }, 2);
        check(QglConfig.renderMode(c, "OCARINA") == 1, "selected GMEM mode not stored");
        QglConfig.reset(c, "OCARINA");
        ArrayList<String> env = new ArrayList<>();
        check(QglConfig.renderMode(c, "OCARINA") == -1, "default render mode");
        QglConfig.env(c, "OCARINA", env);
        check(env.isEmpty(), "defaults must not hook system Vulkan");
        choice(c, "qgl_render_mode", 0);
        choice(c, "qgl_force_load", 1);
        choice(c, "qgl_force_store", 0);
        QglConfig.env(c, "OCARINA", env);
        check(env.size() == 1 && env.get(0).startsWith("DM_QGL_REDIRECT="), "redirect absent");
        File folder = new File(env.get(0).substring("DM_QGL_REDIRECT=".length()));
        for (String f : new String[] {"data/vendor/gpu/qgl_config.txt","data/misc/gpu/qgl_config.txt"}) {
            File target = new File(folder, f);
            check(target.isFile(), "QGL file missing: "+f);
            String txt = Files.readString(target.toPath(), StandardCharsets.US_ASCII);
            check(txt.equals("0x0=0x8675309\\nrendermode=0\\nforcegmemload=1\\nforcegmemstore=0\\n"),
                  "Unexpected driver config: "+txt);
        }
        QglConfig.reset(c,"OCARINA");
        check(QglConfig.renderMode(c,"OCARINA") == -1, "reset failed");
        env.clear();
        QglConfig.env(c,"OCARINA",env);
        check(env.isEmpty(), "reset must restore untouched loader");
        GpuDriver.mock = new GpuDriver.Info("Mesa Turnip","Mesa","libvulkan_freedreno.so");
        choice(c, "qgl_render_mode", 1);
        QglConfig.env(c,"OCARINA",env);
        check(env.isEmpty(), "Turnip must not get Qualcomm override");
        System.out.println("PASS: QGL default, GMEM/Sysmem file paths, overrides, reset, Turnip safety");
    }
}
"""
        }
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            compiled = []
            for rel, source in sources.items():
                dest = base / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(textwrap.dedent(source).lstrip())
                compiled.append(str(dest))
            classes = base / "classes"
            classes.mkdir()
            subprocess.run(["javac", "-d", str(classes), str(QGL), *compiled], check=True)
            proc = subprocess.run(
                ["java", "-Dqgl.test.root=" + str(base / "data"),
                 "-cp", str(classes), "dev.nxnative.android.QglSmoke"],
                check=True, capture_output=True, text=True
            )
            self.assertIn("PASS: QGL default", proc.stdout)


if __name__ == "__main__":
    unittest.main()
