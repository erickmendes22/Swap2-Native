package dev.nxnative.android;

import java.io.IOException;
import java.util.Arrays;

/**
 * GameFlow on the JVM, driven by dm/tools/tests/test_android_game_flow.py: the card's decision table (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow"),
 * job.json's normalization and the failure codes. Prints "ok &lt;cases&gt;", or the first case that fails and exits 1.
 */
public final class GameFlowJvmTest {
    private static int n;

    /** As PackEngine.NoSpace / ToolsFailed (GameFlow.failCode knows them by name: no Android classes here) */
    static final class NoSpace extends IOException { private static final long serialVersionUID = 1; NoSpace() { super("No space left for the preparation tools"); } }
    static final class ToolsFailed extends IOException { private static final long serialVersionUID = 1; ToolsFailed() { super("the packer did not unpack"); } }

    private static void eq(String what, Object want, Object have) {
        n++;
        if (!String.valueOf(want).equals(String.valueOf(have))) {
            System.out.println("FAIL " + what + ": want " + want + ", have " + have);
            System.exit(1);
        }
    }

    private static GameFlow.JobFacts job(String state, String reason, String code, String error, boolean alive, boolean ready) {
        GameFlow.JobFacts j = new GameFlow.JobFacts();
        j.state = state;
        j.reason = reason;
        j.errorCode = code;
        j.error = error;
        j.alive = alive;
        j.ready = ready;
        return j;
    }

    /** A checked card of a dump whose pack fits */
    private static PackFacts fits() {
        PackFacts f = new PackFacts();
        f.checked = true;
        f.dump = true;
        f.pack = true;
        f.code = Boolean.TRUE;
        return f;
    }

