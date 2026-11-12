"""Real launcher selection before the :pack process exists (phone video 190101)."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
JAVA = ROOT / 'android/app/src/ondevice/java/dev/nxnative/android'


class VegetationLauncher(unittest.TestCase):
    @unittest.skipUnless(shutil.which('java'), 'JDK required')
    def test_launcher_without_native_context_selects_508_not_56_captures(self):
        self.run_jvm()

    def run_jvm(self, delta_source=None, ui_source=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); package = root/'src/dev/nxnative/android'; package.mkdir(parents=True)
            (package/'OcarinaShaderDelta.java').write_text(delta_source or (JAVA/'OcarinaShaderDelta.java').read_text())
            shutil.copy(JAVA/'OcarinaVegetation.java', package)
            log = root/'src/android/util'; log.mkdir(parents=True)
            (log/'Log.java').write_text('package android.util; public class Log { public static int w(String t,String m,Throwable e){return 0;} public static int i(String t,String m){return 0;} }')
            # Compile the actual display/admission control prefix. Widget
            # painting after visibility changes is irrelevant to this fault.
            ui = ui_source or (JAVA/'Ondevice.java').read_text()
            start = ui.index('        void show() {')
            end = ui.index('            view.setVisibility(View.VISIBLE);', start) + len('            view.setVisibility(View.VISIBLE);')
            show = ui[start:end] + '\n        }\n'
            (package/'Probe.java').write_text('''
package dev.nxnative.android;
import java.io.*;
import java.nio.file.*;
import java.util.*;
class BuildConfig { static final String NX_DMSH_VK_ABI="674db0a4ff79",NX_DMSH_VK_CHAIN="123456789abc"; }
class PackNative {
    static int calls;
    static File repo() throws IOException {calls++; throw new IllegalStateException("PackNative.context not set");}
}
class Profile { String shaderInputs="aa5e7196d926"; static Profile of(String s){return new Profile();} }
class ShaderAbiCert {static boolean approved(String a,String b,String c,String d){return false;} }
class ShaderLibs {
    static class Header { String abi=BuildConfig.NX_DMSH_VK_ABI,inputs="aa5e7196d926",game="0400486024DEC000",vkChain="b6b21fb5753a";long entries=42339;boolean fits(long n){return true;} }
    static File originalOcarina(File p,String t,String a,String i){return new File(p,"base.lib");}
    static Header header(File f){return f.getName().equals("base.lib")?new Header():null;}
    static boolean hasKey(File f,Header h,String key)throws IOException{return false;}
}
class Job {
    File root; String state="pending";List<String> keys=List.of();
    Job(File f){root=f;}
    String titleId(){return "0400486024DEC000";}
    File pack(){return new File(root,"pack");} File dir(){return new File(root,"ondevice");}
    List<String> hotKeys(){return keys;} String state(){return state;}
}
class View {static final int VISIBLE=0,GONE=8;int value=VISIBLE;int getVisibility(){return value;}void setVisibility(int n){value=n;} }
class Prefs {static Prefs open(Object a,String s){return new Prefs();}String getString(String k,String d){return d;} }
class App {void refresh(){} }
class Screen {
    Job job; View view=new View();App a=new App();int added;
    boolean alive(){return false;}boolean ready(Job j){return true;}boolean listed(Job j){return true;}
    String addedKey(Job j){return "new-update";}void addGame(Job j){added++;}void publish(Object s){}
''' + show + '''
}
public class Probe {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        File root=new File(args[0]);new File(root,"pack").mkdirs();
        File captures=new File(root,"nvn_shdump");captures.mkdirs();
        for(int i=1;i<=56;i++) {
            String key=String.format("%016x",i);
            Files.write(new File(captures,key+".code").toPath(),new byte[4]);
            Files.write(new File(captures,key+".ctl").toPath(),new byte[0xd8]);
        }
        Job j=new Job(root);
        List<String> keys=OcarinaShaderDelta.keys(j);
        check(keys.size()==508,"Expected 508 static stages before pack startup; got "+keys.size());
        check(PackNative.calls==0,"Launcher touched native pack process");
        check(new HashSet<>(keys).size()==508,"Duplicate keys");
        j.keys=keys;
        check(OcarinaShaderDelta.vegetationJob(j),"Wrong job mode");
        check(!OcarinaShaderDelta.alreadyRepaired(j,keys),"Absent supplement called complete");
        check(OcarinaShaderDelta.overlay(j,true).getPath().contains("shaders/vegetation/"),"Wrong output library");
        Screen screen=new Screen();screen.job=j;screen.show();
        check(screen.view.value==View.VISIBLE && screen.added==0,"Pending update hidden as playable base");
        j.state="failed";screen.show();
        check(screen.view.value==View.VISIBLE && screen.added==0,"Failed update/error hidden");
        j.state="done";screen.show();
        check(screen.view.value==View.GONE && screen.added==1,"Completed update not retired");
        System.out.println("508 selected without native context; pending/failed update visible; stable base preserved");
    }
}
''')
            classes = root/'classes'; classes.mkdir()
            sources = sorted(str(p) for p in (root/'src').rglob('*.java'))
            compiler = [shutil.which('javac')] if shutil.which('javac') else ['java', 'com.sun.tools.javac.Main']
            subprocess.run([*compiler, '-d', str(classes), *sources], check=True)
            subprocess.run(['java', '-cp', str(classes), 'dev.nxnative.android.Probe', str(root)], check=True)


if __name__ == '__main__': unittest.main()
