package dev.nxnative.android;

import java.util.Locale;

/**
 * The one-button game flow (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow"), as pure logic: what a game's card shows and does, decided once from the
 * game's own job (its job.json, or the service's live state of it) and what the card's check found in its pack (PackFacts). The label, the caption, the status
 * line and the click all come from this one decision (GameState), so the card can no longer show a running preparation with a "Needs attention" button.
 * No Android classes: dm/tools/tests/test_android_game_flow.py runs it on the JVM (GameFlowJvmTest).
 */
final class GameFlow {
    /** The card's one action */
    enum Action { CHECKING, PLAY, PREPARE, CONTINUE, RETRY, VIEW, FIX }

    /** Why the card shows what it shows (its caption and status sentence; for a failed job, the job's errorCode) */
    enum Why {
        NONE, NO_PACK, UNFINISHED, MODS, BUILD, OTHER_TOOLS, SHADERS, NO_PROFILE, NOT_DUMP, NO_SPACE, TOOLS, KILLED, REFUSED, BATTERY, THERMAL, TIMEOUT, USER,
        APK, INTERRUPTED, IO, STEP, DUMP, IMPORTED_SHADERS, UNREADABLE, BUSY_IMPORT
    }

    /** The job's failure codes in job.json ("errorCode"; Job.fail) */
    static final String NOSPACE = "nospace", TOOLS = "tools", KILLED = "killed", REFUSED = "refused", IO = "io", STEP = "step", DUMP = "dump",
            IMPORTED_SHADERS = "imported_shaders", UNREADABLE = "unreadable";

    /** What the game's own job says (null fields: no job) */
    static final class JobFacts {
        String state = "";      // pending, running, paused, failed, done ("" : no job)
        String reason = "";     // why paused
        String errorCode = "";  // why failed (a code), "" for an older job.json
        String error = "";      // the failure's detail (English, for the logs and Details)
        boolean alive;          // the service's worker runs it now
        boolean ready;          // done, and its pack and library are complete for this APK (Ondevice.ready)
        boolean exists() { return !state.isEmpty(); }
    }

    static final class Decision {
        final Action action;
        final Why why;
        final boolean auto;   // Play first rewrites the code (a short job, no question), then starts the game

        Decision(Action action, Why why, boolean auto) { this.action = action; this.why = why; this.auto = auto; }

        @Override public String toString() { return action + " " + why + (auto ? " auto" : ""); }
    }

    private GameFlow() {}

    private static Decision d(Action a, Why w) { return new Decision(a, w, false); }

    /** The card's decision; the first row that matches wins (the table in docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow") */
    static Decision decide(JobFacts j, PackFacts f) {
        if (!f.profile) return d(Action.FIX, Why.NO_PROFILE);
        if (j != null && j.exists()) {
            switch (j.state) {
                case "running": return j.alive ? d(Action.VIEW, Why.NONE) : d(Action.CONTINUE, Why.INTERRUPTED);
                case "pending": return j.alive ? d(Action.VIEW, Why.NONE) : d(Action.CONTINUE, Why.INTERRUPTED);
                case "paused": {
                    Why w = reasonWhy(j.reason);
                    // the policy's pause (battery, heat) with the worker alive goes on by itself: the screen says why
                    return j.alive ? d(Action.VIEW, w) : d(Action.CONTINUE, w);
                }
                case "failed": return d(Action.RETRY, failWhy(j.errorCode, j.error));
                default:
                    // done: the pack decides (a done job whose pack no longer fits is a new preparation). A finished job's pack plays before the card's check has
                    // seen it, unless that check found what the job cannot have fixed (the mods or the dump changed since)
                    if (j.ready && !(f.checked && (f.mods || f.build))) return d(Action.PLAY, Why.NONE);
                    break;
            }
        }
        if (!f.checked) return d(Action.CHECKING, Why.NONE);
        if (!f.pack || f.unfinished) {
            Why w = f.pack ? Why.UNFINISHED : Why.NO_PACK;
            return f.dump ? d(Action.PREPARE, w) : d(Action.FIX, w);
        }
        // Code that other tools made (a pack from another device or an older rewriter) still runs: it plays as it is, never rewritten in place without a question
        // (a kill or a full disk during that rewrite would leave a pack that played with an unfinished module); Prepare again under Advanced redoes it
        // (the shaders below decide it, as for code whose maker cannot be told)
        Why code = f.build ? Why.BUILD : f.mods ? Why.MODS : Why.NONE;
        // the code does not fit: the dump remakes it on the phone, in a short job Play runs by itself, only when the pack's current shader library is kept as it is.
        // A pack whose library must be made too (none, or only an older one) is a real preparation the user starts: the short job never translates shaders
        if (code != Why.NONE) {
            if (!f.dump) return d(Action.FIX, code);
            if (f.shadersMissing && !f.playable) return d(Action.PREPARE, code);
            return new Decision(Action.PLAY, code, true);
        }
        if (f.shadersMissing) {
            if (f.playable) return d(Action.PLAY, Why.NONE); // same ABI: no mandatory shader update
            if (f.legacy) return d(Action.PLAY, Why.SHADERS); // no ABI: warn, optional shader translation
            return f.dump ? d(Action.PREPARE, Why.SHADERS) : d(Action.FIX, Why.SHADERS);
        }
        return d(Action.PLAY, Why.NONE);
    }

