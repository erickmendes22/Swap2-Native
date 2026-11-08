package dev.nxnative.android;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * What runs a step's tool: the native engine (PackNative, libnxpack.so: the embedded CPython running the repository's tools, which load the translator and SPIRV-Tools from the APK through ctypes)
 * or FakeEngine (-PnxPackEngine=fake). The service calls run() on its worker thread, one tool at a time, and interrupt() from any thread.
 */
interface PackEngine {
    /** PackNative.packRun's contract (see there) */
    int run(String tool, String[] argv, String logPath);

    /** PackNative.packInterrupt's contract (see there) */
    void interrupt();

    /** A simulated engine: its pack is a placeholder that is never played */
    boolean simulated();

    /**
     * Makes the tools ready before a step is marked running (PackService's preflight): the native engine unpacks them and starts Python (PackNative.start), so
     * a full disk or a failed unpack is the job's failure with its code (NoSpace, ToolsFailed), never a step left running with no line in its log
     */
    default void prepare() throws IOException {}

    /** The tools' unpack ran out of room: free and need in bytes (GameFlow's code nospace) */
    final class NoSpace extends IOException {
        final long free, need;
        NoSpace(long free, long need) {
            super("No space left for the preparation tools: " + GameFlow.gb(free) + " free, " + GameFlow.gb(need) + " needed (ENOSPC)");
            this.free = free;
            this.need = need;
        }
    }

    /** The tools did not unpack or Python did not start (GameFlow's code tools) */
    final class ToolsFailed extends IOException {
        ToolsFailed(String m, Throwable cause) { super(m, cause); }
    }

    /** What unpacking the tools still takes in the app's files (0 once this APK's are there): PackNative.toolsBytes */
    static long toolsBytes(Context c) { return "fake".equals(BuildConfig.NX_PACK_ENGINE) ? 0 : PackNative.toolsBytes(c); }

    /** Exit code of a tool stopped by interrupt() (128 + SIGINT, as a shell reports it) */
    int INTERRUPTED = 130;

    /** The tools' environment as the service set it: the native engine passes it with each run (Python reads the process environment only once, at its start) */
    Map<String, String> ENV = new LinkedHashMap<>();

    static PackEngine create(Context c) {
        if ("fake".equals(BuildConfig.NX_PACK_ENGINE)) return new FakeEngine();
        PackNative.context(c);
        return new PackEngine() {
            public int run(String tool, String[] argv, String logPath) { return PackNative.packRun(tool, argv, logPath); }
            public void interrupt() { PackNative.packInterrupt(); }
            public boolean simulated() { return false; }
            public void prepare() throws IOException { PackNative.repo(); }
        };
    }

    /** Environment the tools read, set before a run: in ENV (the native engine's runs) and in the process (Os.setenv: native code's getenv) */
    static void setenv(String key, String value) {
        synchronized (ENV) { ENV.put(key, value); }
        try {
            Os.setenv(key, value, true);
        } catch (ErrnoException e) {
            throw new IllegalStateException(e);
        }
    }
}

/**
 * The Java ↔ native seam (libnxpack.so with libpython3.14.so, loaded in the :pack process only, never with libnxhost.so; android/ondevice/dm_pack.h). Contract:
 * <ul>
 * <li>{@code packRun(tool, argv, logPath)} runs one tool to its end on the calling thread and returns its exit code. {@code tool} is a repository path
 *     ({@code scripts/pack_android.py}, {@code dm/gfx/tools/shader_split.py}, ...) resolved against the tools unpacked from the APK; a Python tool runs in the
 *     embedded CPython by {@code runpy.run_path(tool)} with {@code sys.argv = [tool] + argv}, {@code SystemExit}'s code is the exit code, an uncaught exception
 *     is 1 (its traceback in the log). Its {@code sys.stdout} and {@code sys.stderr} are appended to {@code logPath}, which the caller creates. The environment
 *     is {@link PackEngine#ENV} for that run. The tool reports progress as lines {@code progress <done> <total> <stage>} (or shader_split.py's
 *     {@code progress: <done>/<total>}); the service reads them from the log as it grows. One call at a time per process.</li>
 * <li>The first run in the process unpacks the APK's {@code assets/pack/python.zip} and {@code tools.zip} to {@code filesDir/pack/<version>/} (python/, repo/;
 *     {@code version.txt} names the version, a new APK's zips go to a new folder by rename and the old ones are deleted), then starts Python with that home.
 *     A failure there is written to the log and the run returns 1.</li>
 * <li>{@code packInterrupt()} asks the running tool to stop: a {@code KeyboardInterrupt} raised in its thread at its next bytecode
 *     ({@code PyThreadState_SetAsyncExc}; {@code PyErr_SetInterrupt} would act only on Python's main thread with Python's SIGINT handler, and the packer has
 *     neither). {@code packRun} then returns {@link PackEngine#INTERRUPTED}. Any thread (it hands the call to a thread of its own, since taking the GIL can wait
 *     for a long C call); nothing when no tool runs. A tool that does not return within 20 s is ended with its process by the service: every step is
 *     restartable.</li>
 * </ul>
 */
