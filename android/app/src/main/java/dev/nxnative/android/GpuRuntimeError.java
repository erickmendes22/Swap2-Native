package dev.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** No preflight: classify only Vulkan errors emitted by the REAL game host. */
final class GpuRuntimeError {
    private GpuRuntimeError() {}
    static final class Issue {
        final String title, detail, evidence;
        Issue(String title, String detail, String evidence) {
            this.title = title; this.detail = detail; this.evidence = evidence;
        }
        String report(String driver) {
            return detail + "\n\nNative error:\n" + evidence + "\n\nDriver selected: " + driver
                + "\n\nTry another driver in Settings > GPU driver or Game settings."
                + "\nUse Share log to include the full GPU/driver details. Switching drivers never requires shader recompilation.";
        }
    }
    static Issue fromText(String text) {
        if (text == null) return null;
        String[] lines = text.split("\n");
        for (int i = lines.length - 1; i >= 0; i--) {
            String original = lines[i].trim(), s = original.toLowerCase(Locale.ROOT);
            if (!s.contains("[red]") && !s.contains("fatal")) continue;
            if (s.contains("no vk_ext_map_memory_placed") || s.contains("memorymapplaced") && s.contains("lack"))
                return new Issue("GPU memory mapping unsupported",
                    "The active Vulkan driver cannot map guest GPU memory at the required addresses. Images may be missing.", original);
            if (s.contains("no vk_khr_swapchain"))
                return new Issue("Vulkan cannot present images",
                    "The GPU driver did not expose the swapchain feature needed to present the game.", original);
            if (s.contains("no libvulkan.so") || s.contains("vkcreateinstance") || s.contains("vkcreatedevice")
                    || s.contains("no vulkan physical device") || s.contains("no graphics + compute queue family")
                    || s.contains("replay needs 1.3"))
                return new Issue("Vulkan initialization failed",
                    "The actual game host could not initialize a Vulkan instance, device, API version or graphics queue.", original);
            if (s.contains("timeline semaphores") || s.contains("dynamic rendering")
                    || s.contains("non-uniform indexing") || s.contains("shaderdrawparameters"))
                return new Issue("GPU feature unavailable",
                    "The actual driver lacks a feature that the emulator requires.", original);
            if (s.contains("adrenotools could not load") || s.contains("dm_vk_driver") && s.contains("system driver is used"))
                return new Issue("Custom GPU driver load failed",
                    "The selected custom driver did not load; the system driver may have been used instead.", original);
            if (s.contains("gpu hang:") || s.contains("device lost") || s.contains("vk_error_device_lost"))
                return new Issue("GPU execution stopped",
                    "The GPU/driver lost progress after startup. This does not by itself prove the device is incompatible.", original);
        }
        return null;
    }
    /** Read startup and latest events only, keeping memory bounded for large logs. */
    static Issue inspect(File log) {
        if (log == null || !log.isFile()) return null;
        try (RandomAccessFile f = new RandomAccessFile(log, "r")) {
            long len = f.length();
            byte[] begin = new byte[(int) Math.min(len, 98304L)];
            f.readFully(begin);
            Issue first = fromText(new String(begin, StandardCharsets.UTF_8));
            if (len <= begin.length) return first;
            byte[] end = new byte[(int) Math.min(len - begin.length, 131072L)];
            f.seek(len - end.length);
            f.readFully(end);
            Issue last = fromText(new String(end, StandardCharsets.UTF_8));
            return last != null ? last : first;
        } catch (IOException ex) { return null; }
    }
}
