package dev.nxnative.android;

import android.content.Context;

import java.util.Locale;

/**
 * A game card's one state (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow"): GameFlow's decision from the game's own job (the service's live state of it
 * when it is this game's, else its job.json as the card's check read it) and the card's pack facts, with everything the card shows from it: the one button's
 * label, icon and kind, the caption under the cover, the status line and its colour. Every text comes from the resources (English and Portuguese).
 */
final class GameState {
    final GameFlow.Action action;
    final GameFlow.Why why;
    final boolean auto;          // Play first rewrites the code (Ondevice.fixCodeThenPlay), then starts the game
    final PrepareState job;      // the game's job, null when it has none
    final PackFacts facts;
    final String name;
    final String game;           // its title ID: the code rewrite's time is each game's own (Job.rates)

    private GameState(GameFlow.Decision d, PrepareState job, PackFacts facts, String name, String game) {
        action = d.action;
        why = d.why;
        auto = d.auto;
        this.job = job;
        this.facts = facts;
        this.name = name;
        this.game = game;
    }

    /** live: the service's (or job.json's) state of the job the launcher follows (Ondevice.state), own: this game's job.json as its check read it */
    static GameState of(Game g, PrepareState live, PrepareState own, PackFacts facts) {
        PrepareState j = live != null && live.isFor(g.gameDir) ? live : own != null && own.isFor(g.gameDir) ? own : null;
        return new GameState(GameFlow.decide(j == null ? null : j.facts(), facts), j, facts, g.name, g.titleId);
    }

    /** The job is one that shows its share done (not finished) */
    boolean jobShown() { return job != null && job.phase != PrepareState.Phase.DONE && (action == GameFlow.Action.VIEW || action == GameFlow.Action.CONTINUE || action == GameFlow.Action.RETRY); }

    int labelRes() {
        switch (action) {
            case PLAY: return R.string.s2_play;
            case PREPARE: return R.string.s2_prepare;
            case CONTINUE: return R.string.s2_continue;
            case RETRY: return R.string.s2_prep_retry;
            case VIEW: return R.string.s2_prep_view;
            case FIX: return R.string.s2_fix;
            default: return R.string.s2_badge_checking;
        }
    }

    int iconRes() {
        switch (action) {
            case PLAY: case CONTINUE: return R.drawable.ic_play;
            case PREPARE: case VIEW: return R.drawable.ic_build;
            case RETRY: return R.drawable.s2_ic_retry;
            default: return R.drawable.s2_ic_info;
        }
    }

    Ui.Kind kind() {
        switch (action) {
            case PLAY: return Ui.Kind.PRIMARY;
            case PREPARE: case CONTINUE: case RETRY: return Ui.Kind.PREPARE;
            default: return Ui.Kind.TONAL;
        }
    }

    int color() {
        switch (action) {
            case PLAY: return why == GameFlow.Why.NONE || why == GameFlow.Why.SHADERS ? R.color.bn_leaf : R.color.s2_warning;
            case PREPARE: case CONTINUE: return R.color.s2_warning;
            case VIEW: return R.color.s2_prepare;
            case RETRY: case FIX: return R.color.s2_coral;
            default: return R.color.bn_text_2;
        }
    }

    /** The card's short state (its badge, and the caption under the cover with the share done of a job) */
    String badge(Context c) {
        switch (action) {
            case CHECKING: return c.getString(R.string.s2_badge_checking);
            case PLAY:
                switch (why) {
                    case MODS: return c.getString(R.string.s2_badge_mods);
                    case OTHER_TOOLS: return c.getString(R.string.s2_badge_other_device);
                    case BUILD: return c.getString(R.string.s2_badge_build);
                    default: return c.getString(R.string.s2_badge_ready);
                }
            case PREPARE: return c.getString(R.string.s2_badge_first_play);
            case VIEW: return c.getString(job != null && job.phase == PrepareState.Phase.PAUSED ? R.string.s2_prep_paused : R.string.s2_badge_busy);
            case CONTINUE: return c.getString(why == GameFlow.Why.INTERRUPTED ? R.string.s2_badge_interrupted : R.string.s2_prep_paused);
            case RETRY: return c.getString(R.string.s2_prep_failed);
            default: return c.getString(why == GameFlow.Why.NO_PROFILE ? R.string.s2_badge_unsupported : R.string.s2_badge_problem);
        }
    }

    /**
     * The caption under the cover: nothing for a game that plays (or is still checked), else its badge, with the share done of its job and its time left while it
     * runs, or a Prepare's expected time on this phone ("Prepares on first play · ~4 h 10 min")
     */
    String caption(Context c) {
        if (action == GameFlow.Action.CHECKING || action == GameFlow.Action.PLAY && (why == GameFlow.Why.NONE || why == GameFlow.Why.SHADERS)) return "";
        if (jobShown()) return badge(c) + " · " + pct() + (running() && job.remaining > 0 ? " · " + PrepareTime.approx(job.remaining) : "");
        long t = prepareSeconds(c);
        return action == GameFlow.Action.PREPARE && t > 0 ? badge(c) + " · " + PrepareTime.approx(t) : badge(c);
    }

