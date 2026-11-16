package com.swap2native.shadowtool;

import com.github.luben.zstd.ZstdCompressCtx;
import com.github.luben.zstd.ZstdDecompressCtx;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Reads the real dictionary-compressed Ocarina Bootup SARC and its BYML scene
 * configuration. Does not assume fixed offsets. The patcher intentionally
 * FAILS CLOSED when actual field names are hashed or ambiguous.
 *
 * This does not edit .nup; creates a separate compatible .pack.zs for overlay.
 */
public final class ShadowPack {
    public static final String PACK_PATH="Pack/Bootup.Nin_Ounce_NVN2.pack.zs";
    public static final String DICT_PATH="Pack/ZsDic.pack.zs";
    private static final int MAX_PACK=192*1024*1024;
    private static final int MAX_DICT=8*1024*1024;

    public static final class Field {
        public final String file,path,leaf;
        public final int type,offset;
        public final long value;
        Field(String f,String p,String l,int t,int o,long v) {
            file=f;path=p;leaf=l;type=t;offset=o;value=v;
        }
        public String line(){return path+" = "+value+" ["+Integer.toHexString(type)
                                +", pack+0x"+Integer.toHexString(offset)+"]";}
    }
    public static final class Result {
        public final byte[] raw,dict,compressed;
        public final List<Field> fields;
        public final String report;
        public final boolean applicable,configFound,standalone;
        public final String packPath;
        public final int dictId;
        public final boolean checksum;
        Result(byte[] r,byte[] d,byte[] c,List<Field> f,String t,boolean a,int id,boolean ck,
               boolean found,String path,boolean direct) {
            raw=r;dict=d;compressed=c;fields=f;report=t;applicable=a;
            dictId=id;checksum=ck;configFound=found;packPath=path;standalone=direct;
        }
    }
    private static final class Part {
        final int off,len;
        Part(int o,int n){off=o;len=n;}
    }
    private static final class Frame {
        final int dictId;
        final boolean checksum;
        Frame(int id, boolean ck){dictId=id;checksum=ck;}
    }
    private static final class Sarc {
        final byte[] src;
        final Map<String,Part> parts=new HashMap<>();
        final boolean little;
        private Sarc(byte[] b) throws IOException {
            src=b;
            if(b.length<32 || !ascii(b,0,4).equals("SARC"))
                throw new IOException("Pacote descompactado não é arquivo SARC.");
            little=(b[6]&255)==255&&(b[7]&255)==254;
            if(!little && !((b[6]&255)==254&&(b[7]&255)==255))
                throw new IOException("SARC com BOM inválido.");
            int header=u16(b,4,little), data=read32(b,12,little);
            if(header<20||data<0||data>b.length||header+12>b.length||
               !ascii(b,header,4).equals("SFAT"))
                throw new IOException("Cabeçalho SFAT ausente.");
            int n=u16(b,header+6,little);
            int sfnt=header+12+16*n;
            if(n>10000 || sfnt+8>b.length || !ascii(b,sfnt,4).equals("SFNT"))
                throw new IOException("Entradas SARC inválidas.");
            int names=sfnt+8;
            for(int i=0;i<n;i++) {
                int row=header+12+16*i;
                long attr=Integer.toUnsignedLong(read32(b,row+4,little));
                int start=read32(b,row+8,little), end=read32(b,row+12,little);
                if(start<0||end<start||data>b.length-end)
                    throw new IOException("Intervalo de recurso SARC inválido.");
                String name;
                if((attr>>>24)!=0) {
                    long startName=names+(attr&0xffffL)*4L;
                    if(startName>=data||startName<names)
                        throw new IOException("Nome de recurso SARC fora dos limites.");
                    int k=(int)startName;
                    while(k<data&&b[k]!=0) k++;
                    if(k==data||k-(int)startName>1024)
                        throw new IOException("Nome de recurso SARC inválido.");
                    name=new String(b,(int)startName,k-(int)startName,StandardCharsets.UTF_8);
                } else {
                    name=Long.toHexString(Integer.toUnsignedLong(read32(b,row,little)));
                }
                if(parts.put(name,new Part(data+start,end-start))!=null)
                    throw new IOException("Nome de recurso SARC duplicado.");
            }
        }
    }
    private static final class Byml {
        final byte[] raw;
        final int start,end;
        final boolean little;
        final List<String> keys;
        final ArrayList<Field> entries=new ArrayList<>();
        final Set<Integer> seen=new HashSet<>();
        final String filename;
        Byml(byte[] b, String file, Part p) throws IOException {
            raw=b;start=p.off;end=p.off+p.len;filename=file;
            if(start<0||end>b.length||p.len<20)
                throw new IOException("BYML inválido: limites do arquivo.");
            String magic=ascii(b,start,2);
            if(!magic.equals("YB")&&!magic.equals("BY"))
                throw new IOException("Recurso não contém BYML reconhecível.");
            little=magic.equals("YB");
            int keyOff=read32(b,start+4,little);
            int root=read32(b,start+12,little);
            keys=keyOff!=0 ? readStringTable(keyOff) : new ArrayList<>();
            walk(root,"",0);
        }
        private int abs(long o,int n) throws IOException {
            long z=(long)start+o;
            if(o<0||z<start||z>Integer.MAX_VALUE||z+n>end)
                throw new IOException("BYML contém offset inválido.");
            return (int)z;
        }
        private int u24(int pos) {
            return little ?
                ((raw[pos]&255)|((raw[pos+1]&255)<<8)|((raw[pos+2]&255)<<16)) :
                (((raw[pos]&255)<<16)|((raw[pos+1]&255)<<8)|(raw[pos+2]&255));
        }
        private List<String> readStringTable(int local) throws IOException {
            int at=abs(Integer.toUnsignedLong(local),4);
            if((raw[at]&255)!=0xc2) throw new IOException("Tabela de nomes BYML ausente.");
            int n=u24(at+1);
            if(n>100000)throw new IOException("Tabela BYML grande demais.");
            int entriesEnd=abs(Integer.toUnsignedLong(local)+4, (n+1)*4);
            List<String> out=new ArrayList<>();
            for(int i=0;i<n;i++) {
                long rel=Integer.toUnsignedLong(read32(raw,at+4+4*i,little));
                int p=abs(Integer.toUnsignedLong(local)+rel,1);
                int k=p;
                while(k<end&&raw[k]!=0) k++;
                if(k>=end||k-p>2048) throw new IOException("String BYML inválida.");
                out.add(new String(raw,p,k-p,StandardCharsets.UTF_8));
            }
            return out;
        }
        private void walk(int local,String parent,int depth) throws IOException {
            if(depth>64)throw new IOException("BYML recursivo além do permitido.");
            int off=abs(Integer.toUnsignedLong(local),4);
            if(!seen.add(off))return;
            if(seen.size()>60000) throw new IOException("BYML grande demais para inspeção.");
            int kind=raw[off]&255,n=u24(off+1);
            if(n>100000) throw new IOException("Contêiner BYML com muitas entradas.");
            for(int i=0;i<n;i++) {
                String key; int valType,word;
                if(kind==0xc1) {
                    int p=abs(Integer.toUnsignedLong(local)+4+8L*i,8);
                    int id=u24(p);
                    if(id>=keys.size()) throw new IOException("Chave BYML fora da tabela.");
                    key=keys.get(id);valType=raw[p+3]&255;word=p+4;
                } else if(kind==0xc0) {
                    int t=abs(Integer.toUnsignedLong(local)+4+i,1);
                    int padded=(n+3)&~3;
                    word=abs(Integer.toUnsignedLong(local)+4+padded+4L*i,4);
                    key="["+i+"]";valType=raw[t]&255;
                } else if(kind==0x20||kind==0x21) {
                    int sz=kind==0x20?8:12;
                    int p=abs(Integer.toUnsignedLong(local)+4L+sz*i,sz);
                    long hash=kind==0x20?Integer.toUnsignedLong(read32(raw,p,little)):
                        read64(raw,p,little);
                    key="#"+Long.toHexString(hash);
                    int typePos=abs(Integer.toUnsignedLong(local)+4L+sz*n+i,1);
                    valType=raw[typePos]&255;word=p+sz-4;
                } else {
                    if(depth==0)throw new IOException("Raiz BYML sem contêiner reconhecido.");
                    return;
                }
                String full=parent.isEmpty()?key:parent+"/"+key;
                if(valType==0xc0||valType==0xc1||valType==0x20||valType==0x21)
                    walk(read32(raw,word,little),full,depth+1);
                else if(valType==0xd1||valType==0xd3||valType==0xd2) {
                    long value=valType==0xd1?read32(raw,word,little):
                        valType==0xd3?Integer.toUnsignedLong(read32(raw,word,little)):
                        Float.floatToIntBits(Float.intBitsToFloat(read32(raw,word,little)));
                    entries.add(new Field(filename,full,key,valType,word,value));
                }
            }
        }
    }
    private static int u16(byte[] b,int at,boolean le) {
        return le?((b[at]&255)|((b[at+1]&255)<<8)):
            (((b[at]&255)<<8)|(b[at+1]&255));
    }
    private static int read32(byte[] b,int at,boolean le) {
        return ByteBuffer.wrap(b,at,4).order(le?ByteOrder.LITTLE_ENDIAN:ByteOrder.BIG_ENDIAN).getInt();
    }
    private static long read64(byte[] b,int at,boolean le){
        return ByteBuffer.wrap(b,at,8).order(le?ByteOrder.LITTLE_ENDIAN:ByteOrder.BIG_ENDIAN).getLong();
    }
    private static String ascii(byte[] b,int off,int n) {
        return new String(b,off,n,StandardCharsets.US_ASCII);
    }
    private static Frame frame(byte[] data) throws IOException {
        if(data.length<8|| (data[0]&255)!=0x28||(data[1]&255)!=0xb5||
           (data[2]&255)!=0x2f||(data[3]&255)!=0xfd)
            throw new IOException("Recurso não possui frame Zstd.");
        int fhd=data[4]&255, idFlag=fhd&3, count= new int[]{0,1,2,4}[idFlag];
        int pos=5+(((fhd>>5)&1)==0?1:0), id=0;
        if(pos+count>data.length)throw new IOException("Frame Zstd incompleto.");
        for(int i=0;i<count;i++) id|=(data[pos+i]&255)<<(i*8);
        return new Frame(id,(fhd&4)!=0);
    }
    private static byte[] decompress(byte[] packed,byte[] dict,int cap) throws IOException {
        if(packed.length==0||packed.length>cap)
            throw new IOException("Recurso comprimido fora do limite de memória.");
        try(ZstdDecompressCtx dc=new ZstdDecompressCtx()) {
            if(dict!=null)dc.loadDict(dict);
            // We deliberately use a capped maximum, even with malformed
            // frame headers, rather than trusting attacker-supplied sizes.
            byte[] raw=dc.decompress(packed,cap);
            if(raw.length==0||raw.length>cap)throw new IOException("Zstd vazio ou muito grande.");
            return raw;
        }catch(RuntimeException e) {
            throw new IOException("Falha ao descompactar recurso Zstd: "+e.getMessage(),e);
        }
    }
    private static byte[] dictionary(byte[] input) throws IOException {
        byte[] raw=ascii(input,0,Math.min(4,input.length)).equals("SARC")?
            input:decompress(input,null,MAX_DICT);
        if(!ascii(raw,0,Math.min(4,raw.length)).equals("SARC"))
            return raw; // Already the raw pack.zsdic
        Sarc sarc=new Sarc(raw);
        for(Map.Entry<String,Part> e:sarc.parts.entrySet()) {
            if(e.getKey().endsWith("pack.zsdic")) {
                Part p=e.getValue();
                byte[] bytes=Arrays.copyOfRange(raw,p.off,p.off+p.len);
                if(bytes.length>MAX_DICT)throw new IOException("Dicionário muito grande.");
                return bytes;
            }
        }
        throw new IOException("Dicionário pack.zsdic ausente de ZsDic.pack.zs.");
    }
    /** Reads actual pack and emits a diagnosis without any destructive edits. */
    public static Result inspect(byte[] pack,byte[] zsdic,String provenance) throws IOException {
        return inspect(pack,zsdic,provenance,PACK_PATH);
    }
    public static Result inspect(byte[] pack,byte[] zsdic,String provenance,
                                 String sourcePath) throws IOException {
        Frame f=frame(pack);
        byte[] dict=dictionary(zsdic);
        byte[] raw=decompress(pack,dict,MAX_PACK);
        Sarc sarc=new Sarc(raw);
        List<Field> fields=new ArrayList<>();
        StringBuilder log=new StringBuilder();
        log.append("Ocarina Shadow Tool 0.1\n").append(provenance)
           .append("\nPack Zstd dictId=").append(Integer.toUnsignedString(f.dictId))
           .append(", checksum=").append(f.checksum).append('\n');
        int candidateFiles=0;
        boolean safeEndian=true;
        for(Map.Entry<String,Part> e:sarc.parts.entrySet()) {
            String filename=e.getKey();
            if(filename.contains("ModelSceneConfigParam")&&filename.endsWith(".bgyml")) {
                candidateFiles++;
                log.append("\nBYML: ").append(filename).append('\n');
                Byml config=new Byml(raw,filename,e.getValue());
                if(!config.little) {
                    safeEndian=false;
                    log.append("BYML big-endian: patch recusado até suporte explícito.\n");
                }
                int hits=0;
                for(Field v:config.entries) if(isShadowField(v)) {
                    fields.add(v);
                    log.append(" · ").append(v.line()).append('\n');
                    if(++hits>1500) throw new IOException("Configuração de sombras excedeu limite de campos.");
                }
                if(hits==0) log.append("Sem chaves de sombra com nomes legíveis.\n");
                int suspects=0;
                for(Field v:config.entries) {
                    if((v.value==1024L||v.value==4096L) && suspects++<70)
                        log.append(" · SOMENTE CANDIDATO (não alterado): ")
                           .append(v.line()).append('\n');
                }
                if(suspects>70)log.append(" · Outros valores 1024/4096 omitidos: ")
                    .append(suspects-70).append('\n');
            }
        }
        if(candidateFiles==0) {
            log.append("\nO ModelSceneConfigParam/Main não está neste pack inspecionado.\n")
               .append("Outros recursos relevantes:\n");
            sarc.parts.keySet().stream()
                .filter(s->s.toLowerCase().contains("shadow") || s.contains("ModelScene"))
                .limit(30).forEach(s->log.append(" · ").append(s).append('\n'));
        }
        boolean patchable=false;
        try {
            select(fields,512,2048);
            if(!safeEndian)throw new IOException("BYML de sombra não é little-endian.");
            patchable=true;
            log.append("\nCampos de dimensões reconhecidos; patch 512/2048 habilitado.\n");
        } catch(IOException e) {
            log.append("\nPatch BLOQUEADO: ").append(e.getMessage()).append('\n')
                .append("Exporte este diagnóstico para análise; o NUP original não foi alterado.\n");
        }
        return new Result(raw,dict,pack,fields,log.toString(),patchable,f.dictId,f.checksum,
            candidateFiles>0,sourcePath,false);
    }
    /**
     * Full patch support for a verified, uncompressed standalone BYML in RomFS.
     * A .zs resource is intentionally not treated as plain BYML.
     */
    public static Result inspectStandalone(byte[] raw,String path) throws IOException {
        if(!path.contains("ModelSceneConfigParam") || !path.endsWith(".bgyml"))
            throw new IOException("Não é um ModelSceneConfigParam .bgyml.");
        Byml byml=new Byml(raw,path,new Part(0,raw.length));
        ArrayList<Field> shadow=new ArrayList<>();
        StringBuilder log=new StringBuilder("Ocarina Shadow Tool 0.2\n")
            .append("Origem: ").append(path).append('\n');
        for(Field field:byml.entries) if(isShadowField(field)) {
            shadow.add(field);
            log.append(" · ").append(field.line()).append('\n');
        }
        int suspects=0;
        for(Field field:byml.entries)
            if((field.value==1024L||field.value==4096L) && suspects++<70)
                log.append(" · CANDIDATO (somente leitura): ").append(field.line()).append('\n');
        boolean canPatch=false;
        try {
            if(!byml.little)throw new IOException("BYML big-endian não pode ser alterado.");
            select(shadow,512,2048);
            canPatch=true;
            log.append("Dimensões de sombra reconhecidas. Overlay direto autorizado.\n");
        } catch(IOException ex) {
            log.append("Patch BLOQUEADO: ").append(ex.getMessage()).append('\n');
        }
        return new Result(raw,null,raw,shadow,log.toString(),canPatch,0,false,true,path,true);
    }

