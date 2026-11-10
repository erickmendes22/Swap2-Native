package dev.nxnative.android;

import android.content.Context;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Locale;

/**
 * One on-device job (ONDEVICE.md "The job model"): <work>/ondevice/job.json, the manifest the service writes as it goes and the launcher reads when the service is
 * not running. Every write goes to job.json.tmp, is synced, and is renamed over job.json (FUSE has no RENAME_EXCHANGE; a plain rename of a file is atomic), so a
 * reader or a killed process sees the old or the new file, never half of one.
 *
 * <pre>
 * { "format": 1, "title_id", "name", "version", "dump", "work", "pack": the pack folder the job writes,
 *   "apk": { "engine", "dmsh_chain", "dmsh_vk_chain", "xlate_source", "version_code" }: what the outputs depend on (a change restarts the translation),
 *   "state": "pending" | "running" | "paused" | "done" | "failed", "reason": why paused (user, battery, thermal, timeout) or "", "error": why failed,
 *   "step": the current step, "steps": { "&lt;step&gt;": { "state": "pending" | "running" | "done", "done", "total", "stage" } }, "updated": ms }
 * </pre>
 * A "running" job whose service is gone (the process was killed, the phone rebooted) is resumed by the service (START_STICKY) or the launcher's Resume.
 */
final class Job {
    static final int FORMAT = 2;   // 2: the shaders step writes the library too (vk_android_build.py's result cache); 1 had a library step of its own
    static final String[] STEPS = {"identify", "rewrite", "split", "shaders", "pack"};
    /** The steps in English, for the logs and the job's own detail; the interface says them through STEP_RES */
    static final String[] STEP_TEXT = {"Checking the dump", "Rewriting the game code", "Finding the shaders", "Translating shaders", "Finishing the pack"};
    static final int[] STEP_RES = {R.string.s2_prep_identify, R.string.s2_prep_rewrite, R.string.s2_prep_split, R.string.s2_prep_translate, R.string.s2_prep_pack};
    /** Each step's share of the progress bar, roughly its time on the phone (ONDEVICE.md "Time and power"); the shaders' share is counted by shader */
    private static final int[] WEIGHT = {1, 5, 12, 78, 4};
    static final int SHADERS = 3;
    /** The steps whose outputs depend on the APK's shader chain: a job made by another APK starts them over */
    static final int FIRST_CHAIN_STEP = SHADERS;

    final File file;
    private JSONObject o;

    private Job(File file, JSONObject o) {
        this.file = file;
        this.o = o;
    }

    static File fileOf(File work) { return new File(new File(work, "ondevice"), "job.json"); }

    /**
     * A new job for a checked dump; not written yet. pack: where its pack goes, the app's packs/&lt;title ID&gt; (AppStorage.pack); the working files stay in the
     * dump's work folder (&lt;Switch2&gt;/Work/&lt;id&gt;/ondevice: DumpCheck.workOf)
     */
    static Job create(DumpCheck.Result r, File appPack) throws JSONException {
        JSONObject o = new JSONObject().put("format", FORMAT).put("title_id", r.titleId).put("name", Profile.of(r.titleId) != null ? Profile.of(r.titleId).name : r.titleId).put("version", r.version)
                .put("dump", r.dump.getPath()).put("work", r.work.getPath()).put("apk", apk()).put("state", "pending").put("reason", "").put("error", "")
                .put("step", STEPS[0]).put("created", System.currentTimeMillis());
        // the fake engine never writes over a real pack: its pack is a placeholder in ondevice/
        File pack = "fake".equals(BuildConfig.NX_PACK_ENGINE) ? new File(r.work, "ondevice/fake-pack") : appPack;
        o.put("pack", pack.getPath());
        o.put("own_pack", isNew(pack) || ShaderZip.onlyShaders(pack));   // a folder with only imported shaders (Import shaders…) becomes the job's pack
        // the shaders a delta update translates (the pack's older libraries in the profile's delta manifest, DMSH_VK_DELTA_FROM): the shaders step's total for the
        // count and the time left until the tool reports its own; without it, every shader of the profile
        int delta = Pack.deltaShaders(pack, r.titleId);
        if (delta >= 0) o.put("expected_shaders", delta);
        JSONObject steps = new JSONObject();
        for (String s : STEPS) steps.put(s, new JSONObject().put("state", "pending").put("done", 0).put("total", 0).put("stage", ""));
        o.put("steps", steps);
        return new Job(fileOf(r.work), o);
    }

