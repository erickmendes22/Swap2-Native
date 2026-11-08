package dev.nxnative.android;

import java.util.Locale;

/**
 * How long a preparation takes on this phone (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Expected time"), as pure arithmetic: before it starts (the card, the Prepare
 * question) from the shaders it translates and this phone's rates, and while it runs from the current step's measured rate ({@link Meter}).
 * <ul>
 * <li>{@link Rates}: seconds per shader translated, seconds per shader of the game's map for the split (it reads the whole RomFS whatever the delta), and the
 * rewrite's (each game's own: Job.rates with its title ID) and the pack step's seconds. A phone that ran a job has its own (PackService learns them, Job.rates reads them); one that has not starts from its
 * SoC class's ({@link #defaults}).</li>
 * <li>Kept shaders cost nothing: an imported library (Import shaders…) or the delta manifest's count (Profile.delta, ShaderLibs.toTranslate) is what the
 * caller passes as the shaders to translate.</li>
 * </ul>
 * No Android classes: dm/tools/tests/test_android_prepare_time.py runs it on the JVM (PrepareTimeJvmTest).
 */
final class PrepareTime {
    private PrepareTime() {}

    /** One phone's rates (seconds) */
    static final class Rates {
        final double shader, split, rewrite, pack;

        Rates(double shader, double split, double rewrite, double pack) { this.shader = shader; this.split = split; this.rewrite = rewrite; this.pack = pack; }

        @Override public String toString() { return String.format(Locale.ROOT, "shader %.3f split %.4f rewrite %.0f pack %.0f", shader, split, rewrite, pack); }
    }

    /** The identify step, and the library written and checked at the end of the shaders step (seconds) */
    static final double IDENTIFY = 10, LIBRARY = 60;

    /**
     * The rates of a SoC class (Build.SOC_MODEL), until this phone measured its own. Measured on a Snapdragon 8 Elite (SM8750, RedMagic 11 Air, Zelda: Ocarina of
     * Time, 2026-11-07): 41,927 shaders translated in two runs, 18,432 in 80 min (19:13:36 to the pause at 20:33:28, 0.26 s each) and 23,488 in 2 h 11 min (20:43:54
     * to the pack step at 22:54:40, 0.33 s each: the phone slows as it heats up), 0.30 s each over both (6 translators at a time); the split of 42,339 shaders in
     * 32 min (0.045 s a shader of the map), the code rewrite in 241 s (main 180 s, sdk 55 s, subsdk0 6 s). The other classes are scaled from it by their CPU's
     * speed (estimates, not measured)
     */
    static Rates defaults(String soc) {
        String s = soc == null ? "" : soc.toUpperCase(Locale.ROOT);
        if (s.startsWith("SM8750") || s.startsWith("SM8850") || s.startsWith("SM8845")) return new Rates(0.30, 0.045, 240, 60);   // 8 Elite, 8 Elite Gen 5
        if (s.startsWith("SM8650") || s.startsWith("SM8635") || s.startsWith("SM8735")) return new Rates(0.39, 0.058, 310, 75);   // 8 Gen 3, 8s Gen 3 / Gen 4
        if (s.startsWith("SM8550") || s.startsWith("SM8475") || s.startsWith("SM7675")) return new Rates(0.50, 0.072, 390, 90);   // 8 Gen 2, 8+ Gen 1, 7+ Gen 3
        return new Rates(0.63, 0.09, 480, 120);   // anything else: slower than the classes above
    }

    /**
     * A new rate from a measured one: the first measurement is taken as it is, later ones move the kept rate by a fifth (one hot run, or a game with heavier
     * shaders, does not undo what the phone showed before). Nonsense (not positive, not finite) keeps the old one
     */
    static double learn(double old, double measured) {
        if (!(measured > 0) || Double.isInfinite(measured)) return old;
        return old > 0 ? old * 0.8 + measured * 0.2 : measured;
    }

    /**
     * A whole preparation's seconds: the code rewritten (code), the shader library made (shaders: the split, toTranslate shaders translated and the library
     * written; mapShaders: the game's map, Profile.shaderTotal; toTranslate 0 when the delta manifest keeps every shader, the split still runs), then the pack step.
     * shaders false: the library is kept or imported, neither the split nor the translation runs
     */
    static long seconds(Rates r, int mapShaders, int toTranslate, boolean shaders, boolean code) {
        double s = IDENTIFY + r.pack;
        if (code) s += r.rewrite;
        if (shaders) s += r.split * Math.max(mapShaders, toTranslate) + r.shader * Math.max(0, toTranslate) + LIBRARY;
        return Math.round(s);
    }

