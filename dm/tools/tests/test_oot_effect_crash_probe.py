"""Ensure game-owned NUP crash investigation is bounded and never edits ROMFS."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oot_effect_crash_probe as probe


class OotEffectCrashProbeTests(unittest.TestCase):
    def test_active_nup_update_exefs_derived_not_base_game(self):
        root = '/sdcard/Ocarina.nup:update/131072/romfs'
        self.assertEqual(probe.original_exefs(root),
                         '/sdcard/Ocarina.nup:update/131072/exefs/main')
        self.assertEqual(probe.original_exefs('/game/update/romfs'),
                         '/game/update/exefs/main')
        with self.assertRaises(ValueError):
            probe.original_exefs('/game/unknown-file')

    def test_exact_update_build_id_required(self):
        good = SimpleNamespace(build_id=bytes.fromhex('e0f3ccfa') + bytes(28),
                               text_end=0x5140000)
        self.assertTrue(probe.validate_module(good).startswith('e0f3ccfa'))
        wrong = SimpleNamespace(build_id=bytes.fromhex('deadbeef') + bytes(28),
                                text_end=0x5140000)
        with self.assertRaises(ValueError):
            probe.validate_module(wrong)
        short = SimpleNamespace(build_id=good.build_id, text_end=0x1000)
        with self.assertRaises(ValueError):
            probe.validate_module(short)

    def test_crash_sites_match_user_logs(self):
        self.assertEqual(probe.SITES[0][0], 0x47a924)
        self.assertEqual(probe.SITES[1][0], 0xdbea1c)
        self.assertTrue(all(pc % 4 == 0 for pc, _ in probe.SITES))


if __name__ == '__main__':
    unittest.main()
