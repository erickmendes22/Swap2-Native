package com.swap2native.shadowtool;

import static org.junit.Assert.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import org.junit.Test;

public class ShadowPackTest {
    private static final String CONFIG =
        "System/GameGraphics/ModelSceneConfigParam/Main.game__gfx__ModelSceneConfigParam.bgyml";

    private static void u24(byte[] b,int off,int x) {
        b[off]=(byte)x; b[off+1]=(byte)(x>>8);b[off+2]=(byte)(x>>16);
    }
    private static void entry(byte[] b,ByteBuffer out,int offset,int key,int kind,int value) {
        u24(b,offset,key);
        b[offset+3]=(byte)kind;
        out.putInt(offset+4,value);
    }
    private static byte[] fixture() {
        byte[] b=new byte[512];
        ByteBuffer out=ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
        b[0]='Y';b[1]='B';
        out.putShort(2,(short)7);
        out.putInt(4,0x20);
        out.putInt(12,0x100);
        String[] keys={"CreateDepthShadow","CreateStaticDepthShadow",
            "ShadowMapHeight","ShadowMapSize","ShadowMapWidth"};
        b[0x20]=(byte)0xc2;
        u24(b,0x21,keys.length);
        int cursor=0x20+4+(keys.length+1)*4;
        for(int i=0;i<keys.length;i++) {
            out.putInt(0x24+i*4,cursor-0x20);
            byte[] data=keys[i].getBytes(StandardCharsets.UTF_8);
            System.arraycopy(data,0,b,cursor,data.length);
            cursor+=data.length+1;
        }
        b[0x100]=(byte)0xc1;u24(b,0x101,2);
        entry(b,out,0x104,0,0xc1,0x120);
        entry(b,out,0x10c,1,0xc1,0x160);
        b[0x120]=(byte)0xc1;u24(b,0x121,2);
        entry(b,out,0x124,2,0xd1,1024);
        entry(b,out,0x12c,4,0xd1,1024);
        b[0x160]=(byte)0xc1;u24(b,0x161,1);
        entry(b,out,0x164,3,0xd1,4096);
        return b;
    }
    @Test public void directBymlOverlayChangesOnlyThreeShadowSizes() throws Exception {
        byte[] original=fixture();
        ShadowPack.Result scanned=ShadowPack.inspectStandalone(original,CONFIG);
        assertTrue(scanned.applicable);
        assertTrue(scanned.standalone);
        assertEquals(CONFIG,scanned.packPath);
        byte[] patched=ShadowPack.makeOverlay(scanned,512,2048);
        ByteBuffer p=ByteBuffer.wrap(patched).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals(512,p.getInt(0x128));
        assertEquals(512,p.getInt(0x130));
        assertEquals(2048,p.getInt(0x168));
        ByteBuffer o=ByteBuffer.wrap(original).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals(1024,o.getInt(0x128));
        assertEquals(4096,o.getInt(0x168));
        int changed=0;
        for(int i=0;i<original.length;i++)if(original[i]!=patched[i])changed++;
        assertEquals(3,changed); // 0x0400→0x0200 and 0x1000→0x0800 each change one byte
    }
    @Test public void missingStaticFieldNeverEnablesPatch() throws Exception {
        byte[] data=fixture();
        ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).putInt(0x168,2048);
        ShadowPack.Result result=ShadowPack.inspectStandalone(data,CONFIG);
        assertFalse(result.applicable);
    }
    @Test public void unrelatedBymlCannotBePatched() throws Exception {
        try {
            ShadowPack.inspectStandalone(fixture(),
                "System/GameGraphics/ModelSceneEnvParam/Default.game__gfx__ModelSceneEnvParam.bgyml");
            fail("Unexpected patch");
        }catch(java.io.IOException expected) {
            assertTrue(expected.getMessage().contains("ModelSceneConfigParam"));
        }
    }
}
