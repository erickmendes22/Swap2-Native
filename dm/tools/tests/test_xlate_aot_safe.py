"""The translator front end (dm/gfx/tools/dmsh_xlate/Program.cs) is compiled twice: for .NET (dmsh_xlate.csproj, the Mac's and the PC's dmsh_xlate_bin) and with NativeAOT
(dmsh_xlate_android.csproj, the phone's libdmsh_xlate.so). A call that needs the reflection-based serializer (RequiresUnreferencedCode / RequiresDynamicCode) works under the
JIT and throws under NativeAOT: JsonArray.Add<int> failed every shader with a 1D fetch on the phone (docs/reference/packing.md, "The phone's translator fails every shader
with a 1D fetch"). Both projects make the trim and AOT analyzers' warnings IL2026 / IL3050 errors, so neither builds such a call. Reads the project files only: no .NET needed."""
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'dm/gfx/tools/dmsh_xlate/dmsh_xlate.csproj'
ANDROID = REPO / 'dm/gfx/tools/dmsh_xlate_android/dmsh_xlate_android.csproj'


def errors(text):
    """The warning codes a project file makes errors"""
    return {c.strip() for m in re.findall(r'<WarningsAsErrors>(.*?)</WarningsAsErrors>', text) for c in m.split(';')}


class AotSafe(unittest.TestCase):
    def test_both_refuse_reflection_calls(self):
        for p in (DESKTOP, ANDROID):
            with self.subTest(project=p.name):
                self.assertLessEqual({'IL2026', 'IL3050'}, errors(p.read_text(encoding='utf-8')))

    def test_desktop_runs_the_analyzers(self):   # NativeAOT (PublishAot) turns them on by itself; the .NET build needs them asked for
        t = DESKTOP.read_text(encoding='utf-8')
        self.assertIn('<EnableTrimAnalyzer>true</EnableTrimAnalyzer>', t)
        self.assertIn('<EnableAotAnalyzer>true</EnableAotAnalyzer>', t)
        self.assertIn('<PublishAot>true</PublishAot>', ANDROID.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
