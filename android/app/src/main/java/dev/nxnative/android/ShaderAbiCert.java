package dev.nxnative.android;

/** Build-time audited ABI extensions. Generated with Vulkan host certificates. */
final class ShaderAbiCert {
    private ShaderAbiCert() {}
    private static final class Cert {
        final String oldVk, oldAbi, inputs;
        Cert(String v, String a, String i) { oldVk = v; oldAbi = a; inputs = i; }
    }
    private static final Cert[] CERTS = {
    };
    static boolean approved(String game, String oldVk, String oldAbi, String inputs) {
        if (!"0400486024DEC000".equals(game)) return false;
        for (Cert c : CERTS) {
            if (c.oldVk.equals(oldVk) && c.oldAbi.equals(oldAbi) && c.inputs.equals(inputs)) return true;
        }
        return false;
    }
}
