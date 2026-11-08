package dev.nxnative.android;

/**
 * PrepareTime on the JVM, driven by dm/tools/tests/test_android_prepare_time.py: a preparation's expected time from the shaders it translates and the phone's
 * rates, the time left of a running job, the smoothed step rate and the time's text (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Expected time"). Prints "ok &lt;cases&gt;",
 * or the first case that fails and exits 1.
 */
public final class PrepareTimeJvmTest {
    private static int n;

    private static void eq(String what, Object want, Object have) {
        n++;
        if (!String.valueOf(want).equals(String.valueOf(have))) {
            System.out.println("FAIL " + what + ": want " + want + ", have " + have);
            System.exit(1);
        }
    }

    private static void near(String what, double want, double have) {
        n++;
        if (Math.abs(want - have) > 1e-9) {
            System.out.println("FAIL " + what + ": want " + want + ", have " + have);
            System.exit(1);
        }
    }

    public static void main(String[] args) {
        // the time's text: rounded up, coarser as it grows
        eq("text 0", "1 min", PrepareTime.text(0));
        eq("text 12 min", "12 min", PrepareTime.text(12 * 60));
        eq("text 12 min 1 s", "13 min", PrepareTime.text(12 * 60 + 1));
        eq("text 23 min", "25 min", PrepareTime.text(23 * 60));
        eq("text 61 min", "1 h 10 min", PrepareTime.text(61 * 60));
        eq("text 2 h 30", "2 h 30 min", PrepareTime.text(150 * 60));
        eq("text 6 h", "6 h", PrepareTime.text(6 * 3600));
        eq("text 6 h 5", "6 h 30 min", PrepareTime.text(6 * 3600 + 300));
        eq("approx", "~45 min", PrepareTime.approx(42 * 60));

        // the SoC classes: the Snapdragon 8 Elite's rates are the measured ones
        PrepareTime.Rates elite = PrepareTime.defaults("SM8750");
        near("8 Elite shader", 0.30, elite.shader);
        near("8 Elite split", 0.045, elite.split);
        near("8 Elite rewrite", 240, elite.rewrite);
        eq("8 Elite case", elite.toString(), PrepareTime.defaults("sm8750-ac").toString());
        eq("unknown is slower", true, PrepareTime.defaults(null).shader > PrepareTime.defaults("SM8550").shader && PrepareTime.defaults("SM8550").shader > PrepareTime.defaults("SM8650").shader
                && PrepareTime.defaults("SM8650").shader > elite.shader);

        // a whole Prepare: Zelda: Ocarina of Time (42,339 shaders) on the 8 Elite, Pokopia (131,426, no delta manifest: all of them)
        long zelda = PrepareTime.seconds(elite, 42339, 42339, true, true);
        eq("zelda seconds", Math.round(10 + 60 + 240 + 0.045 * 42339 + 0.30 * 42339 + 60), zelda);
        eq("zelda text", "4 h 10 min", PrepareTime.text(zelda));
        long pokopia = PrepareTime.seconds(elite, 131426, 131426, true, true);
        eq("pokopia text", "13 h", PrepareTime.text(pokopia));
        eq("pokopia longer", true, pokopia > 2.5 * zelda);
        // kept shaders cost nothing: imported (only the code), a library kept; a delta update of 0 still splits and writes the library, a delta of 500 (the split
        // reads every shader of the map)
        eq("imported", "6 min", PrepareTime.text(PrepareTime.seconds(elite, 42339, 0, false, true)));
        eq("kept", 70L, PrepareTime.seconds(elite, 42339, 0, false, false));
        eq("delta 0", Math.round(10 + 60 + 0.045 * 42339 + 60), PrepareTime.seconds(elite, 42339, 0, true, false));
        eq("delta 500", Math.round(10 + 60 + 0.045 * 42339 + 0.30 * 500 + 60), PrepareTime.seconds(elite, 42339, 500, true, false));

        // time left: the shaders step at its measured rate, then the pack
        boolean[] atShaders = {true, true, true, false, false};
        eq("left shaders measured", Math.round((42339 - 17359) * 0.2 + 60 + 60), PrepareTime.remaining(elite, atShaders, 3, 17359, 42339, 0.2, 100, 42339, 42339, false));
        eq("left shaders not measured", Math.round((42339 - 17359) * 0.30 + 60 + 60), PrepareTime.remaining(elite, atShaders, 3, 17359, 42339, -1, 5, 42339, 42339, false));
        eq("left library", Math.round(60 - 20 + 60.0), PrepareTime.remaining(elite, atShaders, 3, 42339, 42339, 0.2, 20, 42339, 42339, true));
        // the rewrite (no count) less the time it ran, then the split and every shader
        boolean[] atRewrite = {true, false, false, false, false};
        eq("left rewrite", Math.round(240 - 100 + 0.045 * 42339 + 0.30 * 42339 + 60 + 60), PrepareTime.remaining(elite, atRewrite, 1, 0, 0, -1, 100, 42339, 42339, false));
        eq("left rewrite overdue", Math.round(24 + 0.045 * 42339 + 0.30 * 42339 + 60 + 60), PrepareTime.remaining(elite, atRewrite, 1, 0, 0, -1, 1000, 42339, 42339, false));
        // the split with a count and no rate yet: its share left
        boolean[] atSplit = {true, true, false, false, false};
        eq("left split", Math.round(0.045 * 42339 / 2 + 0.30 * 42339 + 60 + 60), PrepareTime.remaining(elite, atSplit, 2, 93000, 186000, -1, 600, 42339, 42339, false));
        // a delta update's split (Zelda's manifest: 55 to translate) charges its 55 shaders, not the map's
        eq("left delta split", Math.round(0.045 * 42339 + 0.30 * 55 + 60 + 60), PrepareTime.remaining(elite, atSplit, 2, 0, 0, -1, -1, 55, 42339, false));
        // an imported job's shaders cost nothing; a done job has nothing left
        eq("left imported", 60L, PrepareTime.remaining(elite, new boolean[] {true, true, true, true, false}, 4, 0, 0, -1, -1, 0, 42339, false));
        eq("left done", -1L, PrepareTime.remaining(elite, new boolean[] {true, true, true, true, true}, 4, 1, 1, -1, -1, 0, 42339, false));

        // the meter: the first line is its anchor, windows of 20 s, smoothed by 0.3; a count that goes back starts it over
        PrepareTime.Meter m = new PrepareTime.Meter();
        m.feed(0, 0);
        m.feed(10_000, 50);
        near("meter before a window", -1, m.rate());
        m.feed(20_000, 100);
        near("meter first window", 0.2, m.rate());
        m.feed(40_000, 200);
        near("meter steady", 0.2, m.rate());
        m.feed(60_000, 250);
        near("meter smoothed", 0.2 * 0.7 + 0.4 * 0.3, m.rate());
        near("meter mean", 60.0 / 250, m.mean());
        near("meter covers", 60, m.measuredSeconds());
        m.feed(70_000, 10);   // the tool started over: a new anchor
        m.feed(80_000, 60);
        near("meter after restart", 0.2 * 0.7 + 0.4 * 0.3, m.rate());
        m.feed(90_000, 110);
        near("meter after restart window", (0.2 * 0.7 + 0.4 * 0.3) * 0.7 + 0.2 * 0.3, m.rate());
        eq("meter windows", 4, m.windows());

        // learning: the first measurement as it is, later ones by a fifth, nonsense ignored
        near("learn first", 0.3, PrepareTime.learn(0, 0.3));
        near("learn later", 0.28, PrepareTime.learn(0.3, 0.2));
        near("learn nonsense", 0.3, PrepareTime.learn(0.3, -1));
        near("learn infinite", 0.3, PrepareTime.learn(0.3, Double.POSITIVE_INFINITY));
        near("learn NaN", 0.3, PrepareTime.learn(0.3, Double.NaN));

        System.out.println("ok " + n);
    }
}