final class PackNative {
    private static final String TAG = "nxpack";
    private static Context app;
    private static File root;          // filesDir/pack/<version>, once unpacked and Python started
    private static volatile boolean loaded;

    private PackNative() {}

    static synchronized void context(Context c) { if (app == null) app = c.getApplicationContext(); }

    static native int init0(String pythonHome);

    static native int run0(String tool, String[] args, String[] env, String logPath);

    static native int interrupt0();

    /** packTryRun's answer while another tool runs in this process (75: EX_TEMPFAIL) */
    static final int BUSY = 75;
    /** One tool at a time in the process: the job's (PackService) and a short one's (SceneService) */
    private static final java.util.concurrent.locks.ReentrantLock RUN = new java.util.concurrent.locks.ReentrantLock();

    /** Guards the job's state below: packInterrupt reaches the job's tool, or the job while it waits for a short run, never the short run itself */
    private static final Object STOP = new Object();
    private static boolean jobWaits, jobRuns, stopJob;

    /**
     * Runs the tool, after the one running in this process (a short SceneService run) has ended. A packInterrupt while it waits returns INTERRUPTED without
     * running the tool (the short run goes on to its end)
     */
    static int packRun(String tool, String[] argv, String logPath) {
        synchronized (STOP) { jobWaits = true; stopJob = false; }
        boolean held = false;
        try {
            while (!(held = RUN.tryLock(100, java.util.concurrent.TimeUnit.MILLISECONDS))) {
                synchronized (STOP) { if (stopJob) return PackEngine.INTERRUPTED; }
            }
            synchronized (STOP) {
                if (stopJob) return PackEngine.INTERRUPTED;
                jobRuns = true;
            }
            return runLocked(tool, argv, logPath);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return PackEngine.INTERRUPTED;
        } finally {
            synchronized (STOP) { jobWaits = false; jobRuns = false; stopJob = false; }
            if (held) RUN.unlock();
        }
    }

    /** Runs the tool when no other runs in this process (the job's step: hours), else BUSY at once */
    static int packTryRun(String tool, String[] argv, String logPath) {
        if (!RUN.tryLock()) return BUSY;
        try { return runLocked(tool, argv, logPath); } finally { RUN.unlock(); }
    }

    private static int runLocked(String tool, String[] argv, String logPath) {
        File r;
        try {
            r = start();
        } catch (IOException | RuntimeException | UnsatisfiedLinkError e) {
            Log.e(TAG, "the packer did not start", e);
            log(logPath, "[RED] the packer did not start: " + e + "\n");
            return 1;
        }
        String[] env;
        synchronized (PackEngine.ENV) {
            env = PackEngine.ENV.entrySet().stream().map(x -> x.getKey() + "=" + x.getValue()).toArray(String[]::new);
        }
        return run0(new File(new File(r, "repo"), tool).getPath(), argv, env, logPath);
    }

    /** The repository's tools as unpacked from the APK (starts the packer when it has not started in this process) */
    static File repo() throws IOException { return new File(start(), "repo"); }

    static void packInterrupt() {
        synchronized (STOP) {
            if (jobWaits && !jobRuns) { stopJob = true; Log.i(TAG, "interrupt: the job's next tool will not start"); return; }
            if (!jobRuns) { Log.i(TAG, "interrupt: no job tool running"); return; }   // a short run (SceneService) is not the job's to stop
        }
        if (!loaded) return;
        Thread t = new Thread(() -> Log.i(TAG, "interrupt: " + (interrupt0() > 0 ? "sent" : "no tool running")), "nxpack-interrupt");
        t.setDaemon(true);
        t.start();
    }

    /** Room kept free beyond the unpacked tools (the job's own first writes) */
    private static final long TOOLS_MARGIN = 64L << 20;

    private static String version(Context c) throws IOException {
        String version;
        try (BufferedReader b = new BufferedReader(new InputStreamReader(c.getAssets().open("pack/version.txt"), StandardCharsets.UTF_8))) {
            version = b.readLine().trim();
        }
        if (!version.matches("[0-9a-f]{16}")) throw new IOException("assets/pack/version.txt: " + version);
        return version;
    }

