package dev.nxnative.android;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** A game the user added: its folder and its pack folder, as /storage paths. Remembered in the app's preferences. */
final class Game {
    final String titleId, name, gameDir, packDir;

    // Paths are kept in their primary form (Frontend.normal: /sdcard and /storage/self/primary are /storage/emulated/0), so one file is one game: the
    // library listed Zelda twice, its .nup added once as /storage/emulated/0/Switch2/… and once as /sdcard/Switch2/… (an adb test intent)
    Game(String titleId, String name, String gameDir, String packDir) {
        this.titleId = titleId;
        this.name = name;
        this.gameDir = Frontend.normal(gameDir);
        this.packDir = Frontend.normal(packDir);
    }

    JSONObject toJson() throws JSONException {
        return new JSONObject().put("title_id", titleId).put("name", name).put("game", gameDir).put("pack", packDir);
    }

    static Game fromJson(JSONObject o) throws JSONException {
        return new Game(o.getString("title_id"), o.getString("name"), o.getString("game"), o.getString("pack"));
    }

    private static SharedPreferences prefs(Context c) { return Prefs.open(c, "games"); }

    static List<Game> load(Context c) {
        List<Game> out = new ArrayList<>();
        try {
            JSONArray a = new JSONArray(prefs(c).getString("list", "[]"));
            for (int i = 0; i < a.length(); i++) add(out, fromJson(a.getJSONObject(i)));
        } catch (JSONException e) {
            // a damaged list starts empty
        }
        return out;
    }

    /** Adds g unless the list has its game already (the first entry of a path stays: a list saved before the paths were kept normal can hold one twice) */
    private static void add(List<Game> list, Game g) {
        for (Game x : list) if (x.gameDir.equals(g.gameDir)) return;
        list.add(g);
    }

    static void save(Context c, List<Game> games) {
        JSONArray a = new JSONArray();
        List<Game> once = new ArrayList<>();
        for (Game g : games) add(once, g);
        try {
            for (Game g : once) a.put(g.toJson());
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
        prefs(c).edit().putString("list", a.toString()).commit();
    }
}
