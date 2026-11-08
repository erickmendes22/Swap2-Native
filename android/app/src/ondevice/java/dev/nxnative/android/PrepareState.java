package dev.nxnative.android;

import android.content.Context;

import java.io.File;

/**
 * One snapshot of a game's job for the interface (docs/SWAP2-NATIVE-PREPARE-FLOW.md): the preparation screen (PrepareScreen, through PrepareActivity) and the
 * game's card (MainActivity, through Ondevice.listen and GameState). Made from the job (Job) and whether the service runs it; immutable, so the interface may keep
 * it. Its texts are in the interface's language (the Context's resources); the job's own detail (error) stays as the job wrote it, for Details and the logs.
 */
final class PrepareState {
    enum Phase { PENDING, RUNNING, PAUSED, FAILED, DONE }

    final String titleId, name;
    final long version;
    final File dump;          // the game's folder or .nup: Game.gameDir of its card
    final File file;          // the job's job.json
    final Phase phase;
    final String state, reason, errorCode, error;   // job.json's own words (GameFlow.JobFacts)
    final boolean alive;      // the service's worker runs it now
    final GameFlow.Why why;   // why it stopped (failed: its code; paused: its reason), NONE while it runs
    final long free, need;    // a failure's numbers (nospace, tools), -1 when it has none
    final boolean codeOnly;   // the short job: only the code is rewritten (Job.codeOnly)
    final int step, steps;    // the current step, 1-based, of Job.STEPS.length
    final String stepName;    // that step in words (Job.STEP_RES)
    final String status;      // the job's sentence (Job.statusText): the step and its count, why it paused, or why it stopped and what to do
    final double overall;     // 0..1
    final long shadersDone, shadersTotal;   // total 0: not counted yet
    /** The job's seconds left on this phone (Job.remaining: the current step at its measured rate, the rest at the phone's rates), -1 when done */
    final long remaining;
    final boolean canPause, canResume, canPlay;
    /** Stopped (failed or paused) at the split or the translation: Import shaders… is offered, after which Resume skips those steps (Job.shadersInPack) */
    final boolean canImportShaders;
    /** The job took its shaders from the pack (Import shaders…): none translated */
    final boolean shadersImported;
    /** The service could not write job.json (PackService's saveError: most likely a full disk) */
    final boolean saveFailed;

    private PrepareState(Context c, Job j, boolean alive, boolean ready, boolean saveFailed) {
        titleId = j.titleId();
        name = j.name().isEmpty() ? j.titleId() : j.name();
        version = j.version();
        dump = j.dump();
        file = j.file;
        String s = j.state();
        state = s;
        reason = j.reason();
        errorCode = j.errorCode();
        error = j.error();
        this.alive = alive;
        boolean running = alive && ("running".equals(s) || "pending".equals(s) || "paused".equals(s) && !"user".equals(j.reason()) && !"timeout".equals(j.reason()));
        phase = "done".equals(s) ? Phase.DONE : "failed".equals(s) ? Phase.FAILED : "pending".equals(s) && !alive ? Phase.PENDING
                : running && !"paused".equals(s) ? Phase.RUNNING : Phase.PAUSED;
        why = "failed".equals(s) ? GameFlow.failWhy(errorCode, error) : "paused".equals(s) ? GameFlow.reasonWhy(reason)
                : ("running".equals(s) || "pending".equals(s)) && !alive ? GameFlow.Why.INTERRUPTED : GameFlow.Why.NONE;
        free = j.errorArg("free");
        need = j.errorArg("need");
        codeOnly = j.codeOnly();
        int i = j.current();
        step = i + 1;
        steps = Job.STEPS.length;
        stepName = j.stepName(c);
        status = j.statusText(c, alive);
        overall = Math.max(0, Math.min(1, j.overall()));
        long t = Math.max(0, j.shadersTotal());
        shadersTotal = t;
        shadersDone = Math.max(0, Math.min(j.shadersDone(), t));
        remaining = "done".equals(s) ? -1 : j.remaining(Job.rates(c, j.titleId()), System.currentTimeMillis());
        canPause = running;
        canResume = !running && !"done".equals(s) || "done".equals(s) && j.apkChanged();
        canPlay = ready && !running;
        canImportShaders = !running && (phase == Phase.FAILED || phase == Phase.PAUSED) && (i == 2 || i == Job.SHADERS);
        shadersImported = j.shadersImported();
        this.saveFailed = saveFailed;
    }

    /** The state of a job: alive = the service runs it now; ready = its pack and shader library are complete for this APK (Ondevice's ready) */
    static PrepareState of(Context c, Job j, boolean alive, boolean ready) { return new PrepareState(c, j, alive, ready, false); }

    static PrepareState of(Context c, Job j, boolean alive, boolean ready, boolean saveFailed) { return new PrepareState(c, j, alive, ready, saveFailed); }

    /** "~2 h 10 min left" in the interface's language, "" when nothing is left to say */
    String leftText(Context c) { return remaining > 0 ? c.getString(R.string.s2_time_left, PrepareTime.approx(remaining)) : ""; }

    /** Whether this is the job of a game (its card): the same game folder or .nup */
    boolean isFor(String gameDir) { return dump.getPath().equals(gameDir); }

    /** GameFlow's view of it */
    GameFlow.JobFacts facts() {
        GameFlow.JobFacts f = new GameFlow.JobFacts();
        f.state = state;
        f.reason = reason;
        f.errorCode = errorCode;
        f.error = error;
        f.alive = alive;
        f.ready = canPlay;
        return f;
    }
}