    public static void main(String[] a) {
        // The friend's phone (2026-11-08): a job that failed on a full disk while its rewrite was marked running (an APK before error codes)
        String[] steps = {"done", "running", "pending", "pending", "pending"};
        eq("normalize failed", "[done, pending, pending, pending, pending]", Arrays.toString(GameFlow.normalizeSteps("failed", steps)));
        eq("normalize paused", "[done, pending, pending, pending, pending]", Arrays.toString(GameFlow.normalizeSteps("paused", steps)));
        eq("normalize running", Arrays.toString(steps), Arrays.toString(GameFlow.normalizeSteps("running", steps)));
        eq("normalize keeps input", "running", steps[1]);
        eq("friend: failed ENOSPC", "RETRY NO_SPACE", GameFlow.decide(job("failed", "", "", "java.io.IOException: write failed: ENOSPC (No space left on device)", false, false), fits()));
        eq("failed with code", "RETRY NO_SPACE", GameFlow.decide(job("failed", "", "nospace", "", false, false), fits()));
        eq("failed tools", "RETRY TOOLS", GameFlow.decide(job("failed", "", "tools", "", false, false), fits()));
        eq("failed killed (old text)", "RETRY KILLED", GameFlow.decide(job("failed", "", "", "rewriting the game code was stopped by Android 2 times before it finished", false, false), fits()));
        eq("failed step", "RETRY STEP", GameFlow.decide(job("failed", "", "", "rewrite stopped with code 1", false, false), fits()));
        eq("failed dump", "RETRY DUMP", GameFlow.decide(job("failed", "", "dump", "", false, false), fits()));
        // A worker that is gone, or one that runs
        eq("running, worker dead", "CONTINUE INTERRUPTED", GameFlow.decide(job("running", "", "", "", false, false), fits()));
        eq("pending, never started", "CONTINUE INTERRUPTED", GameFlow.decide(job("pending", "", "", "", false, false), fits()));
        eq("running, worker alive", "VIEW NONE", GameFlow.decide(job("running", "", "", "", true, false), fits()));
        eq("paused battery, worker waits", "VIEW BATTERY", GameFlow.decide(job("paused", "battery", "", "", true, false), fits()));
        eq("paused by the user", "CONTINUE USER", GameFlow.decide(job("paused", "user", "", "", false, false), fits()));
        eq("paused refused", "CONTINUE REFUSED", GameFlow.decide(job("paused", "refused", "", "", false, false), fits()));
        // The job wins over an unchecked card; a finished one plays
        eq("job before the check", "CONTINUE INTERRUPTED", GameFlow.decide(job("running", "", "", "", false, false), PackFacts.unchecked(true)));
        eq("done and ready, unchecked", "PLAY NONE", GameFlow.decide(job("done", "", "", "", false, true), PackFacts.unchecked(true)));
        PackFacts mods = fits();
        mods.mods = true;
        eq("done and ready, mods changed since", "PLAY MODS auto", GameFlow.decide(job("done", "", "", "", false, true), mods));
        // No job: the pack decides
        eq("no profile", "FIX NO_PROFILE", GameFlow.decide(null, PackFacts.unchecked(false)));
        eq("no profile, with a job", "FIX NO_PROFILE", GameFlow.decide(job("failed", "", "nospace", "", false, false), PackFacts.unchecked(false)));
        eq("unchecked", "CHECKING NONE", GameFlow.decide(null, PackFacts.unchecked(true)));
        eq("fits", "PLAY NONE", GameFlow.decide(null, fits()));
        eq("done job, fits", "PLAY NONE", GameFlow.decide(job("done", "", "", "", false, false), fits()));
        PackFacts none = fits();
        none.pack = false;
        eq("no pack, dump", "PREPARE NO_PACK", GameFlow.decide(null, none));
        none.dump = false;
        eq("no pack, no dump", "FIX NO_PACK", GameFlow.decide(null, none));
        PackFacts unf = fits();
        unf.unfinished = true;
        eq("unfinished, dump", "PREPARE UNFINISHED", GameFlow.decide(null, unf));
        eq("mods changed, dump", "PLAY MODS auto", GameFlow.decide(null, mods));
        mods.dump = false;
        eq("mods changed, no dump", "FIX MODS", GameFlow.decide(null, mods));
        PackFacts other = fits();
        other.code = Boolean.FALSE;
        eq("another device's pack, dump", "PLAY NONE", GameFlow.decide(null, other));
        other.dump = false;
        eq("another device's pack, no dump", "PLAY NONE", GameFlow.decide(null, other));
        other.shadersMissing = true;
        other.playable = true;
        eq("another device's pack, older same-ABI shaders", "PLAY NONE", GameFlow.decide(null, other));
        other.playable = false;
        eq("another device's pack, no shaders", "FIX SHADERS", GameFlow.decide(null, other));
        PackFacts unknown = fits();
        unknown.code = null;
        eq("code unknown", "PLAY NONE", GameFlow.decide(null, unknown));
        PackFacts build = fits();
        build.build = true;
        eq("another build, dump", "PLAY BUILD auto", GameFlow.decide(null, build));
        build.shadersMissing = true;
        eq("another build, no shaders", "PREPARE BUILD", GameFlow.decide(null, build));
        build.playable = true;
        eq("another build, older same-ABI shaders, rewrite code only", "PLAY BUILD auto", GameFlow.decide(null, build));
        build.dump = false;
        eq("another build, no dump", "FIX BUILD", GameFlow.decide(null, build));
        PackFacts modsCompatible = fits();
        modsCompatible.mods = true;
        modsCompatible.shadersMissing = true;
        modsCompatible.playable = true;
        eq("mods and compatible external shaders, rewrite only code", "PLAY MODS auto", GameFlow.decide(null, modsCompatible));
        PackFacts sh = fits();
        sh.shadersMissing = true;
        eq("no shaders, dump", "PREPARE SHADERS", GameFlow.decide(null, sh));
        sh.legacy = true;
        eq("legacy shaders", "PLAY SHADERS", GameFlow.decide(null, sh));
        sh.legacy = false;
        sh.playable = true;
        eq("older same-ABI shaders play without update", "PLAY NONE", GameFlow.decide(null, sh));
        sh.playable = false;
        sh.dump = false;
        eq("no shaders, no dump", "FIX SHADERS", GameFlow.decide(null, sh));
        // The worker's failure codes
        eq("failCode NoSpace", "nospace", GameFlow.failCode(new NoSpace()));
        eq("failCode ToolsFailed", "tools", GameFlow.failCode(new ToolsFailed()));
        eq("failCode ENOSPC", "nospace", GameFlow.failCode(new IOException("write failed: ENOSPC (No space left on device)")));
        eq("failCode wrapped", "nospace", GameFlow.failCode(new RuntimeException("x", new IOException("No space left on device"))));
        eq("failCode other", "io", GameFlow.failCode(new IOException("Permission denied")));
        eq("failWhy unknown code", "STEP", GameFlow.failWhy("something", ""));
        eq("reasonWhy thermal", "THERMAL", GameFlow.reasonWhy("thermal"));
        eq("fits", "true", GameFlow.fits(2048L << 20, 2048L << 20));
        eq("does not fit", "false", GameFlow.fits(300L << 20, 768L << 20));
        eq("no need", "true", GameFlow.fits(-1, 0));
        System.out.println("ok " + n);
    }
}
