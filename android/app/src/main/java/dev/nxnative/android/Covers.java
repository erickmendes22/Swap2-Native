package dev.nxnative.android;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/**
 * A game's cover in the library (MainActivity's cards): its eShop icon by its title ID, from tinfoil.media's image service (512 px, else 256: the larger one is not
 * always served), as the old runtime's library took it (MKWDroidActivity.downloadCover, commit ae9a8a9). Kept as a PNG in &lt;shared storage&gt;/Switch2/covers/&lt;title
 * ID&gt;.png, beside the games, so it outlives an uninstall; a title the service does not have is not asked again for a day (&lt;title ID&gt;.none). One download at a
 * time, off the main thread; the card shows the kit's placeholder until its cover is there.
 */
final class Covers {
    private static final String TAG = "Swap2Native";
    private static final long RETRY_MS = 24L * 3600 * 1000;
    private static final ExecutorService one = Executors.newSingleThreadExecutor(r -> new Thread(r, "nx-covers"));
    private static final Set<String> asked = new HashSet<>();
    private static final Handler main = new Handler(Looper.getMainLooper());

    private Covers() {}

    static File dir() { return new File(Profile.userDir().getParentFile(), "covers"); }

    static File file(String titleId) { return new File(dir(), titleId + ".png"); }

    /** The cover now when it is on the storage (decoded at most 512 px wide), else null and, once per run, a download; done gets the bitmap on the main thread */
    static Bitmap get(String titleId, Consumer<Bitmap> done) {
        File f = file(titleId);
        if (f.isFile()) {
            Bitmap b = BitmapFactory.decodeFile(f.getPath());
            if (b != null) return b;
        }
        synchronized (asked) { if (!asked.add(titleId)) return null; }
        one.execute(() -> {
            Bitmap b = download(titleId);
            if (b != null) main.post(() -> done.accept(b));
        });
        return null;
    }

    private static Bitmap download(String titleId) {
        File none = new File(dir(), titleId + ".none");
        if (none.isFile() && System.currentTimeMillis() - none.lastModified() < RETRY_MS) return null;
        boolean answered = false;   // the service said it has no cover (not a network failure, which is asked again next run)
        for (String size : new String[] {"512", "256"}) {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL("https://tinfoil.media/ti/" + titleId + "/" + size + "/" + size + "/").openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(15000);
                c.setRequestProperty("User-Agent", "Swap2-Native");
                int code = c.getResponseCode();
                if (code != 200) { answered |= code == 404; continue; }   // (a 503 or another server error is asked again next run)
                Bitmap b = BitmapFactory.decodeStream(c.getInputStream());
                if (b == null) continue;
                File out = file(titleId), tmp = new File(out.getPath() + ".part");
                if (!dir().isDirectory() && !dir().mkdirs()) return b;   // shown, not kept
                try (FileOutputStream o = new FileOutputStream(tmp)) { b.compress(Bitmap.CompressFormat.PNG, 100, o); }
                if (!tmp.renameTo(out)) tmp.delete();
                none.delete();
                Log.i(TAG, "cover of " + titleId + ": " + b.getWidth() + "x" + b.getHeight());
                return b;
            } catch (Exception e) {
                Log.w(TAG, "cover of " + titleId + ": " + e);
            } finally {
                if (c != null) c.disconnect();
            }
        }
        // tinfoil.media has no cover for the newer Switch 2 games (The Legend of Zelda: Ocarina of Time and Pokémon Pokopia answer 503 at every size, 2026-11-05):
        // Nintendo's own store search (Nintendo of Europe) by the profile's name, the game's square key art (500 px)
        Bitmap n = nintendo(titleId);
        if (n != null) { keep(titleId, n); none.delete(); return n; }
        if (answered) try { if (dir().isDirectory() || dir().mkdirs()) new FileOutputStream(none).close(); } catch (Exception e) { /* asked again next run */ }
        return null;
    }

    private static void keep(String titleId, Bitmap b) {
        File out = file(titleId), tmp = new File(out.getPath() + ".part");
        if (!dir().isDirectory() && !dir().mkdirs()) return;   // shown, not kept
        try (FileOutputStream o = new FileOutputStream(tmp)) { b.compress(Bitmap.CompressFormat.PNG, 100, o); } catch (Exception e) { tmp.delete(); return; }
        if (!tmp.renameTo(out)) tmp.delete();
        Log.i(TAG, "cover of " + titleId + ": " + b.getWidth() + "x" + b.getHeight());
    }

    /** A name for comparing: lower case, accents and everything but letters and digits dropped ("Pokémon Pokopia" = "Pokemon Pokopia") */
    private static String plain(String s) {
        return java.text.Normalizer.normalize(s, java.text.Normalizer.Form.NFD).replaceAll("\\p{M}", "").toLowerCase(java.util.Locale.ROOT).replaceAll("[^a-z0-9]", "");
    }

    /**
     * The game's square image from Nintendo of Europe's store search (searching.nintendo-europe.com, the index nintendo.com/eu's search uses): the games of the
     * game's system (title IDs from 04… are Switch 2) found by its profile's name; the entry whose title is that name, else none (a near name could be another game)
     */
    private static Bitmap nintendo(String titleId) {
        Profile p = Profile.of(titleId);
        if (p == null || p.name == null || p.name.isEmpty()) return null;
        String system = titleId.startsWith("04") ? "Nintendo Switch 2" : "Nintendo Switch";
        HttpURLConnection c = null;
        try {
            // (the index's system_names_txt does not filter as a phrase: the system is checked here, on the first 30 games the name finds)
            String q = "https://searching.nintendo-europe.com/en/select?wt=json&rows=30&fl=title,image_url_sq_s,system_names_txt&fq=type:GAME&q="
                    + java.net.URLEncoder.encode(p.name, "UTF-8");
            c = (HttpURLConnection) new URL(q).openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", "Swap2-Native");
            if (c.getResponseCode() != 200) return null;
            String body = new String(c.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            org.json.JSONArray docs = new org.json.JSONObject(body).getJSONObject("response").getJSONArray("docs");
            String want = plain(p.name);
            for (int i = 0; i < docs.length(); i++) {
                org.json.JSONObject d = docs.getJSONObject(i);
                String url = d.optString("image_url_sq_s", "");
                org.json.JSONArray sys = d.optJSONArray("system_names_txt");
                boolean on = false;
                for (int k = 0; sys != null && k < sys.length(); k++) on |= system.equals(sys.optString(k));
                if (url.isEmpty() || !on || !plain(d.optString("title", "")).equals(want)) continue;
                c.disconnect();
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(15000);
                c.setRequestProperty("User-Agent", "Swap2-Native");
                if (c.getResponseCode() != 200) return null;
                Bitmap b = BitmapFactory.decodeStream(c.getInputStream());
                if (b != null && b.getWidth() > 512) b = Bitmap.createScaledBitmap(b, 512, b.getHeight() * 512 / b.getWidth(), true);
                return b;
            }
            Log.i(TAG, "cover of " + titleId + ": Nintendo's store search has no " + system + " game named " + p.name);
        } catch (Exception e) {
            Log.w(TAG, "cover of " + titleId + " (Nintendo's store search): " + e);
        } finally {
            if (c != null) c.disconnect();
        }
        return null;
    }
}