    /**
     * A job for a pack that is already there (PackCheck): ready (every step done, its pack that folder), or with what does not fit redone in that folder: the code
     * (rewrite and pack; the shader library in the pack is kept), the shaders (split, shaders, pack; the code is kept), or both. The simulated engine never writes
     * into a real pack: its rebuild goes to ondevice/fake-pack.
     */
    static Job adopt(DumpCheck.Result r, File packDir, boolean code, boolean shaders) throws JSONException {
        Job j = create(r, packDir);
        boolean fake = "fake".equals(BuildConfig.NX_PACK_ENGINE);
        boolean ready = !code && !shaders;
        if (ready || !fake) j.o.put("pack", packDir.getPath());
        for (String s : STEPS) {
            boolean shaderStep = s.equals("split") || s.equals("shaders");
            if (ready || s.equals("identify") || !code && s.equals("rewrite") || !shaders && shaderStep) j.stepState(s, "done");
        }
        // the code only: the pack step takes the library already in the pack (pack_android.py --shader-cache <pack>/shaders: current there, so it stays as it is)
        if (!shaders && !ready && !fake) j.o.put("shader_cache", new File(packDir, "shaders").getPath());
        if (ready) j.o.put("state", "done");
        if (code && !shaders) j.o.put("code_only", true);   // the short job (Play after a mod change, a pack from another device): the screen shows it as one bar
        j.o.put("adopted", packDir.getPath());
        return j;
    }

    static Job read(File f) throws IOException {
        try {
            JSONObject o = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            if (o.optInt("format") != FORMAT) throw new IOException(f + ": job format " + o.optInt("format") + ", this app writes " + FORMAT);
            Job j = new Job(f, o);
            j.normalize();
            return j;
        } catch (JSONException e) {
            throw new IOException(f + ": " + e.getMessage());
        }
    }

    /**
     * A job that is not running has no running step (GameFlow.normalizeSteps): a worker that died between marking a step running and its end left one, which
     * the card and the import checks took for a rewrite in progress for good (found on a phone whose storage was full, 2026-11-08)
     */
    private void normalize() {
        String[] st = new String[STEPS.length];
        for (int i = 0; i < STEPS.length; i++) st[i] = stepState(STEPS[i]);
        String[] n = GameFlow.normalizeSteps(state(), st);
        for (int i = 0; i < STEPS.length; i++) if (!n[i].equals(st[i])) stepState(STEPS[i], n[i]);
    }

    /** Every running step back to pending (the worker ended without finishing it) */
    synchronized void clearRunningSteps() { for (String s : STEPS) if ("running".equals(stepState(s))) stepState(s, "pending"); }

    /** A job as the service sends it (the same JSON) */
    static Job of(File f, String json) {
        try {
            return new Job(f, new JSONObject(json));
        } catch (JSONException e) {
            return null;
        }
    }

