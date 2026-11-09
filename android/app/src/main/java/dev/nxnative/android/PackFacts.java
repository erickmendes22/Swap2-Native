package dev.nxnative.android;

/**
 * What a game card's check found in its pack (MainActivity.check, off the main thread), for GameFlow.decide. A plain value: the JVM test builds one by hand.
 */
final class PackFacts {
    boolean checked;          // the check has run (else the card says Checking)
    boolean profile = true;   // the APK (or Switch2/profiles) has the game's profile
    boolean dump;             // the game folder is a dump Prepare can start from (Pack.isDump)
    boolean pack;             // the pack reads (Pack.read)
    boolean unfinished;       // a module's rewrite did not finish (Pack.unfinishedModule)
    boolean build;            // the pack's code is of another game build (PackCheck.build)
    boolean mods;             // the mods changed since the code was rewritten (PackCheck.mods)
    Boolean code;             // PackCheck.code: this APK's rewriter made it (FALSE: other tools, a pack from another device; null: cannot tell)
    boolean shadersMissing;   // no current shader library (Pack.libraryProblem)
    boolean playable;         // another version, same Vulkan ABI and valid tables: playable without translation
    boolean legacy;           // ... or one from before versioned updates (Pack.legacyLibrary)
    boolean shadersImported;  // no pack yet, its shader library imported (ShaderZip.ready): Prepare only rewrites the code
    boolean deltaKnown;       // the profile's delta manifest knows the pack's older library (Ondevice.deltaShaders >= 0): an update needs no question
    // What a Prepare of it would do now, for its expected time (PrepareTime.seconds): the game's shader map (Profile.shaderTotal), the shaders it translates (0: kept
    // or imported; an older library's update: the delta manifest's count, which may be 0; -1: not known), whether it makes the shader library (the split and the
    // shaders step run, even for 0 to translate) and whether it rewrites the code too
    int mapShaders;
    int toTranslate = -1;
    boolean shaders;
    boolean rewrite;

    PackFacts() {}

    /** The facts of a card not checked yet */
    static PackFacts unchecked(boolean profile) {
        PackFacts f = new PackFacts();
        f.profile = profile;
        return f;
    }
}
