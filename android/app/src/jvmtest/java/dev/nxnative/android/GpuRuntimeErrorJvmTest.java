package dev.nxnative.android;

public final class GpuRuntimeErrorJvmTest {
    static void check(boolean ok, String msg) { if (!ok) throw new AssertionError(msg); }
    static void verify(String error, String title) {
        GpuRuntimeError.Issue issue = GpuRuntimeError.fromText(error);
        check(issue != null && issue.title.equals(title), "unexpected: " + title);
        check(issue.report("Turnip").contains(error), "raw evidence missing");
    }
    public static void main(String[] args) {
        check(GpuRuntimeError.fromText("[vk] driver: Turnip\n[nvn] frame 100") == null, "false-positive working GPU");
        check(GpuRuntimeError.fromText("[RED] shader cache miss") == null, "shader miss is not driver error");
        verify("[RED] no VK_EXT_map_memory_placed: guest memory stays anonymous", "GPU memory mapping unsupported");
        verify("[RED] no VK_KHR_swapchain: nothing is presented", "Vulkan cannot present images");
        verify("[RED] vkCreateDevice -8", "Vulkan initialization failed");
        verify("[RED] device lacks timeline semaphores (0)", "GPU feature unavailable");
        verify("[RED] DM_VK_DRIVER=/x: adrenotools could not load the driver", "Custom GPU driver load failed");
        verify("[RED] GPU hang: fence not reached", "GPU execution stopped");
        System.out.println("GPU runtime error classification: PASS");
    }
}