    /** The job runs now (not paused, not stopped) */
    private boolean running() { return job != null && job.phase == PrepareState.Phase.RUNNING; }

    /** What a Prepare of the game would take on this phone now (PrepareTime.seconds from the card's facts and the phone's rates), -1 when its facts do not say */
    long prepareSeconds(Context c) {
        if (facts == null || facts.toTranslate < 0) return -1;
        return PrepareTime.seconds(Job.rates(c, game), facts.mapShaders, facts.toTranslate, facts.shaders, facts.rewrite);
    }

    String pct() { return job == null ? "" : String.format(Locale.getDefault(), "%d%%", (int) Math.floor(job.overall * 100)); }

    /** The selected game's status line: what happens now and why, in one sentence */
    String status(Context c) {
        switch (action) {
            case VIEW:
                // running: "Translating shaders · 41% · ~2 h 10 min left"
                if (job.phase == PrepareState.Phase.PAUSED) return badge(c) + " · " + pct() + " · " + Job.reasonText(c, job.reason);
                return job.remaining > 0 ? job.stepName + " · " + pct() + " · " + job.leftText(c) : badge(c) + " · " + pct() + " · " + job.stepName;
            case CONTINUE: case RETRY: {
                String w = pct() + " · " + whyText(c, why, job);
                return job != null && job.remaining > 0 ? w + " " + c.getString(R.string.s2_time_left_sentence, PrepareTime.text(job.remaining)) : w;
            }
            case PREPARE: {
                if (facts.shadersImported) return c.getString(R.string.s2_prep_shaders_imported);
                long t = prepareSeconds(c);
                if (t <= 0) return c.getString(why == GameFlow.Why.SHADERS ? R.string.s2_first_play_shaders : R.string.s2_first_play);
                return c.getString(why == GameFlow.Why.SHADERS ? R.string.s2_first_play_shaders_time : R.string.s2_first_play_time, PrepareTime.text(t));
            }
            case PLAY: case FIX: { String w = whyText(c, why, job); return w.isEmpty() ? badge(c) : w; }
            default: return badge(c);
        }
    }

    /** Why, as one plain sentence (the card's status, the problem sheet, the preparation screen); the job (may be null) gives a failure's numbers and step */
    static String whyText(Context c, GameFlow.Why w, PrepareState j) {
        return whyText(c, w, j == null ? -1 : j.free, j == null ? -1 : j.need, j == null ? "" : j.stepName, j == null ? "" : j.name);
    }

    static String whyText(Context c, GameFlow.Why w, Job j) {
        return whyText(c, w, j.errorArg("free"), j.errorArg("need"), j.stepName(c), j.name());
    }

    private static double gb(long b) { return b / 1073741824.0; }

    static String whyText(Context c, GameFlow.Why w, long free, long need, String step, String name) {
        switch (w) {
            case NO_SPACE: return free >= 0 && need > 0 ? c.getString(R.string.s2_why_nospace, gb(free), gb(need)) : c.getString(R.string.s2_why_nospace_plain);
            case TOOLS: return free >= 0 ? c.getString(R.string.s2_why_tools, gb(free)) : c.getString(R.string.s2_why_tools_plain);
            case KILLED: return c.getString(R.string.s2_why_killed_long);
            case REFUSED: return c.getString(R.string.s2_why_refused_long);
            case IO: return c.getString(R.string.s2_why_io, step);
            case STEP: return c.getString(R.string.s2_why_step, step);
            case DUMP: return c.getString(R.string.s2_why_dump);
            case IMPORTED_SHADERS: return c.getString(R.string.s2_why_imported_shaders);
            case UNREADABLE: return c.getString(R.string.s2_why_unreadable);
            case INTERRUPTED: return c.getString(R.string.s2_why_interrupted);
            case BATTERY: case THERMAL: case TIMEOUT: case USER: case APK:
                return c.getString(R.string.s2_why_paused, Job.reasonText(c, w == GameFlow.Why.BATTERY ? "battery" : w == GameFlow.Why.THERMAL ? "thermal"
                        : w == GameFlow.Why.TIMEOUT ? "timeout" : w == GameFlow.Why.APK ? "apk" : "user"));
            case MODS: return c.getString(R.string.s2_why_mods);
            case OTHER_TOOLS: return c.getString(R.string.s2_why_other_tools);
            case BUILD: return c.getString(R.string.s2_why_build);
            case NO_PACK: return c.getString(R.string.s2_why_no_pack);
            case UNFINISHED: return c.getString(R.string.s2_why_unfinished);
            case SHADERS: return c.getString(R.string.s2_why_shaders);
            case NO_PROFILE: return c.getString(R.string.s2_why_no_profile, name == null ? "" : name);
            case NOT_DUMP: return c.getString(R.string.s2_why_not_dump);
            case BUSY_IMPORT: return c.getString(R.string.s2_shaders_err_working, name == null ? "" : name);
            default: return "";
        }
    }

    /** A FIX state's sentence when the game folder is not a dump the app can prepare from (the sheet adds what it can do) */
    String fixText(Context c) {
        String w = whyText(c, why, job);
        if (facts.dump || why == GameFlow.Why.NO_PROFILE) return w;
        return w + "\n\n" + c.getString(R.string.s2_why_not_dump);
    }
}