    /**
     * The unpacked size of the tools: assets/pack/size.txt (build.gradle writes it beside version.txt), else the zips' entry sizes as they report them, plus
     * the margin. An older APK with neither counts only the margin
     */
    static long unpackedBytes(Context c) {
        try (BufferedReader b = new BufferedReader(new InputStreamReader(c.getAssets().open("pack/size.txt"), StandardCharsets.UTF_8))) {
            return Long.parseLong(b.readLine().trim()) + TOOLS_MARGIN;
        } catch (IOException | RuntimeException e) {
            long n = 0;
            for (String a : new String[] {"pack/python.zip", "pack/tools.zip"}) {
                try (InputStream in = c.getAssets().open(a); ZipInputStream z = new ZipInputStream(in)) {
                    ZipEntry ze;
                    while ((ze = z.getNextEntry()) != null) if (ze.getSize() > 0) n += ze.getSize();
                } catch (IOException x) { /* no packer in this APK */ }
            }
            return n + TOOLS_MARGIN;
        }
    }

    /** What unpacking still takes in filesDir: 0 when this APK's tools are there */
    static long toolsBytes(Context c) {
        try {
            File dir = new File(new File(c.getFilesDir(), "pack"), version(c));
            return dir.isDirectory() ? 0 : unpackedBytes(c);
        } catch (IOException e) {
            return 0;
        }
    }

    /**
     * Unpacks the Python home and the tools when this APK's are not there yet, loads the library and starts Python (once per process). Other versions and a
     * stopped unpack (.tmp) are deleted first, so a phone needs room for one copy, not two; the room is checked before anything is written (NoSpace); a failed
     * unpack leaves no .tmp behind (ToolsFailed)
     */
    private static synchronized File start() throws IOException {
        if (root != null) return root;
        if (app == null) throw new IllegalStateException("PackNative.context not set");
        String version = version(app);
        File base = new File(app.getFilesDir(), "pack"), dir = new File(base, version);
        File[] old = base.listFiles();
        if (old != null) for (File f : old) if (!f.getName().equals(version)) { Log.i(TAG, "deleting the packer's other version " + f.getName()); Job.deleteTree(f); }
        if (!dir.isDirectory()) {
            long t0 = System.nanoTime();
            long need = unpackedBytes(app), free = new android.os.StatFs(app.getFilesDir().getPath()).getAvailableBytes();
            if (!GameFlow.fits(free, need)) {
                PackEngine.NoSpace e = new PackEngine.NoSpace(free, need);
                Log.e(TAG, e.getMessage());
                throw e;
            }
            File tmp = new File(base, version + ".tmp");
            try {
                unzip("pack/python.zip", new File(tmp, "python"));
                unzip("pack/tools.zip", new File(tmp, "repo"));
                if (!tmp.renameTo(dir)) throw new IOException("cannot rename " + tmp + " to " + dir);
            } catch (IOException | RuntimeException e) {
                Job.deleteTree(tmp);
                Log.e(TAG, "unpacking the packer failed", e);
                long now = new android.os.StatFs(app.getFilesDir().getPath()).getAvailableBytes();
                if (GameFlow.noSpace(String.valueOf(e.getMessage())) || now < TOOLS_MARGIN) throw new PackEngine.NoSpace(now, need);
                throw new PackEngine.ToolsFailed("the packer did not unpack: " + e, e);
            }
            Log.i(TAG, "unpacked the packer " + version + " in " + (System.nanoTime() - t0) / 1_000_000 + " ms");
        }
        try {
            if (!loaded) {
                System.loadLibrary("nxpack");   // its dependency libpython3.14.so comes from the APK too
                loaded = true;
            }
        } catch (UnsatisfiedLinkError e) {
            throw new PackEngine.ToolsFailed("the packer did not start: " + e, e);
        }
        int rc = init0(new File(dir, "python").getPath());
        if (rc != 0) throw new PackEngine.ToolsFailed("Python did not start (home " + new File(dir, "python") + ", dm_pack_init " + rc + "; logcat has its reason)", null);
        root = dir;
        return root;
    }

    private static void unzip(String asset, File to) throws IOException {
        String top = to.getCanonicalPath() + File.separator;
        byte[] buf = new byte[1 << 16];
        try (InputStream in = app.getAssets().open(asset); ZipInputStream z = new ZipInputStream(in)) {
            ZipEntry e;
            while ((e = z.getNextEntry()) != null) {
                File f = new File(to, e.getName());
                if (!f.getCanonicalPath().startsWith(top)) throw new IOException(asset + ": entry outside its folder: " + e.getName());
                if (e.isDirectory()) { f.mkdirs(); continue; }
                f.getParentFile().mkdirs();
                try (OutputStream out = new FileOutputStream(f)) {
                    int n;
                    while ((n = z.read(buf)) > 0) out.write(buf, 0, n);
                }
            }
        }
    }

    private static void log(String path, String text) {
        try {
            Files.write(new File(path).toPath(), text.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException e) {
            Log.e(TAG, "log " + path + ": " + e + "; the line was: " + text.trim());   // a full disk still leaves the line in logcat
        }
    }
}