    /** What this APK's outputs depend on (ONDEVICE.md "Versions") */
    static JSONObject apk() {
        try {
            return new JSONObject().put("engine", BuildConfig.NX_PACK_ENGINE).put("dmsh_chain", BuildConfig.NX_DMSH_CHAIN).put("dmsh_vk_chain", BuildConfig.NX_DMSH_VK_CHAIN)
                    .put("xlate_source", BuildConfig.NX_XLATE_SOURCE).put("version_code", BuildConfig.VERSION_CODE);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Whether the job's translated shaders came from another chain (or engine) than this APK's: then they are translated again */
    synchronized boolean apkChanged() {
        JSONObject a = o.optJSONObject("apk"), b = apk();
        if (a == null) return true;
        for (String k : new String[] {"engine", "dmsh_chain", "dmsh_vk_chain", "xlate_source"}) if (!b.optString(k).equals(a.optString(k))) return true;
        return false;
    }

    /**
     * The pack folder already holds this APK's library of the game, built from the profile's inputs (Import shaders…: ShaderZip.ready): the split and the
     * translation are recorded done as they are ("imported"), and the pack step takes the library where it is (--shader-cache &lt;pack&gt;/shaders: current there,
     * so pack_android.py copies nothing). Nothing is translated on the phone
     */
    synchronized void shadersInPack() {
        try {
            Profile p = Profile.of(titleId());
            long n = p != null ? p.shaderTotal : 0;
            for (String s : new String[] {"split", "shaders"}) step0(s).put("state", "done").put("done", n).put("total", n).put("stage", "imported");
            o.put("shader_cache", new File(pack(), "shaders").getPath());
            o.put("shaders_imported", true);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Whether the job took its shader library from the pack (shadersInPack) instead of translating it */
    synchronized boolean shadersImported() { return o.optBoolean("shaders_imported", false); }

    /** What names a library file's bytes for importRefused: its path, size and modification time (a new import changes them) */
    static String librarySignature(File lib) { return lib == null ? "" : lib.getPath() + "|" + lib.length() + "|" + lib.lastModified(); }

    /**
     * The pack step refused the library the job took from the pack (pack_android.py's library_current: built from other shader tables than the phone's profile, which
     * the launcher could not see when its inputs are "unknown"): the split and the translation go back to pending, and that library (by its signature) is not taken
     * again, so a Retry translates on the phone instead of failing the same way. A newly imported library is taken again
     */
    synchronized void importRefused(File lib) {
        try {
            for (String s : new String[] {"split", "shaders"}) o.getJSONObject("steps").put(s, new JSONObject().put("state", "pending").put("done", 0).put("total", 0).put("stage", ""));
            o.remove("shader_cache");
            o.remove("shaders_imported");
            o.put("import_refused", librarySignature(lib));
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Whether the pack step refused this library before (importRefused) */
    synchronized boolean refusedImport(File lib) { return lib != null && librarySignature(lib).equals(o.optString("import_refused", "")); }

    /** Starts the chain's steps over with this APK's versions; the caller deletes their outputs */
    /** The exact number of shaders a reviewed incremental hot update compiles. */
    synchronized void expectedShaders(int n) throws JSONException {
        if (n > 0) o.put("expected_shaders", n);
        else o.remove("expected_shaders");
    }

    /** An already-playable same-ABI or audited ABI-extension library is kept
     * unchanged after an APK update. No full shader job must be restarted just
     * because a tool/chain version string changed. */
    synchronized void acceptPlayableShaderVersion() throws JSONException {
        o.put("apk", apk());
        o.remove("expected_shaders");
    }

    synchronized void resetChainSteps() throws JSONException {
        // the split is the dump's and stays valid, but a finished job deleted it: then it is made again too
        int from = new File(dir(), "split").isDirectory() ? FIRST_CHAIN_STEP : FIRST_CHAIN_STEP - 1;
        for (int i = from; i < STEPS.length; i++) o.getJSONObject("steps").put(STEPS[i], new JSONObject().put("state", "pending").put("done", 0).put("total", 0).put("stage", ""));
        o.remove("shader_cache");
        // A scoped update may have completed just 4 shaders. Its count is
        // specific to the prior APK; an ordinary full rebuild must never keep
        // showing that stale total until the translator starts reporting.
        o.remove("expected_shaders");
        o.remove("shaders_imported");   // translated again: the preparation screen shows the translation's count, not "imported"
        o.put("apk", apk());
        if ("done".equals(state())) o.put("state", "paused").put("reason", "apk");
    }

    synchronized void save() throws IOException {
        try {
            o.put("updated", System.currentTimeMillis());
        } catch (JSONException e) {
            throw new IOException(e);
        }
        File dir = file.getParentFile();
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot make " + dir);
        File tmp = new File(dir, file.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(o.toString(1).getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        } catch (JSONException e) {
            throw new IOException(e);
        }
        Files.move(tmp.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    synchronized String json() { return o.toString(); }

    synchronized String state() { return o.optString("state"); }
    synchronized String reason() { return o.optString("reason"); }
    synchronized String error() { return o.optString("error"); }
    /** Why it failed, a code (GameFlow: nospace, tools, killed, io, step, dump, imported_shaders, unreadable); "" for a job.json of an older APK */
    synchronized String errorCode() { return o.optString("errorCode", ""); }
    /** A number the failure's sentence takes (free, need: bytes), -1 when there is none */
    synchronized long errorArg(String k) { JSONObject a = o.optJSONObject("errorArgs"); return a == null ? -1 : a.optLong(k, -1); }
    /** The short job: only the code is rewritten (Job.adopt with the shaders kept) */
    synchronized boolean codeOnly() { return o.optBoolean("code_only", false); }
    synchronized String name() { return o.optString("name"); }
    synchronized String titleId() { return o.optString("title_id"); }
    synchronized long version() { return o.optLong("version"); }
    synchronized long updated() { return o.optLong("updated"); }
    synchronized long created() { return o.optLong("created"); }
    synchronized File dump() { return new File(o.optString("dump")); }
    synchronized File work() { return new File(o.optString("work")); }
    synchronized File pack() { return new File(o.optString("pack")); }
    /** The folder of shader libraries (v-<V>/) the pack step copies from: the job's own build (ondevice/lib), or the pack's shaders/ when only the code is redone */
    synchronized File shaderCache() { String s = o.optString("shader_cache", ""); return s.isEmpty() ? new File(dir(), "lib") : new File(s); }

    /** A folder the job may call its own (and so offer to delete): one that does not exist yet, or is empty, when the job is made */
    static boolean isNew(File dir) {
        String[] l = dir.list();
        return !dir.exists() || l != null && l.length == 0;
    }

    /** Whether the job made its pack folder (own_pack): a folder that was there before, a Mac pack say, is the user's and is never deleted by the app */
    synchronized boolean ownsPack() { return o.optBoolean("own_pack", false) && adopted().isEmpty(); }

    /** Another pack folder for a new job (Ondevice's ondevice_pack: agents' test runs, never the app's packs/&lt;id&gt; or a pack beside the dump) */
    synchronized void pack(File dir) {
        try {
            o.put("own_pack", isNew(dir) || ShaderZip.onlyShaders(dir));
            o.put("pack", dir.getPath());
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }
    File dir() { return file.getParentFile(); }
    /** The pack folder this job took over as it was (Job.adopt), "" when the job makes its own */
    synchronized String adopted() { return o.optString("adopted", ""); }

    synchronized void state(String state, String reason, String error) {
        try {
            o.put("state", state).put("reason", reason == null ? "" : reason).put("error", error == null ? "" : error);
            if (!"failed".equals(state)) { o.remove("errorCode"); o.remove("errorArgs"); }
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Failed, with its code (GameFlow), the numbers its sentence takes (free / need in bytes, -1 for none) and the detail for the logs and Details (English) */
    synchronized void fail(String code, long free, long need, String detail) {
        try {
            o.put("state", "failed").put("reason", "").put("error", detail == null ? "" : detail).put("errorCode", code);
            if (free >= 0 || need >= 0) o.put("errorArgs", new JSONObject().put("free", free).put("need", need));
            else o.remove("errorArgs");
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    private JSONObject step(String s) {
        JSONObject steps = o.optJSONObject("steps");
        JSONObject j = steps == null ? null : steps.optJSONObject(s);
        return j != null ? j : new JSONObject();
    }

    synchronized String stepState(String s) { return step(s).optString("state", "pending"); }

    synchronized void stepState(String s, String state) {
        try {
            step0(s).put("state", state);
            if (state.equals("running")) { o.put("step", s); step0(s).put("started", System.currentTimeMillis()); }
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * One more start of step s (its "starts" in job.json, saved with the step's running state): a start the process did not live through to the step's end
     * (Android ended it, most likely for memory: the rewrite peaks at 2.7 GB) stays counted, so a sticky restart cannot loop on it. → the starts so far
     */
    synchronized int start(String s) {
        try {
            JSONObject j = step0(s);
            int n = j.optInt("starts", 0) + 1;
            j.put("starts", n);
            return n;
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** The step ended in this process (done, failed, paused): its unfinished starts are forgotten. All steps' when the user starts the job again (Retry, Resume) */
    synchronized void ended(String s) { try { step0(s).put("starts", 0); } catch (JSONException e) { throw new IllegalStateException(e); } }

    synchronized void endedAll() { for (String s : STEPS) ended(s); }

    /** A step's count from the tool's progress lines */
    synchronized void stepProgress(String s, long done, long total, String stage) {
        try {
            step0(s).put("done", done).put("total", total).put("stage", stage == null ? "" : stage);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** A step's measured seconds per unit of its count (PrepareTime.Meter in PackService's Tail), kept in job.json for the screen's time left */
    synchronized void stepRate(String s, double rate) {
        try {
            if (rate > 0 && !Double.isInfinite(rate)) step0(s).put("rate", rate);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * What is left of the job, in seconds (PrepareTime.remaining), -1 when it is done: the current step at its measured rate (job.json's "rate"; a paused step keeps
     * the one its last run measured), else at this phone's rates, and the steps after it at those rates. Shaders kept or imported cost nothing
     */
    synchronized long remaining(PrepareTime.Rates r, long nowMs) {
        if ("done".equals(state())) return -1;
        boolean[] done = new boolean[STEPS.length];
        for (int i = 0; i < STEPS.length; i++) done[i] = "done".equals(stepState(STEPS[i]));
        int cur = current();
        JSONObject st = step(STEPS[cur]);
        long started = st.optLong("started", 0);
        boolean running = "running".equals(state()) && "running".equals(st.optString("state"));
        double elapsed = running && started > 0 ? Math.max(0, (nowMs - started) / 1000.0) : -1;
        String stage = st.optString("stage");
        boolean finishing = cur == SHADERS && (stage.equals("library") || stage.equals("done") || stage.equals("check"));
        Profile p = Profile.of(titleId());
        int map = p != null ? p.shaderTotal : 0;
        long toTranslate = shadersImported() || done[SHADERS] ? 0 : shadersTotal();
        return PrepareTime.remaining(r, done, cur, stepDone(cur), stepTotal(cur), st.optDouble("rate", -1), elapsed, toTranslate, map, finishing);
    }

    // ---- This phone's rates (PrepareTime.Rates): learned by PackService as jobs run, in the "prepare_time" preferences; its SoC class's until then ----

    static final String RATE_SHADER = "shader", RATE_SPLIT = "split", RATE_PACK = "pack";
    private static PrepareTime.Rates rates;
    private static java.util.Map<String, ?> kept = java.util.Collections.emptyMap();
    private static long ratesAt;

    /** The name of a game's rewrite time in the phone's rates: each game's own (DKB's code rewrites in 74 s, Zelda's in 241 s on the same phone) */
    static String rateRewrite(String titleId) { return "rewrite." + titleId; }

    /**
     * This phone's rates for the game titleId, read at most every 30 s (the card and the screen ask on every job tick; PackService writes them in its own process):
     * the shaders', the split's and the pack step's the phone's, the rewrite's the game's (its SoC class's until that game's code was rewritten whole here)
     */
    static synchronized PrepareTime.Rates rates(Context c, String titleId) {
        long now = android.os.SystemClock.elapsedRealtime();
        if (rates == null || now - ratesAt >= 30_000) {
            PrepareTime.Rates d = PrepareTime.defaults(android.os.Build.SOC_MODEL);
            android.content.SharedPreferences p = Prefs.open(c, "prepare_time");
            rates = new PrepareTime.Rates(p.getFloat(RATE_SHADER, (float) d.shader), p.getFloat(RATE_SPLIT, (float) d.split), d.rewrite, p.getFloat(RATE_PACK, (float) d.pack));
            kept = p.getAll();
            ratesAt = now;
        }
        Object rw = titleId == null ? null : kept.get(rateRewrite(titleId));
        return rw instanceof Float ? new PrepareTime.Rates(rates.shader, rates.split, (Float) rw, rates.pack) : rates;
    }

    /** The phone's rate of key before anything was learned in this run (0: none learned yet), for PrepareTime.learn from a fixed base */
    static float learned(Context c, String key) { return Prefs.open(c, "prepare_time").getFloat(key, 0); }

    /** Keeps a learned rate (seconds), base: what was kept before this run (learned) */
    static synchronized void learn(Context c, String key, float base, double measured) {
        double v = PrepareTime.learn(base, measured);
        if (!(v > 0)) return;
        Prefs.open(c, "prepare_time").edit().putFloat(key, (float) v).apply();
        rates = null;
    }

    private JSONObject step0(String s) throws JSONException {
        JSONObject steps = o.optJSONObject("steps");
        if (steps == null) o.put("steps", steps = new JSONObject());
        JSONObject j = steps.optJSONObject(s);
        if (j == null) steps.put(s, j = new JSONObject().put("state", "pending").put("done", 0).put("total", 0).put("stage", ""));
        return j;
    }

    /** The first step not done, -1 when all are */
    synchronized int next() {
        for (int i = 0; i < STEPS.length; i++) if (!"done".equals(stepState(STEPS[i]))) return i;
        return -1;
    }

    /** The step to show: the running one, else the next to run, else the last */
    synchronized int current() {
        int i = java.util.Arrays.asList(STEPS).indexOf(o.optString("step"));
        int n = next();
        if (n < 0) return STEPS.length - 1;
        return i >= 0 && "running".equals(stepState(STEPS[i])) ? i : n;
    }

    /** 0..1 over all steps, each by its weight and its own count */
    synchronized double overall() {
        double sum = 0, all = 0;
        for (int i = 0; i < STEPS.length; i++) {
            all += WEIGHT[i];
            JSONObject j = step(STEPS[i]);
            if ("done".equals(j.optString("state"))) sum += WEIGHT[i];
            else if (j.optLong("total") > 0) sum += WEIGHT[i] * Math.min(1.0, (double) j.optLong("done") / j.optLong("total"));
        }
        return sum / all;
    }

    synchronized long stepDone(int i) { return step(STEPS[i]).optLong("done"); }
    synchronized long stepTotal(int i) { return step(STEPS[i]).optLong("total"); }

    /** The shaders translated so far and their total (the game's profile's shader map, Profile.shaderTotal, until the tool says its own) */
    synchronized long shadersDone() { return "done".equals(stepState(STEPS[SHADERS])) ? shadersTotal() : stepDone(SHADERS); }
    // the tool's total once it reported one: the shaders it translates (a delta update keeps the others, android/SHADERS.md#delta-updates), else the profile's count
    // (until then the delta manifest's count the job was made with, "expected_shaders", else the profile's count)
    synchronized long shadersTotal() {
        long t = stepTotal(SHADERS);
        if (t > 1 || !step(STEPS[SHADERS]).optString("stage").isEmpty()) return t;
        if (o.has("expected_shaders")) return o.optLong("expected_shaders");
        Profile p = Profile.of(titleId());
        return p != null ? p.shaderTotal : 0;
    }

    /** "Translating shaders: 12,345 of 22,852" during the shaders step ("Writing the shader library" at its end), else the step and its count when it has one */
    synchronized String stepText() {
        int i = current();
        if (i == SHADERS) {
            String stage = step(STEPS[i]).optString("stage");
            if (stage.equals("library") || stage.equals("done")) return "Writing the shader library";
            if (stage.equals("check")) return "Checking the shader library";
            return String.format(Locale.getDefault(), "%s: %,d of %,d", STEP_TEXT[i], shadersDone(), shadersTotal());
        }
        long d = stepDone(i), t = stepTotal(i);
        return STEP_TEXT[i] + (t > 1 ? String.format(Locale.getDefault(), " %,d / %,d", d, t) : t == 1 || d == 0 ? "" : String.format(Locale.getDefault(), " %,d", d));
    }

    /** The step being shown, in the interface's language: "Process the shaders: 12,345 of 22,852", or the step and its count */
    synchronized String stepText(Context c) {
        int i = current();
        if (i == SHADERS) {
            String stage = step(STEPS[i]).optString("stage");
            if (stage.equals("library") || stage.equals("done")) return c.getString(R.string.s2_st_library);
            if (stage.equals("check")) return c.getString(R.string.s2_st_check_library);
            return c.getString(R.string.s2_st_shaders, c.getString(STEP_RES[i]), shadersDone(), shadersTotal());
        }
        long d = stepDone(i), t = stepTotal(i);
        return c.getString(STEP_RES[i]) + (t > 1 ? String.format(Locale.getDefault(), " %,d / %,d", d, t) : t == 1 || d == 0 ? "" : String.format(Locale.getDefault(), " %,d", d));
    }

    /** The current step's name in the interface's language */
    synchronized String stepName(Context c) { return c.getString(STEP_RES[current()]); }

    /** One line for the screen and the notification, in the interface's language: what the job is doing, or why it stopped and what to do */
    synchronized String statusText(Context c, boolean serviceAlive) {
        String s = state();
        switch (s) {
            case "done": return c.getString(R.string.s2_st_done);
            case "failed": return GameState.whyText(c, GameFlow.failWhy(errorCode(), error()), this);
            case "pending": return c.getString(serviceAlive ? R.string.s2_st_starting : R.string.s2_st_pending);
            case "paused": return c.getString(R.string.s2_st_paused, reasonText(c, reason()), stepText(c));
            case "running": return serviceAlive ? c.getString(R.string.s2_st_running, stepText(c), current() + 1, STEPS.length)
                    : c.getString(R.string.s2_st_interrupted, stepText(c));
            default: return s;
        }
    }

    /** Why a job paused, in the interface's language */
    static String reasonText(Context c, String r) {
        switch (r == null ? "" : r) {
            case "user": return c.getString(R.string.s2_why_user);
            case "battery": return c.getString(R.string.s2_why_battery);
            case "thermal": return c.getString(R.string.s2_why_thermal);
            case "timeout": return c.getString(R.string.s2_why_timeout);
            case "refused": return c.getString(R.string.s2_why_refused);
            case "killed": return c.getString(R.string.s2_why_killed);
            case "apk": return c.getString(R.string.s2_why_apk);
            default: return r == null || r.isEmpty() ? c.getString(R.string.s2_why_stopped) : r;
        }
    }

    /** One line for the logs and the job's detail (English): what the job is doing or why it stopped */
    synchronized String statusText(boolean serviceAlive) {
        String s = state();
        String step = "step " + (current() + 1) + " of " + STEPS.length;
        switch (s) {
            case "done": return "Ready to play.";
            case "failed": return "Stopped at " + STEP_TEXT[current()].toLowerCase(Locale.ROOT) + ": " + error().replaceAll("[.\\s]+$", "") + ". Tap Retry to go on.";
            case "pending": return "Not started yet.";
            case "paused": return "Paused: " + reasonText(reason()) + ". " + stepText() + ".";
            case "running": return serviceAlive ? stepText() + " (" + step + ")."
                    : "Interrupted at " + stepText() + ". Tap Resume to go on.";
            default: return s;
        }
    }

    static String reasonText(String r) {
        switch (r) {
            case "user": return "by you";
            case "battery": return "battery below 20 %: plug in the charger to go on";
            case "thermal": return "the phone is too hot: it goes on when it has cooled";
            case "timeout": return "Android's daily limit for background work: open the app and tap Resume";
            case "refused": return "Android did not let it start in the background: open the app and tap Resume";
            case "apk": return "the app was updated with other shader tools: the shaders are translated again";
            default: return r.isEmpty() ? "stopped" : r;
        }
    }

    /**
     * The split's kept scan results (shader_split.py DM_SPLIT_RESUME), kept across pauses, kills and reboots until the job records the split done. In the app's
     * own storage, not beside the job on shared storage: no other app can put files there for the split to read, and its syncs do not go through FUSE.
     * One folder a game; the files carry a digest of their inputs, so another job of the same game starts it over.
     */
    synchronized File splitScan(Context c) {
        return new File(c.getNoBackupFilesDir(), "split.scan/" + titleId());
    }

    /** Syncs every file under f to the disk (the split's outputs, before they are renamed into place and the step is recorded done) */
    static void syncTree(File f) throws IOException {
        File[] kids = Files.isSymbolicLink(f.toPath()) ? null : f.listFiles();
        if (kids != null) for (File k : kids) {
            if (k.isDirectory()) syncTree(k);
            else try (java.nio.channels.FileChannel ch = java.nio.channels.FileChannel.open(k.toPath(), java.nio.file.StandardOpenOption.WRITE)) { ch.force(true); }
        }
    }

    /** Deletes a folder of the job's own outputs: ondevice/ paths, and the pack the job made itself (Ondevice's Manage, asked first; never the dump or the saves) */
    static void deleteTree(File f) {
        File[] kids = Files.isSymbolicLink(f.toPath()) ? null : f.listFiles();   // a link goes, never what it points to
        if (kids != null) for (File k : kids) {
            if (k.isDirectory()) deleteTree(k);
            else k.delete();
        }
        f.delete();
    }

    /** The job the launcher shows (the last started), remembered across processes */
    static File remembered(Context c) {
        String p = Prefs.open(c, "ondevice").getString("job", null);
        return p == null ? null : new File(p);
    }

    static void remember(Context c, File jobFile) {
        Prefs.open(c, "ondevice").edit().putString("job", jobFile == null ? null : jobFile.getPath()).commit();
    }
}
