package dev.nxnative.android;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

/**
 * One-time Vulkan readiness probe in its OWN Android process. Never load or
 * initialize a custom Vulkan driver inside :game just to inspect extensions:
 * driver teardown and process-global dispatch state may be unsafe to reuse
 * when nxhost_main starts on some Snapdragon/Turnip combinations.
 *
 * The caller times out independently and can offer Try anyway if this process
 * dies while querying the GPU. No shaders or game memory are loaded here.
 */
public final class GpuProbeProvider extends ContentProvider {
    static Uri uri(Context context) {
        return Uri.parse("content://" + context.getPackageName() + ".gpu_probe");
    }

    @Override public boolean onCreate() { return true; }

    @Override public Bundle call(String method, String arg, Bundle extras) {
        if (!"vulkan-readiness".equals(method)) return super.call(method, arg, extras);
        Bundle out = new Bundle();
        try {
            if (extras == null) throw new IllegalArgumentException("missing Vulkan probe arguments");
            String title = extras.getString("title_id");
            if (title == null || title.isEmpty()) throw new IllegalArgumentException("missing game ID");
            Native.load(title);
            String facts = Native.readiness(extras.getStringArray("env"));
            out.putString("facts", facts != null ? facts : "unchecked=Vulkan readiness unavailable in game host");
        } catch (RuntimeException | LinkageError e) {
            Log.e("Swap2Native", "isolated Vulkan readiness failed", e);
            out.putString("facts", "unchecked=isolated Vulkan readiness failed: " + e.getClass().getSimpleName());
        } finally {
            // vka_driver_open caches the Vulkan driver per native process. A
            // later run can pick a different per-game driver (891.14 instead
            // of Turnip V37) and otherwise silently probe the OLD driver.
            // The provider is private and only performs one GPU check; retire
            // its process AFTER Binder has delivered this call's reply.
            new Handler(Looper.getMainLooper()).postDelayed(
                    () -> android.os.Process.killProcess(android.os.Process.myPid()), 1500);
        }
        return out;
    }

    @Override public Cursor query(Uri uri, String[] columns, String selection, String[] args, String order) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
