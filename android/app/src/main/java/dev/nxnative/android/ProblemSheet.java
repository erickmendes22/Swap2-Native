package dev.nxnative.android;

import android.app.AlertDialog;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;

/**
 * A game that cannot start and that the one button cannot fix by itself (GameFlow's FIX: no profile, a pack that does not fit a folder that is no dump): one
 * sheet with what is wrong in one or two plain sentences, the one fix there is as its button, and "More options" for the game's Options. Never a dead end, never
 * a technical choice as the first thing asked. The check's own words (English) are under them, small and selectable, for a bug report.
 */
final class ProblemSheet {
    private ProblemSheet() {}

    static void show(MainActivity a, Game g, GameState s) { show(a, g, s.why, s.facts.dump, null); }

    /** why: what is wrong; dump: the game folder is a dump Prepare can start from; detail: the check's own sentence (null: none) */
    static void show(MainActivity a, Game g, GameFlow.Why why, boolean dump, String detail) {
        LauncherEffects.play(a, LauncherEffects.Cue.ERROR);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        String body = GameState.whyText(a, why, -1, -1, "", g.name);
        if (!dump && why != GameFlow.Why.NO_PROFILE) body = (body.isEmpty() ? "" : body + "\n\n") + a.getString(R.string.s2_why_not_dump);
        Ui.add(box, Ui.body(a, body), 0);
        AlertDialog[] d = new AlertDialog[1];
        File gd = new File(g.gameDir);
        if (why != GameFlow.Why.NO_PROFILE) {
            // the one fix: from the dump, Prepare; without one, a pack folder that fits (the one place this choice comes first)
            Button fix = dump ? Ui.button(a, a.getString(R.string.s2_prepare), Ui.Kind.PREPARE, v -> { d[0].dismiss(); Ondevice.prepare(a, gd, false); })
                    : Ui.button(a, a.getString(R.string.s2_pick_pack), Ui.Kind.PRIMARY, v -> { d[0].dismiss(); a.pickPackFor(gd, g.titleId); });
            Ui.add(box, fix, 16);
        }
        TextView more = Ui.text(a, a.getString(R.string.s2_more_options), 14, R.color.bn_banana, 600);
        more.setPadding(0, Ui.dp(a, 12), 0, Ui.dp(a, 12));
        more.setOnClickListener(v -> { d[0].dismiss(); a.manage(g); });
        Ui.add(box, more, 8);
        if (detail != null && !detail.isEmpty()) {
            TextView t = Ui.small(a, detail);
            t.setTextSize(12);
            t.setTextIsSelectable(true);
            Ui.add(box, t, 8);
        }
        d[0] = Ui.sheet(a, a.getString(R.string.s2_fix_title, g.name), box).setPositiveButton(android.R.string.ok, null).show();
    }
}