    /** Examine a named standalone BYML, even when it is not packed in Bootup. */
    public static String describeStandalone(byte[] resource,String path) throws IOException {
        if(resource.length<20)throw new IOException("BYML vazio ou inválido.");
        Byml byml=new Byml(resource,path,new Part(0,resource.length));
        StringBuilder text=new StringBuilder("Recurso BYML: ").append(path).append('\n');
        int hits=0;
        for(Field field:byml.entries) {
            String name=field.path.toLowerCase(java.util.Locale.ROOT);
            if(name.contains("shadow")||name.contains("size")||name.contains("resolution")) {
                text.append(" · ").append(field.line()).append('\n');
                if(++hits>=150) {text.append("... limitado a 150 campos\n");break;}
            }
        }
        if(hits==0)text.append("Nenhum campo legível relacionado a sombra/resolução.\n");
        text.append("Arquivo direto: exportação de patch ainda não habilitada.\n");
        return text.toString();
    }
    private static Map<Integer,Integer> select(List<Field> fields,i
    // Names and dimensions verified from the real Ocarina BASE v65536 RomFS
    // diagnosis. The UI variant differs: its 4096 depth map must not be
    // blindly reduced by the gameplay profile.
    public static final String MAIN_CONFIG=
        "gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml";

    private static boolean isShadowField(Field v) {
        String leaf=v.leaf.toLowerCase(java.util.Locale.ROOT);
        return leaf.contains("shadow") || leaf.startsWith("staticsdw");
    }

    private static Map<Integer,Integer> select(List<Field> fields,int dyn,int stat) throws IOException {
        if(dyn!=512 && dyn!=256)
            throw new IOException("Resolução dinâmica permitida: 512 ou 256.");
        if(stat!=2048 && stat!=1024)
            throw new IOException("Resolução estática permitida: 2048 ou 1024.");
        String[] keys={"DepthShadowTexWidth","DepthShadowTexHeight","StaticSdwWidth"};
        int[] expected={1024,1024,4096};
        int[] targets={dyn,dyn,stat};
        Map<Integer,Integer> edits=new HashMap<>();
        for(int i=0;i<keys.length;i++) {
            Field match=null;
            for(Field v:fields) {
                if(!MAIN_CONFIG.equals(v.file) || !keys[i].equals(v.leaf))continue;
                if(match!=null)
                    throw new IOException("Campo de sombra duplicado: "+keys[i]);
                match=v;
            }
            if(match==null)
                throw new IOException("Campo de sombra do Main ausente: "+keys[i]);
            if(!keys[i].equals(match.path))
                throw new IOException("Campo fora da raiz esperada: "+match.path);
            if(match.type!=0xd1 || match.value!=expected[i])
                throw new IOException("Tipo ou tamanho inesperado em "+keys[i]+": "+match.line());
            if(edits.put(match.offset,targets[i])!=null)
                throw new IOException("Dois campos compartilham o mesmo offset.");
        }
        return edits;
    }
ent SARC. */
    public static byte[] makeOverlay(Result r,int dynamic,int stat) throws IOException {
        if(!r.applicable)throw new IOException("Diagnóstico não autorizou um patch seguro.");
        Map<Integer,Integer> edits=select(r.fields,dynamic,stat);
        byte[] modified=r.raw.clone();
        for(Map.Entry<Integer,Integer> e:edits.entrySet()) {
            int off=e.getKey();
            if(off<0||off+4>modified.length)throw new IOException("Offset de sombra fora do pacote.");
            ByteBuffer.wrap(modified,off,4).order(ByteOrder.LITTLE_ENDIAN).putInt(e.getValue());
        }
        boolean changed=false;
        for(int i=0;i<r.raw.length;i++) if(r.raw[i]!=modified[i]) {
            changed=true;boolean allowed=false;
            for(int off:edits.keySet())if(i>=off&&i<off+4)allowed=true;
            if(!allowed)throw new IOException("Modificação fora dos campos validados.");
        }
        if(!changed)throw new IOException("Nenhuma dimensão foi alterada.");
        if(r.standalone) return modified;
        byte[] compressed;
        try(ZstdCompressCtx ctx=new ZstdCompressCtx()) {
            compressed=ctx.setLevel(15).setChecksum(r.checksum).setContentSize(true)
                .setDictID(r.dictId!=0).loadDict(r.dict).compress(modified);
        }catch(RuntimeException ex) {throw new IOException("Falha ao recomprimir pack: "+ex.getMessage(),ex);}
        Frame frame=frame(compressed);
        if(frame.dictId!=r.dictId||frame.checksum!=r.checksum)
            throw new IOException("Frame Zstd mudou ID de dicionário ou checksum.");
        if(!Arrays.equals(modified,decompress(compressed,r.dict,MAX_PACK)))
            throw new IOException("Verificação de descompressão do overlay falhou.");
        return compressed;
    }
}
