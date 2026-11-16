package com.swap2native.shadowtool;

import static org.junit.Assert.*;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import org.junit.Test;

/** Regression tests for field names from an actual Ocarina BASE v65536 diagnosis. */
public class ShadowPackTest {
    private static final String MAIN =
        "gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml";
    private static final String UI =
        "gsys/ModelSceneConfigParam/UI.gsys__ModelSceneConfigParam.bgyml";

    private static void u24(byte[] b,int off,int x) {
        b[off]=(byte)x; b[off+1]=(byte)(x>>8);b[off+2]=(byte)(x>>16);
    }
    private static void entry(byte[] b,ByteBuffer out,int offset,int key,int type,int value) {
        u24(b,offset,key);
        b[offset+3]=(byte)type;
        out.putInt(offset+4,value);
    }
    private static byte[] fixture(int width,int height,int staticWidth) {
        byte[] b=new byte[512];
        ByteBuffer out=ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
        b[0]='Y';b[1]='B';out.putShort(2,(short)7);
        out.putInt(4,0x20);out.putInt(12,0x100);
        String[] keys={"DepthShadowTexHeight","DepthShadowTexWidth",
            "StaticSdwWidth","OcclusionQueryNum","CubemapMaxShapeNum"};
        b[0x20]=(byte)0xc2;u24(b,0x21,keys.length);
        int cursor=0x20+4+(keys.length+1)*4;
        for(int i=0;i<keys.length;i++) {
            out.putInt(0x24+i*4,cursor-0x20);
            byte[] name=keys[i].getBytes(StandardCharsets.UTF_8);
            System.arraycopy(name,0,b,cursor,name.length);
            cursor+=name.length+1;
        }
        b[0x100]=(byte)0xc1;u24(b,0x101,5);
        entry(b,out,0x104,0,0xd1,height);
        entry(b,out,0x10c,1,0xd1,width);
        entry(b,out,0x114,2,0xd1,staticWidth);
        entry(b,out,0x11c,3,0xd1,4096);
        entry(b,out,0x124,4,0xd3,4096);
        return b;
    }
    private static int value(byte[] b,int offset) {
        return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getInt(offset);
    }
    @Test public void mainMapsAndOnlyMainMapsCanBeReduced() throws Exception {
        byte[] original=fixture(1024,1024,4096);
        ShadowPack.Result scanned=ShadowPack.inspectStandalone(original,MAIN);
        assertTrue(scanned.applicable);
        assertTrue(scanned.standalone);
        assertEquals(MAIN,scanned.packPath);
        byte[] patched=ShadowPack.makeOverlay(scanned,512,2048);
        assertEquals(512,value(patched,0x108)); // DepthShadowTexHeight
        assertEquals(512,value(patched,0x110)); // DepthShadowTexWidth
        assertEquals(2048,value(patched,0x118)); // StaticSdwWidth
        assertEquals(4096,value(patched,0x120)); // NOT an occlusion resolution
        assertEquals(4096,value(patched,0x128)); // NOT a shadow cubemap
        assertEquals(1024,value(original,0x108));
        assertEquals(4096,value(original,0x118));
        int changed=0;
        for(int i=0;i<original.length;i++)if(original[i]!=patched[i])changed++;
        assertEquals(3,changed);
        byte[] low=ShadowPack.makeOverlay(scanned,256,1024);
        assertEquals(256,value(low,0x108));
        assertEquals(256,value(low,0x110));
        assertEquals(1024,value(low,0x118));
    }
    @Test public void UIIsNotTreatedAsGameplay() throws Exception {
        ShadowPack.Result ui=ShadowPack.inspectStandalone(fixture(4096,4096,4096),UI);
        assertFalse(ui.applicable);
        ShadowPack.Result uiTrick=ShadowPack.inspectStandalone(fixture(1024,1024,4096),UI);
        assertFalse(uiTrick.applicable);
    }
    @Test public void missingOrChangedMainDimensionsBlockPatch() throws Exception {
        assertFalse(ShadowPack.inspectStandalone(fixture(4096,1024,4096),MAIN).applicable);
        assertFalse(ShadowPack.inspectStandalone(fixture(1024,1024,2048),MAIN).applicable);
        byte[] badType=fixture(1024,1024,4096);
        badType[0x107]=(byte)0xd3;
        assertFalse(ShadowPack.inspectStandalone(badType,MAIN).applicable);
    }
    @Test public void unrelatedBymlRefused() throws Exception {
        try {
            ShadowPack.inspectStandalone(fixture(1024,1024,4096),
                "System/GameGraphics/ModelSceneEnvParam/Default.game__gfx__ModelSceneEnvParam.bgyml");
            fail("Expected unrelated file to be rejected");
        }catch(IOException expected) {
            assertTrue(expected.getMessage().contains("ModelSceneConfigParam"));
        }
    }
}
