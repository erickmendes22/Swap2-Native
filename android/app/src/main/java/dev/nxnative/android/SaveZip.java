package dev.nxnative.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * A game's save as one .zip, in and out (its Options menu and its settings' Saves: Import save from another emulator…, Export save…), over SaveStore. No Android
 * classes: the JVM test (LauncherJvmTest, run by dm/tools/tests/test_android_saves.py) runs it.
 * <ul>
 * <li><b>Import</b> takes a .zip, never a folder (a folder picked before was an emulator's whole folder once, and its copy filled a phone: ENOSPC). The zip is listed
 *     first (by its central directory when it has a path, else read through once as a stream), every name checked (no absolute path, no "..", no name twice:
 *     zip-slip and case clashes refused), and this game's save is found in it ({@link #find}): a folder named the title ID (any case) holding files, as Lichii, Eden
 *     and yuzu keep it (nand/user/save/0000000000000000/&lt;user&gt;/&lt;TITLE ID&gt;/ with account.sav and slot_XX, their device save under the all-zero user beside it)
 *     and as Export writes it; else the files at the zip's top level, or its one top folder (a Ryujinx save folder's 0/), unless they hold an emulator's own folders
 *     or keys. Only that part (and its device save: &lt;part&gt;_device beside it, or the all-zero user's) is extracted, into &lt;save&gt;.import beside the
 *     save, its entry count, each file's size and the total checked while it is written (never more than {@link SaveStore#MAX_SAVE_BYTES}), all under the save's
 *     lock; SaveStore's verified restore then takes it (the current save backed up first, the verified copy, the journal), and the staging folder goes.</li>
 * <li><b>Export</b> writes &lt;TITLE ID&gt;/ (and &lt;TITLE ID&gt;_device/) into swap2-save-&lt;TITLE ID&gt;-&lt;yyyyMMdd-HHmmss&gt;.zip.partial, reads it back with the
 *     importer's own reader (it must find that part, with every file's SHA-256 and size as the save's), checks the save did not change meanwhile, and only then gives it
 *     its name. The save is only read.</li>
 * </ul>
 */
final class SaveZip {
    static final String PREFIX = "swap2-save-", PARTIAL = ".partial", IMPORT_SUFFIX = ".import";
    /** The entries of the part taken (a save holds a few dozen files) */
    static final int MAX_ENTRIES = 10000;
    /** The entries of the whole zip listed to find the save in it (an emulator's folder zipped whole) */
    static final int MAX_LISTED = 200000;
    /** One file of a save (the host gives a game 256 MB of save data in all: hle_fs.c GetSaveDataSizeMax) */
    static final long MAX_FILE = 512L << 20;
    /** A zip without a path is read whole to list it: past this many bytes it is no save zip */
    static final long MAX_STREAM = 4L << 30;
    /** Folders of an emulator that hold folders named by title ID that are not saves (mods, caches, dumps): a title ID folder below one is not taken */
    static final Set<String> NOT_SAVES = new HashSet<>(Arrays.asList("load", "dump", "shader", "shaders", "cache", "contents", "mods", "exefs", "romfs", "atmosphere",
            "screenshots", "game_list", "log", "logs", "registered", "placeholder", "games", "work"));

    enum Why { NOT_ZIP, UNSAFE_NAME, DUPLICATE, NONE_FOUND, TOO_BIG, ZIP_TOO_BIG, TOO_MANY, FILE_TOO_BIG, NO_SPACE, NO_SAVE, READ_BACK, CHANGED }

    /** A failure the launcher words in the user's language (SaveUi.message), its args the values the wording takes (names, paths, sizes: never English words) */
    static final class Failure extends IOException {
        private static final long serialVersionUID = 1L;
        final Why why;
        final String[] args;

        Failure(Why why, String message, String... args) {
            super(message);
            this.why = why;
            this.args = args;
        }
    }

    private SaveZip() {}

    // ---- Where the zip comes from ----

    /** Opens the zip again (a picked document: ContentResolver.openInputStream) */
    interface Opener { InputStream open() throws IOException; }

    /** A zip by its path (read by its central directory), or a stream opened as often as needed (a document without a path) */
    static final class Source {
        final File file;
        final Opener opener;
        final String name;

        Source(File file) { this.file = file; opener = null; name = file.getName(); }

        Source(Opener o, String name) { file = null; opener = o; this.name = name; }
    }

    /** One entry: its checked name (folders without their trailing /), whether it is a folder, its size (read when listed as a stream) and its time */
    static final class Item {
        final String name;
        final boolean dir;
        final long size, time;

        Item(String name, boolean dir, long size, long time) { this.name = name; this.dir = dir; this.size = size; this.time = time; }
    }

    /**
     * A zip entry's name made safe: '\' read as '/', "." and empty segments dropped; null for an entry to leave out (__MACOSX/, .DS_Store, the top folder itself).
     * Refused (UNSAFE_NAME): an absolute name, a drive letter, "..", a ':' or a control character
     */
    static String clean(String raw) throws Failure {
        String s = raw.replace('\\', '/');
        if (s.startsWith("/") || s.matches("^[A-Za-z]:.*")) throw new Failure(Why.UNSAFE_NAME, "the zip has an absolute name: " + raw, raw);
        StringBuilder b = new StringBuilder();
        for (String seg : s.split("/")) {
            if (seg.isEmpty() || seg.equals(".")) continue;
            if (seg.equals("..")) throw new Failure(Why.UNSAFE_NAME, "the zip has a name going up (..): " + raw, raw);
            for (int i = 0; i < seg.length(); i++) {
                char c = seg.charAt(i);
                if (c < 0x20 || c == ':' || c == 0x7f) throw new Failure(Why.UNSAFE_NAME, "the zip has a name with a ':' or a control character: " + raw, raw);
            }
            if (b.length() > 0) b.append('/');
            b.append(seg);
        }
        String n = b.toString();
        if (n.isEmpty() || n.equals("__MACOSX") || n.startsWith("__MACOSX/") || n.equals(".DS_Store") || n.endsWith("/.DS_Store")) return null;
        return n;
    }

    /** The zip's entries, checked (names, count, no name twice in any case); a stream is read through once (its sizes counted, MAX_STREAM at most) */
    static List<Item> list(Source src) throws IOException {
        List<Item> out = new ArrayList<>();
        if (src.file != null) {
            try (ZipFile z = new ZipFile(src.file)) {
                Enumeration<? extends ZipEntry> en = z.entries();
                while (en.hasMoreElements()) {
                    ZipEntry e = en.nextElement();
                    add(out, e, e.getSize());
                }
            } catch (ZipException | IllegalArgumentException e) {
                throw new Failure(Why.NOT_ZIP, src.name + " is not a .zip: " + e.getMessage(), src.name);
            }
        } else {
            long total = 0;
            byte[] buf = new byte[1 << 16];
            try (InputStream in = src.opener.open(); ZipInputStream z = new ZipInputStream(in)) {
                for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                    long n = 0;
                    for (int k; (k = z.read(buf)) > 0; ) {
                        n += k;
                        if ((total += k) > MAX_STREAM) throw new Failure(Why.ZIP_TOO_BIG, src.name + " holds more than " + SaveStore.size(MAX_STREAM), SaveStore.size(MAX_STREAM));
                    }
                    add(out, e, n);
                }
            } catch (ZipException | IllegalArgumentException e) {
                throw new Failure(Why.NOT_ZIP, src.name + " is not a .zip: " + e.getMessage(), src.name);
            }
            if (out.isEmpty()) throw new Failure(Why.NOT_ZIP, src.name + " is not a .zip (no entries)", src.name);
        }
        // one name once: shared storage ignores case, and a file may not sit where another entry needs a folder
        Map<String, Boolean> seen = new HashMap<>();
        for (Item i : out) {
            String k = i.name.toLowerCase(Locale.ROOT);
            Boolean d = seen.put(k, i.dir);
            if (d != null && !(d && i.dir)) throw new Failure(Why.DUPLICATE, "the zip holds " + i.name + " twice", i.name);
        }
        for (Item i : out) {
            for (int p = i.name.indexOf('/'); p > 0; p = i.name.indexOf('/', p + 1)) {
                if (Boolean.FALSE.equals(seen.get(i.name.substring(0, p).toLowerCase(Locale.ROOT))))
                    throw new Failure(Why.DUPLICATE, "the zip holds " + i.name.substring(0, p) + " as a file and as a folder", i.name.substring(0, p));
            }
        }
        return out;
    }

    private static void add(List<Item> out, ZipEntry e, long size) throws Failure {
        if (out.size() >= MAX_LISTED) throw new Failure(Why.TOO_MANY, "the zip holds more than " + MAX_LISTED + " entries", String.valueOf(MAX_LISTED));
        String n = clean(e.getName());
        if (n != null) out.add(new Item(n, e.isDirectory(), e.isDirectory() ? 0 : Math.max(size, 0), e.getTime()));
    }

    // ---- Finding the save ----

    /** A part of the zip that is a save: its folder ("" for the zip's top level) and its device save's beside it (null when none), with what they hold */
    static final class Part {
        final String prefix;
        String device;
        int files, entries;
        long bytes, newest;

        Part(String prefix) { this.prefix = prefix; }

        /** Whether an entry belongs to this part's main save (as a relative path), or its device save; null when to neither */
        String[] place(String name) {
            if (prefix.isEmpty()) return new String[] {SaveStore.MAIN, name};
            if (below(name, prefix)) return new String[] {SaveStore.MAIN, name.substring(prefix.length() + 1)};
            if (device != null && below(name, device)) return new String[] {SaveStore.DEVICE, name.substring(device.length() + 1)};
            return null;
        }

        /** Whether name is below the folder dir, in any case (shared storage ignores it) */
        private static boolean below(String name, String dir) {
            return name.length() > dir.length() + 1 && name.charAt(dir.length()) == '/' && name.regionMatches(true, 0, dir, 0, dir.length());
        }

        /** Whether this part sits below a folder named save (an emulator's nand/user/save) */
        boolean underSave() {
            for (String s : prefix.split("/")) if (s.equalsIgnoreCase("save")) return true;
            return false;
        }
    }

    /** Counts what the part holds (its main save and its device save) */
    private static Part count(Part p, List<Item> items) {
        for (Item i : items) {
            if (p.place(i.name) == null) continue;
            p.entries++;
            if (!i.dir) { p.files++; p.bytes += i.size; p.newest = Math.max(p.newest, i.time); }
        }
        return p;
    }

    /**
     * A part with its device save: &lt;prefix&gt;_device beside it when the zip has that folder, even empty (Export writes it as the save has it: the host makes
     * &lt;save&gt;_device when a game mounts its device save, before the game writes to it), else other (the yuzu family's device save, see {@link #zeroUser}), else none
     */
    private static Part part(String prefix, String other, List<Item> items) {
        Part p = new Part(prefix);
        if (!prefix.isEmpty()) {
            String dev = prefix + SaveStore.DEVICE_SUFFIX;
            for (Item i : items)
                if (i.dir && i.name.equalsIgnoreCase(dev) || i.name.regionMatches(true, 0, dev + "/", 0, dev.length() + 1)) { p.device = i.name.substring(0, dev.length()); break; }
            if (p.device == null) p.device = other;
        }
        return count(p, items);
    }

    /** The user ID of the yuzu family's device save (all zero): its saves are save/0000000000000000/&lt;user ID&gt;/&lt;TITLE ID&gt; */
    static final String ZERO_USER = "00000000000000000000000000000000";

    /** Whether a title ID folder is the yuzu family's device save (Eden, Lichii, yuzu): save/0000000000000000/00000000000000000000000000000000/&lt;TITLE ID&gt; */
    static boolean zeroUser(String prefix) {
        String[] s = prefix.split("/");
        return s.length >= 2 && s[s.length - 2].equals(ZERO_USER);
    }

    /** The folder two levels above a title ID folder (the one holding the user folders); "" when there is none */
    private static String slot(String prefix) {
        String[] s = prefix.split("/");
        return s.length < 3 ? "" : String.join("/", Arrays.copyOfRange(s, 0, s.length - 2)).toLowerCase(Locale.ROOT);
    }

    /** Ryujinx's save folder (bis/user/save/&lt;number&gt;/): the committed save in 0/, its working copy in 1/, these files beside them */
    static final Set<String> RYUJINX = new HashSet<>(Arrays.asList("0", "1", "_", ".lock", "extradata0", "extradata1"));

    /** The folder's 0/ when the folder ("" for the zip's top level) is a Ryujinx save folder whose 0/ holds files; else null */
    private static String ryujinx(String dir, List<Item> items) {
        String pre = dir.isEmpty() ? "" : dir + "/", zero = pre + "0";
        boolean any = false, files = false;
        for (Item i : items) {
            if (!i.name.regionMatches(true, 0, pre, 0, pre.length()) || i.name.length() == pre.length()) continue;
            String rest = i.name.substring(pre.length()), child = rest.contains("/") ? rest.substring(0, rest.indexOf('/')) : rest;
            if (!RYUJINX.contains(child.toLowerCase(Locale.ROOT))) return null;
            any = true;
            if (!i.dir && rest.length() > 2 && rest.startsWith("0/")) files = true;
        }
        return any && files ? zero : null;
    }

    /** Folders of an emulator's own folder (a zip of it is no save): yuzu family's nand and sdmc, Ryujinx's bis, the keys */
    static final Set<String> EMULATOR = new HashSet<>(Arrays.asList("nand", "sdmc", "bis", "keys"));

    /** Whether a folder name is an emulator's (EMULATOR) or a title, save or user ID (16 or 32 hex digits: no game names a save folder so) */
    private static boolean emulatorFolder(String name) {
        String l = name.toLowerCase(Locale.ROOT);
        return EMULATOR.contains(l) || l.matches("[0-9a-f]{16}|[0-9a-f]{32}");
    }

    /** Whether a part taken without a title ID folder holds an emulator's folders or keys (a zip of an emulator's folder, or of another game's save) */
    private static boolean notASave(Part p, List<Item> items) {
        for (Item i : items) {
            String[] at = p.place(i.name);
            if (at == null) continue;
            String[] seg = at[1].split("/");
            for (int k = 0; k < seg.length; k++) {
                boolean folder = i.dir || k < seg.length - 1;
                if (folder ? emulatorFolder(seg[k]) : seg[k].toLowerCase(Locale.ROOT).endsWith(".keys")) return true;
            }
        }
        return false;
    }

    /**
     * The parts of the zip that may be this game's save, the likeliest first: the folders named the title ID (any case; none below an emulator's mods, caches or dumps:
     * NOT_SAVES) that hold files, those below a "save" folder first, then the newest; the yuzu family's device save (zeroUser) is never one: it is the device save of
     * the users' saves beside it. Without such a folder: the zip's top level when files sit there, else its one top folder (a &lt;folder&gt;_device beside it is its
     * device save; a Ryujinx save folder gives its 0/), and neither when it holds an emulator's folders, keys or folders named by an ID (notASave: a zip of an
     * emulator's folder, or of another game's save). Empty when none
     */
    static List<Part> find(List<Item> items, String titleId) {
        List<Part> out = new ArrayList<>();
        Map<String, String> folders = new LinkedHashMap<>();   // lower case → as written: every folder named the title ID
        for (Item i : items) {
            String[] seg = i.name.split("/");
            int depth = i.dir ? seg.length : seg.length - 1;   // the folders this entry is in (and a folder entry itself)
            for (int k = 0; k < depth; k++) {
                if (NOT_SAVES.contains(seg[k].toLowerCase(Locale.ROOT))) break;
                if (!seg[k].equalsIgnoreCase(titleId)) continue;
                String pre = String.join("/", Arrays.copyOfRange(seg, 0, k + 1));
                folders.putIfAbsent(pre.toLowerCase(Locale.ROOT), pre);
            }
        }
        Map<String, String> devices = new HashMap<>();   // slot → the yuzu family's device save there, when it holds files
        for (String pre : folders.values())
            if (zeroUser(pre) && count(new Part(pre), items).files > 0) devices.put(slot(pre), pre);
        for (String pre : folders.values()) {
            if (zeroUser(pre)) continue;
            Part p = part(pre, slot(pre).isEmpty() ? null : devices.get(slot(pre)), items);
            if (p.files > 0) out.add(p);
        }
        if (!out.isEmpty()) {
            out.sort((a, b) -> a.underSave() != b.underSave() ? (a.underSave() ? -1 : 1) : a.newest != b.newest ? Long.compare(b.newest, a.newest) : a.prefix.compareTo(b.prefix));
            return out;
        }
        if (!devices.isEmpty()) return out;   // only a device save: importing it as the main save would be wrong
        boolean rootFiles = false;
        Set<String> tops = new java.util.LinkedHashSet<>();
        for (Item i : items) {
            int s = i.name.indexOf('/');
            if (s < 0 && !i.dir) rootFiles = true;
            tops.add(s < 0 ? (i.dir ? i.name : null) : i.name.substring(0, s));
        }
        tops.remove(null);
        Part p = null;
        String ry = ryujinx("", items);
        if (ry != null) p = part(ry, null, items);
        else if (rootFiles) p = count(new Part(""), items);
        else {
            List<String> l = new ArrayList<>(tops);
            l.removeIf(t -> t.toLowerCase(Locale.ROOT).endsWith(SaveStore.DEVICE_SUFFIX) && tops.contains(t.substring(0, t.length() - SaveStore.DEVICE_SUFFIX.length())));
            if (l.size() == 1) {
                ry = ryujinx(l.get(0), items);
                if (ry != null) p = part(ry, null, items);
                else if (!emulatorFolder(l.get(0))) p = part(l.get(0), null, items);
            }
        }
        if (p != null && p.files > 0 && !notASave(p, items)) out.add(p);
        return out;
    }

    /** Why a part may not be taken (FILE_TOO_BIG, TOO_BIG, TOO_MANY), by the sizes the listing gives; null when it may */
    static Failure refuse(Part p, List<Item> items) {
        for (Item i : items)   // first: one file far too big says more than the total it makes
            if (!i.dir && i.size > MAX_FILE && p.place(i.name) != null) return new Failure(Why.FILE_TOO_BIG, i.name + " is larger than " + SaveStore.size(MAX_FILE), i.name, SaveStore.size(MAX_FILE));
        if (p.bytes > SaveStore.MAX_SAVE_BYTES) return new Failure(Why.TOO_BIG, where(p) + " holds " + SaveStore.size(p.bytes), where(p), SaveStore.size(p.bytes), SaveStore.size(SaveStore.MAX_SAVE_BYTES));
        if (p.entries > MAX_ENTRIES) return new Failure(Why.TOO_MANY, where(p) + " holds more than " + MAX_ENTRIES + " entries", String.valueOf(MAX_ENTRIES));
        return null;
    }

    /** A part's place in the zip, for the messages ("" for its top level) */
    static String where(Part p) { return p.prefix.isEmpty() ? "/" : p.prefix + "/"; }

    /** The parts of the zip a user may import, the likeliest first (find, without those over the limits); a Failure when there is none */
    static List<Part> plan(Source src, String titleId) throws IOException {
        List<Item> items = list(src);
        List<Part> all = find(items, titleId), ok = new ArrayList<>();
        Failure first = null;
        for (Part p : all) {
            Failure f = refuse(p, items);
            if (f == null) ok.add(p);
            else if (first == null) first = f;
        }
        if (!ok.isEmpty()) return ok;
        if (first != null) throw first;
        throw new Failure(Why.NONE_FOUND, "no save of " + titleId + " in " + src.name, src.name, titleId.toUpperCase(Locale.ROOT));
    }

    // ---- Import ----

    /** The staging folder of an import beside the save: &lt;save&gt;.import (its device save &lt;save&gt;.import_device beside it) */
    static File staging(File save) { return new File(save.getAbsoluteFile().getParentFile(), save.getName() + IMPORT_SUFFIX); }

    /**
     * Imports that part of the zip into the save: extracted (limits checked as it is written) into the staging folder under the save's lock, then
     * SaveStore.restoreLocked (the current save backed up first, the verified copy, the journal); the staging folder goes in every case
     */
    static SaveStore.Restored importZip(Source src, Part part, File save, File backups, String stamp) throws IOException {
        File st = staging(save), sd = SaveStore.device(st);
        try (SaveStore.Lock l = SaveStore.lock(save)) {
            SaveStore.recoverLocked(save);
            SaveStore.clearLeftoversLocked(save);   // a stopped import's staging folder and a stopped restore's copy, first: their space is back
            File dir = save.getAbsoluteFile().getParentFile();
            if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
            long free = dir.getUsableSpace(), need = 3 * part.bytes + (64L << 20);   // the staging folder, the copy beside the save and the backup of the old one
            if (free > 0 && free < need)
                throw new Failure(Why.NO_SPACE, "importing needs " + SaveStore.size(need) + " free beside the save, there are " + SaveStore.size(free), SaveStore.size(need), dir.getPath(), SaveStore.size(free));
            try {
                if (!st.mkdirs()) throw new IOException("cannot create " + st);
                if (part.device != null && !sd.mkdirs()) throw new IOException("cannot create " + sd);
                extract(src, part, st, sd);
                if (!SaveStore.hasFiles(st) && !SaveStore.hasFiles(sd)) throw new Failure(Why.NONE_FOUND, "no file of the save in " + src.name, src.name, "");
                return SaveStore.restoreLocked(st, save, backups, stamp);
            } finally {
                SaveStore.deleteTree(st);
                SaveStore.deleteTree(sd);
            }
        }
    }

    /** Writes the part's entries into main (and device), counting entries, each file's bytes and the total as they are written */
    static void extract(Source src, Part part, File main, File device) throws IOException {
        long[] total = {0};
        int[] entries = {0};
        Set<String> written = new HashSet<>();
        if (src.file != null) {
            try (ZipFile z = new ZipFile(src.file)) {
                Enumeration<? extends ZipEntry> en = z.entries();
                while (en.hasMoreElements()) {
                    ZipEntry e = en.nextElement();
                    File to = target(e, part, main, device, entries, written);
                    if (to == null) continue;
                    if (e.isDirectory()) { mkdirs(to); continue; }
                    try (InputStream in = z.getInputStream(e)) { write(in, to, e, total); }
                }
            } catch (ZipException | IllegalArgumentException e) {
                throw new Failure(Why.NOT_ZIP, src.name + " is not a .zip: " + e.getMessage(), src.name);
            }
            return;
        }
        try (InputStream in = src.opener.open(); ZipInputStream z = new ZipInputStream(in)) {
            for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                File to = target(e, part, main, device, entries, written);
                if (to == null) continue;
                if (e.isDirectory()) mkdirs(to);
                else write(z, to, e, total);
            }
        } catch (ZipException | IllegalArgumentException e) {
            throw new Failure(Why.NOT_ZIP, src.name + " is not a .zip: " + e.getMessage(), src.name);
        }
    }

    /** Where an entry of the part goes (inside main or device: the names are checked again), null when it is not the part's */
    private static File target(ZipEntry e, Part part, File main, File device, int[] entries, Set<String> written) throws IOException {
        String n = clean(e.getName());
        if (n == null) return null;
        String[] at = part.place(n);
        if (at == null) return null;
        if (++entries[0] > MAX_ENTRIES) throw new Failure(Why.TOO_MANY, "the save in the zip holds more than " + MAX_ENTRIES + " entries", String.valueOf(MAX_ENTRIES));
        File root = at[0].equals(SaveStore.MAIN) ? main : device, to = new File(root, at[1]);
        if (!to.getAbsoluteFile().toPath().normalize().startsWith(root.getAbsoluteFile().toPath().normalize()))   // clean refused "..": a second guard, by path components
            throw new Failure(Why.UNSAFE_NAME, "the zip has a name outside the save: " + e.getName(), e.getName());
        if (!e.isDirectory() && !written.add(at[0] + "/" + at[1].toLowerCase(Locale.ROOT))) throw new Failure(Why.DUPLICATE, "the zip holds " + n + " twice", n);
        return to;
    }

    private static void mkdirs(File d) throws IOException {
        if (!d.isDirectory() && !d.mkdirs()) throw new IOException("cannot create " + d);
    }

    private static void write(InputStream in, File to, ZipEntry e, long[] total) throws IOException {
        mkdirs(to.getParentFile());
        if (to.exists()) throw new Failure(Why.DUPLICATE, "the zip holds " + e.getName() + " twice", e.getName());
        long n = 0;
        byte[] buf = new byte[1 << 16];
        try (FileOutputStream out = new FileOutputStream(to)) {
            for (int k; (k = in.read(buf)) > 0; ) {
                n += k;
                if (n > MAX_FILE) throw new Failure(Why.FILE_TOO_BIG, e.getName() + " is larger than " + SaveStore.size(MAX_FILE), e.getName(), SaveStore.size(MAX_FILE));
                if ((total[0] += k) > SaveStore.MAX_SAVE_BYTES)
                    throw new Failure(Why.TOO_BIG, "the save in the zip holds more than " + SaveStore.size(SaveStore.MAX_SAVE_BYTES), "", SaveStore.size(total[0]), SaveStore.size(SaveStore.MAX_SAVE_BYTES));
                out.write(buf, 0, k);
            }
            out.getFD().sync();
        }
        if (e.getTime() > 0) to.setLastModified(e.getTime());
    }

    // ---- Export ----

    /** What Export wrote: the zip, the save's files and bytes, and whether it holds the device save */
    static final class Exported {
        File zip;
        int files;
        long bytes;
        boolean device;
    }

    /** swap2-save-&lt;TITLE ID&gt;-&lt;stamp&gt;.zip */
    static String exportName(String titleId, String stamp) { return PREFIX + titleId.toUpperCase(Locale.ROOT) + "-" + stamp + ".zip"; }

    /** A name not taken in dir: name, else name-2.zip, name-3.zip, … */
    static File freeFile(File dir, String name) {
        File f = new File(dir, name);
        String base = name.endsWith(".zip") ? name.substring(0, name.length() - 4) : name;
        for (int k = 2; f.exists() || new File(f.getPath() + PARTIAL).exists(); k++) f = new File(dir, base + "-" + k + ".zip");
        return f;
    }

    /**
     * Removes the swap2-save-&lt;TITLE ID&gt;-….zip.partial files a stopped export of this game left in dir (the process ended while it wrote or checked one), the caller
     * holding the save's lock: an export holds it from its first byte to its rename, so no export of this game is writing one. → the bytes freed
     */
    static long clearPartials(File dir, String titleId) {
        String pre = (PREFIX + titleId + "-").toLowerCase(Locale.ROOT), suf = (".zip" + PARTIAL).toLowerCase(Locale.ROOT);
        String[] l = dir.list();
        long freed = 0;
        if (l == null) return 0;
        for (String n : l) {
            String low = n.toLowerCase(Locale.ROOT);
            File f = new File(dir, n);
            if (!low.startsWith(pre) || !low.endsWith(suf) || !f.isFile()) continue;
            long len = f.length();
            if (f.delete()) freed += len;
        }
        return freed;
    }

    /** Writes the save (main and device) as a zip into outDir, read back and checked before it gets its name (see the class comment). Takes the save's lock */
    static Exported export(File save, String titleId, File outDir, String stamp) throws IOException {
        String tid = titleId.toUpperCase(Locale.ROOT);
        try (SaveStore.Lock l = SaveStore.lock(save)) {
            SaveStore.recoverLocked(save);
            Map<String, File> parts = SaveStore.parts(save);
            if (!save.isDirectory() || !SaveStore.hasFiles(save) && !(parts.containsKey(SaveStore.DEVICE) && SaveStore.hasFiles(parts.get(SaveStore.DEVICE))))
                throw new Failure(Why.NO_SAVE, "there is no save in " + save, save.getPath());
            for (File p : parts.values())
                if (SaveStore.inside(outDir, p)) throw new IOException("the zip cannot go inside the save folder " + p);
            SaveStore.Manifest want = SaveStore.scanParts(parts);
            if (want.bytes > SaveStore.MAX_SAVE_BYTES)
                throw new Failure(Why.TOO_BIG, save + " holds " + SaveStore.size(want.bytes), save.getPath(), SaveStore.size(want.bytes), SaveStore.size(SaveStore.MAX_SAVE_BYTES));
            mkdirs(outDir);
            clearPartials(outDir, tid);
            long free = outDir.getUsableSpace(), need = want.bytes + (16L << 20);
            if (free > 0 && free < need)
                throw new Failure(Why.NO_SPACE, "the zip needs " + SaveStore.size(need) + ", " + outDir + " has " + SaveStore.size(free) + " free", SaveStore.size(need), outDir.getPath(), SaveStore.size(free));
            File zip = freeFile(outDir, exportName(tid, stamp)), tmp = new File(zip.getPath() + PARTIAL);
            try {
                try (FileOutputStream fo = new FileOutputStream(tmp); ZipOutputStream z = new ZipOutputStream(fo)) {
                    z.setLevel(6);
                    for (Map.Entry<String, File> e : parts.entrySet()) {
                        String pre = e.getKey().equals(SaveStore.MAIN) ? tid : tid + SaveStore.DEVICE_SUFFIX;
                        z.putNextEntry(new ZipEntry(pre + "/"));
                        z.closeEntry();
                        for (Map.Entry<String, String> m : want.sub(e.getKey()).entries.entrySet()) {
                            File f = new File(e.getValue(), m.getKey());
                            boolean dir = m.getValue().equals("d");
                            ZipEntry ze = new ZipEntry(pre + "/" + m.getKey() + (dir ? "/" : ""));
                            ze.setTime(f.lastModified());
                            z.putNextEntry(ze);
                            if (!dir) try (InputStream in = new FileInputStream(f)) { in.transferTo(z); }
                            z.closeEntry();
                        }
                    }
                    z.finish();
                    fo.getFD().sync();
                }
                // read back with the importer's reader: a zip that is kept is one Import takes, and holds the save as it was scanned
                Source back = new Source(tmp);
                List<Item> items = list(back);
                List<Part> found = find(items, tid);
                Part p = found.isEmpty() ? null : found.get(0);
                if (p == null || !p.prefix.equals(tid) || (p.device != null) != parts.containsKey(SaveStore.DEVICE) || refuse(p, items) != null)
                    throw new Failure(Why.READ_BACK, "the zip read back does not hold the save as " + tid + "/", tid + "/");
                SaveStore.Manifest got = manifestOf(tmp, p);
                String d = want.diff(got);
                if (d != null) throw new Failure(Why.READ_BACK, "the zip read back does not match the save (" + d + ")", want.diffAt(got));
                SaveStore.Manifest now = SaveStore.scanParts(parts);
                String changed = want.diff(now);
                if (changed != null) throw new Failure(Why.CHANGED, "the save changed while it was zipped (" + changed + ")", want.diffAt(now));
                if (!tmp.renameTo(zip)) throw new IOException("cannot name the zip " + zip);
            } finally {
                if (tmp.exists()) tmp.delete();
            }
            Exported out = new Exported();
            out.zip = zip;
            out.files = want.files;
            out.bytes = want.bytes;
            out.device = parts.containsKey(SaveStore.DEVICE);
            return out;
        }
    }

    /** The part of a zip as SaveStore's manifest of a save's parts (main/…, device/…: SHA-256 and size of each file), read from the zip */
    static SaveStore.Manifest manifestOf(File zip, Part p) throws IOException {
        SaveStore.Manifest m = new SaveStore.Manifest();
        m.entries.put(SaveStore.MAIN, "d");
        if (p.device != null) m.entries.put(SaveStore.DEVICE, "d");
        byte[] buf = new byte[1 << 16];
        try (ZipFile z = new ZipFile(zip)) {
            Enumeration<? extends ZipEntry> en = z.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                String n = clean(e.getName());
                String[] at = n == null ? null : p.place(n);
                if (at == null || at[1].isEmpty()) continue;
                String key = at[0] + "/" + at[1];
                if (e.isDirectory()) { m.entries.put(key, "d"); continue; }
                MessageDigest h;
                try { h = MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException x) { throw new IOException(x); }
                long size = 0;
                try (InputStream in = z.getInputStream(e)) {
                    for (int k; (k = in.read(buf)) > 0; ) { h.update(buf, 0, k); size += k; }
                }
                StringBuilder s = new StringBuilder();
                for (byte x : h.digest()) s.append(String.format(Locale.ROOT, "%02x", x & 0xff));
                m.entries.put(key, "f " + s + " " + size);
                m.files++;
                m.bytes += size;
            }
        }
        return m;
    }

    /** The zips in these folders whose name holds the title ID (any case: Export's swap2-save-&lt;TITLE ID&gt;-…, or a zip named after the save folder), newest first */
    static List<File> found(String titleId, File... dirs) {
        List<File> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        String id = titleId.toLowerCase(Locale.ROOT);
        for (File d : dirs) {
            File[] l = d == null ? null : d.listFiles();
            if (l == null) continue;
            for (File f : l) {
                String n = f.getName().toLowerCase(Locale.ROOT);
                // by name first: only a matching name costs a stat (a Download folder may hold thousands of files, and this runs as the sheet opens)
                if (n.endsWith(".zip") && n.contains(id) && f.isFile() && seen.add(SaveStore.canon(f))) out.add(f);
            }
        }
        out.sort((a, b) -> Long.compare(b.lastModified(), a.lastModified()));
        return out;
    }
}