    /** A step's seconds when it has not started (by Job.STEPS index: identify, rewrite, split, shaders, pack) */
    static double stepSeconds(Rates r, int step, int mapShaders, long toTranslate) {
        switch (step) {
            case 0: return IDENTIFY;
            case 1: return r.rewrite;
            case 2: return r.split * mapShaders;
            case 3: return r.shader * Math.max(0, toTranslate) + LIBRARY;   // a step not done writes the library, whatever it translates
            default: return r.pack;
        }
    }

    /**
     * What is left of a job (seconds), -1 when nothing is (every step done). done: each step's state; cur: the step shown (Job.current); curDone / curTotal: its count
     * (total 0 or 1: no count); curRate: its measured seconds per unit (Meter, &lt;= 0: not measured yet); curElapsed: its seconds since it started in this run (-1:
     * not running); toTranslate: the shaders step's total (Job.shadersTotal); mapShaders: the game's map; finishing: the shaders step is past its translation
     * (writing or checking the library). A step with a count and a measured rate takes its count left at that rate; one with a count and none, its default share of
     * what is left; one without a count, its default less the time it has run (a tenth of it at least: it has not ended yet)
     */
    static long remaining(Rates r, boolean[] done, int cur, long curDone, long curTotal, double curRate, double curElapsed, long toTranslate, int mapShaders,
                          boolean finishing) {
        double s = 0;
        boolean any = false;
        for (int i = 0; i < done.length; i++) {
            if (done[i]) continue;
            any = true;
            double full = stepSeconds(r, i, mapShaders, toTranslate);
            if (i != cur) { s += full; continue; }
            if (i == 3 && finishing) { s += curElapsed >= 0 ? Math.max(LIBRARY * 0.1, LIBRARY - curElapsed) : LIBRARY; continue; }
            if (curTotal > 1) {
                long left = Math.max(0, curTotal - Math.min(curDone, curTotal));
                double tail = i == 3 ? LIBRARY : 0;
                if (curRate > 0) s += left * curRate + tail;
                else if (i == 3) s += left * r.shader + tail;
                else s += full * left / curTotal;
            } else if (curElapsed >= 0) s += Math.max(full * 0.1, full - curElapsed);
            else s += full;
        }
        return any ? Math.round(s) : -1;
    }

    /**
     * The time as people say it, the same in English and Portuguese: "12 min", "2 h 30 min", "6 h". Rounded up, and coarser as it grows (a minute under 20 min,
     * 5 min under an hour, 10 min under 5 h, half an hour beyond); 1 min at least
     */
    static String text(long seconds) {
        long m = Math.max(1, (seconds + 59) / 60);
        long step = m < 20 ? 1 : m < 60 ? 5 : m < 300 ? 10 : 30;
        m = (m + step - 1) / step * step;
        if (m < 60) return m + " min";
        long h = m / 60, rest = m % 60;
        return rest == 0 ? h + " h" : h + " h " + rest + " min";
    }

    /** "~12 min", for the card and the short lines */
    static String approx(long seconds) { return "~" + text(seconds); }

    /**
     * A step's measured rate, smoothed: seconds per unit of its progress lines over windows of at least {@link #WINDOW_MS} each (one translator call is 64 shaders,
     * a window several calls), each window moving the rate by {@link #SMOOTH}. The first line it sees is its anchor only: the time from the step's start to it is the
     * tool's start-up, not its rate. A count that goes back (the tool started over) starts it over
     */
    static final class Meter {
        static final long WINDOW_MS = 20_000;
        static final double SMOOTH = 0.3;
        private long t0 = -1, d0;
        private double rate = -1;
        private int windows;
        private long measuredMs, measuredUnits;   // every window's time and count: the step's mean rate for the phone's rates (learn)

        void feed(long tMs, long done) {
            if (t0 < 0 || done < d0) { t0 = tMs; d0 = done; return; }
            long dt = tMs - t0, dd = done - d0;
            if (dt < WINDOW_MS || dd <= 0) return;
            double inst = dt / 1000.0 / dd;
            rate = rate < 0 ? inst : rate * (1 - SMOOTH) + inst * SMOOTH;
            windows++;
            measuredMs += dt;
            measuredUnits += dd;
            t0 = tMs;
            d0 = done;
        }

        /** Seconds per unit, -1 before the first window */
        double rate() { return rate; }

        int windows() { return windows; }

        /** The mean over every window (seconds per unit), -1 before the first */
        double mean() { return measuredUnits > 0 ? measuredMs / 1000.0 / measuredUnits : -1; }

        /** The seconds the windows cover */
        double measuredSeconds() { return measuredMs / 1000.0; }
    }
}