    /** A paused job's reason as a Why */
    static Why reasonWhy(String r) {
        switch (r == null ? "" : r) {
            case "battery": return Why.BATTERY;
            case "thermal": return Why.THERMAL;
            case "timeout": return Why.TIMEOUT;
            case "refused": return Why.REFUSED;
            case "killed": return Why.KILLED;
            case "apk": return Why.APK;
            case "user": return Why.USER;
            default: return Why.USER;
        }
    }

    /** A failed job's code as a Why; an older job.json (no code) is read from its detail: a full disk is said as one */
    static Why failWhy(String code, String detail) {
        String c = code == null || code.isEmpty() ? codeOfDetail(detail) : code;
        switch (c) {
            case NOSPACE: return Why.NO_SPACE;
            case TOOLS: return Why.TOOLS;
            case KILLED: return Why.KILLED;
            case REFUSED: return Why.REFUSED;
            case IO: return Why.IO;
            case DUMP: return Why.DUMP;
            case IMPORTED_SHADERS: return Why.IMPORTED_SHADERS;
            case UNREADABLE: return Why.UNREADABLE;
            default: return Why.STEP;
        }
    }

    /** The code of a failure's text when the job wrote none (job.json of an older APK) */
    static String codeOfDetail(String detail) {
        String d = detail == null ? "" : detail;
        if (noSpace(d)) return NOSPACE;
        if (d.contains("was stopped by Android")) return KILLED;
        if (d.contains("the packer did not start")) return TOOLS;
        if (d.startsWith("java.io.") || d.contains("IOException")) return IO;
        return STEP;
    }

    static boolean noSpace(String s) {
        return s != null && (s.contains("ENOSPC") || s.contains("No space left") || s.contains("no space left"));
    }

    /** The code of an exception that ended the worker (PackService.work): a full disk, the tools that did not start, else a file error */
    static String failCode(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t.getClass().getSimpleName().equals("NoSpace") || noSpace(String.valueOf(t.getMessage()))) return NOSPACE;
            if (t.getClass().getSimpleName().equals("ToolsFailed")) return TOOLS;
        }
        return IO;
    }

    /**
     * job.json as read (Job.read): a job that is not running has no running step. A worker that died between marking a step running and its end (a kill, a full
     * disk that also failed the save) left one: it goes back to pending, so the card and the import checks no longer take the job for a rewrite in progress
     */
    static String[] normalizeSteps(String state, String[] steps) {
        String[] out = steps.clone();
        if ("running".equals(state)) return out;
        for (int i = 0; i < out.length; i++) if ("running".equals(out[i])) out[i] = "pending";
        return out;
    }

    /** Whether free bytes hold need bytes (with the margin the tools' unpack keeps) */
    static boolean fits(long free, long need) { return need <= 0 || free >= need; }

    /** GB with one decimal, for the logs */
    static String gb(long b) { return String.format(Locale.ROOT, "%.1f GB", b / 1073741824.0); }
}
