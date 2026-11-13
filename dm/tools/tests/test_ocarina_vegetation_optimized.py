"""Actual persistent defaults and launcher environment for the paired A/B."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"


class VegetationOptimization(unittest.TestCase):
    @unittest.skipUnless(shutil.which("java"), "JDK required")
    def test_setting_switches_only_plane_scatter_with_full_foliage_retained(self):
        prefs = (JAVA / "Prefs.java").read_text()
        methods = "\n".join(re.findall(r"    static (?:boolean|void) (?:fullVegetation|vegetationOptimized|vegetationContiguous|computeOptimized|fragmentOptimized)\([^\n]+", prefs))
        self.assertEqual(methods.count("static "), 10)
        activity = (JAVA / "GameActivity.java").read_text()
        env = "\n".join(re.findall(r'            if \(Prefs.OCARINA_TITLE.equals\(id\)\) env.add\("DM_VK_(?:VEGETATION|MEMU_PLANE_LUT|MEMU_COALESCED|OOT_CS_RETILE|OOT_FRAGMENT_AST)=[^\n]+', activity))
        self.assertEqual(env.count("env.add"), 5)
        settings = (JAVA / "GameSettings.java").read_text()
        self.assertIn(".toggle(a, Prefs.vegetationOptimized(a, id), (b, on) -> Prefs.vegetationOptimized(a, id, on))", settings)
        source = '''import java.util.*;
class Context {}
class Store {
  Map<String,Boolean> values = new HashMap<>();
  boolean getBoolean(String key, boolean fallback) { return values.getOrDefault(key, fallback); }
  Store edit() { return this; }
  Store putBoolean(String key, boolean value) { values.put(key, value); return this; }
  boolean commit() { return true; }
}
class Prefs {
  static final String OCARINA_TITLE = "0400486024DEC000";
  static Store store = new Store();
  static Store of(Context c) { return store; }
  static String gameKey(String k, String id) { return k + id; }
''' + methods + '''
}
public class Probe extends Context {
  List<String> env = new ArrayList<>();
  void environment(String id) { env.clear();
''' + env + '''
  }
  static void check(boolean b) { if (!b) throw new AssertionError("wrong launch environment"); }
  public static void main(String[] args) {
    Probe p = new Probe(); String id = Prefs.OCARINA_TITLE;
    p.environment(id);
    check(p.env.contains("DM_VK_VEGETATION=1") && p.env.contains("DM_VK_MEMU_PLANE_LUT=1"));
    check(p.env.contains("DM_VK_MEMU_COALESCED=0"));
    check(p.env.contains("DM_VK_OOT_CS_RETILE=1"));
    check(p.env.contains("DM_VK_OOT_FRAGMENT_AST=1"));
    Prefs.fragmentOptimized(p, id, false); p.environment(id);
    check(p.env.contains("DM_VK_OOT_FRAGMENT_AST=0") && p.env.contains("DM_VK_OOT_CS_RETILE=1") && p.env.contains("DM_VK_VEGETATION=1"));
    Prefs.fragmentOptimized(p, id, true); p.environment(id);
    check(p.env.contains("DM_VK_OOT_FRAGMENT_AST=1"));
    Prefs.computeOptimized(p, id, false); p.environment(id);
    check(p.env.contains("DM_VK_OOT_CS_RETILE=0") && p.env.contains("DM_VK_VEGETATION=1") && p.env.contains("DM_VK_MEMU_PLANE_LUT=1"));
    Prefs.computeOptimized(p, id, true); p.environment(id);
    check(p.env.contains("DM_VK_OOT_CS_RETILE=1"));
    Prefs.vegetationContiguous(p, id, true); p.environment(id);
    check(p.env.contains("DM_VK_MEMU_COALESCED=1") && p.env.contains("DM_VK_MEMU_PLANE_LUT=1") && p.env.contains("DM_VK_VEGETATION=1"));
    Prefs.vegetationContiguous(p, id, false);
    Prefs.vegetationOptimized(p, id, false); p.environment(id);
    check(p.env.contains("DM_VK_VEGETATION=1") && p.env.contains("DM_VK_MEMU_PLANE_LUT=0"));
    Prefs.fullVegetation(p, id, false); Prefs.vegetationOptimized(p, id, true); p.environment(id);
    check(p.env.contains("DM_VK_VEGETATION=0") && p.env.contains("DM_VK_MEMU_PLANE_LUT=1"));
    check(Prefs.vegetationOptimized(p, "another-title"));
    p.environment("another-title"); check(p.env.isEmpty());
  }
}
'''
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "Probe.java"; path.write_text(source)
            compiler = [shutil.which("javac")] if shutil.which("javac") else ["java", "com.sun.tools.javac.Main"]
            subprocess.run([*compiler, "-d", td, str(path)], check=True)
            subprocess.run(["java", "-cp", td, "Probe"], check=True)


if __name__ == "__main__":
    unittest.main()
