"""Run the actual Java idle preference and environment line on the JVM."""
from pathlib import Path
import subprocess,tempfile,unittest
from dm.gfx.tools.tests.test_banana_input_caches import function
ROOT=Path(__file__).resolve().parents[3]
class EncoderDefault(unittest.TestCase):
 def test_oot_default_and_explicit_rollback(self):
  s=(ROOT/'android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java').read_text()
  methods=function(s,'static int encoderIdle(Context c)')+'\n'+function(s,'static int encoderIdle(Context c, String id)')
  env=next(x.strip()for x in s.splitlines()if 'if (encoderIdle(c, id)'in x and 'out.add('in x)
  src='''import java.util.*;
class Context{}
class Store{Map<String,Integer> m=new HashMap<>();int getInt(String k,int v){return m.getOrDefault(k,v);}}
class Prefs{static final String OCARINA_TITLE="0400486024DEC000";static Store p=new Store();static Store of(Context c){return p;}static String gameKey(String k,String id){return id+":"+k;}}
class EncoderIdleJvm{static int clamp(int v,int l,int h){return Math.min(h,Math.max(l,v));}
'''+methods+'''
static List<String> env(Context c,String id){List<String> out=new ArrayList<>();'''+env+'''return out;}
static void check(boolean b){if(!b)throw new AssertionError();}
public static void main(String[] args){Context c=new Context();String id=Prefs.OCARINA_TITLE;
check(encoderIdle(c,id)==1);check(env(c,id).contains("DM_VK_ENC_SPIN_US=0"));
check(encoderIdle(c,"other")==0);check(env(c,"other").isEmpty());
Prefs.p.m.put(Prefs.gameKey("encoder_idle",id),0);check(encoderIdle(c,id)==0);check(env(c,id).isEmpty());
Prefs.p.m.put(Prefs.gameKey("encoder_idle",id),1);check(encoderIdle(c,id)==1);
Prefs.p.m.put("encoder_idle",1);check(encoderIdle(c,"other")==1);
System.out.println("encoder default: OOT parks, explicit per-game polling rollback and other-game default preserved");}}
'''
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);p=d/'EncoderIdleJvm.java';p.write_text(src)
   subprocess.run(['javac','-d',str(d),str(p)],check=True,capture_output=True)
   r=subprocess.run(['java','-cp',str(d),'EncoderIdleJvm'],check=True,capture_output=True,text=True);print(r.stdout)
if __name__=='__main__':unittest.main()
