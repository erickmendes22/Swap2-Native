package com.swap2native.shadowtool;

import com.github.luben.zstd.ZstdDecompressCtx;

import java.io.EOFException;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/**
 * Bounded, seek-based reader for the real NUP 1.0-draft format, not for .nsp.
 * The system file picker gives a FileDescriptor; only its index and requested
 * pack files are read. The entire .nup is never copied into memory.
 *
 * Record layout follows dm/tools/nup.py (NUP spec 1.0-draft).
 * Superblock TOC SHA-256 and extracted-file SHA-256 are mandatory.
 */
public final class NupReader {
    public static final long OCARINA = 0x0400486024DEC000L;
    private static final int NONE = -1;
    private static final int HEADER = 0x80;
    private static final int TOC_HEADER = 0x30;
    private static final int PKG_SIZE = 0x40, DIR_SIZE = 0x18, FILE_SIZE = 0x50;
    private static final int MAX_TOC = 64 * 1024 * 1024;
    private static final int MAX_RESOURCE = 192 * 1024 * 1024;

    public static final class Package {
        public final long titleId;
        public final int version, kind, romfs;
        Package(long tid, int v, int k, int root) {
            titleId=tid; version=v; kind=k; romfs=root;
        }
        public String label() {
            return (kind == 0 ? "Base" : kind == 1 ? "Atualização" : "Adicional")
                + " v" + Integer.toUnsignedString(version)
                + " · " + String.format(Locale.ROOT, "%016X", titleId);
        }
    }
    public static final class Resource {
        public final byte[] bytes;
        public final String from;
        Resource(byte[] data, String where) { bytes = data; from = where; }
    }
    private final FileChannel channel;
    private final long size, blob;
    private final ByteBuffer toc;
    private final int nd, nf, pkCount, dirsOffset, filesOffset, kidsOffset, poolOffset, poolLen, kidCount;
    private final List<Package> packages = new ArrayList<>();
    private final int[] children;

    public NupReader(FileChannel channel) throws IOException {
        this.channel = channel;
        size = channel.size();
        if (size < HEADER) throw new IOException("O arquivo não possui cabeçalho NUP completo.");
        ByteBuffer sb = ByteBuffer.wrap(read(0, HEADER)).order(ByteOrder.LITTLE_ENDIAN);
        if (sb.get(0)!='N'||sb.get(1)!='U'||sb.get(2)!='P'||sb.get(3)!=1)
            throw new IOException("Arquivo não é NUP v1.");
        int headerSize = Short.toUnsignedInt(sb.getShort(4));
        int version = Short.toUnsignedInt(sb.getShort(6));
        long tocStart=sb.getLong(8), tocLen=sb.getLong(16);
        blob=sb.getLong(56);
        long declaredSize=sb.getLong(64);
        pkCount=sb.getInt(72);
        int flags=sb.getInt(76);
        if (headerSize < HEADER || version != 1 || flags != 0 ||
            declaredSize != size || tocStart != headerSize ||
            tocLen < TOC_HEADER || tocLen > MAX_TOC ||
            tocStart > size || tocLen > size - tocStart ||
            blob % 16 != 0 || blob < tocStart + tocLen || blob > size ||
            pkCount <= 0 || pkCount > 10000)
            throw new IOException("NUP inválido: dimensões, versão ou tamanho incompleto.");
        byte[] expectedTocHash = Arrays.copyOfRange(sb.array(),24,56);
        byte[] index = read(tocStart, (int)tocLen);
        if (!Arrays.equals(expectedTocHash, sha256(index)))
            throw new IOException("NUP corrompido: SHA-256 do índice não confere.");
        toc = ByteBuffer.wrap(index).order(ByteOrder.LITTLE_ENDIAN);
        if (toc.get(0)!='T'||toc.get(1)!='O'||toc.get(2)!='C'||toc.get(3)!=1
            || toc.getInt(4)!=pkCount)
            throw new IOException("Índice TOC não corresponde ao cabeçalho NUP.");
        long dirs=toc.getLong(8), files=toc.getLong(16);
        long pool=toc.getLong(24), poolSize=toc.getLong(32);
        if (dirs < 0 || dirs > 500000 || files < 0 || files > 800000 ||
            pool < 0 || poolSize < 0)
            throw new IOException("NUP possui quantidade inválida de arquivos.");
        nd=(int)dirs; nf=(int)files;
        long dOff=TOC_HEADER + (long)pkCount*PKG_SIZE;
        long fOff=dOff + (long)nd*DIR_SIZE;
        long kOff=fOff + (long)nf*FILE_SIZE;
        if (kOff>tocLen || pool<kOff || poolSize>tocLen-pool)
            throw new IOException("Índice NUP possui regiões fora dos limites.");
        dirsOffset=(int)dOff; filesOffset=(int)fOff; kidsOffset=(int)kOff;
        poolOffset=(int)pool; poolLen=(int)poolSize;
        long nk=0;
        for(int i=0;i<nd;i++) {
            long first=Integer.toUnsignedLong(toc.getInt(dirsOffset + i*DIR_SIZE + 8));
            long count=Integer.toUnsignedLong(toc.getInt(dirsOffset + i*DIR_SIZE + 12));
            if (first > Integer.MAX_VALUE || count > Integer.MAX_VALUE)
                throw new IOException("Índice NUP muito grande.");
            nk+=count;
        }
        if (nk>Integer.MAX_VALUE || nk*4>pool-kOff)
            throw new IOException("Filhos de diretório NUP fora do índice.");
        kidCount=(int)nk;
        children=new int[kidCount];
        for(int i=0;i<kidCount;i++) children[i]=toc.getInt(kidsOffset+i*4);
        for(int i=0;i<nd;i++) {
            int off=dirsOffset+i*DIR_SIZE;
            long first=Integer.toUnsignedLong(toc.getInt(off+8));
            long count=Integer.toUnsignedLong(toc.getInt(off+12));
            checkName(off);
            if (first+count>kidCount)
                throw new IOException("Diretório possui filhos inválidos.");
            String prior=null;
            for(long k=first;k<first+count;k++) {
                int child=children[(int)k];
                if(child<0 || (long)child >= (long)nd+nf)
                    throw new IOException("Índice aponta para arquivo inexistente.");
                String n=name(child);
                if(n.isEmpty() || n.contains("/") || n.contains("\u0000")
                   || n.equals(".") || n.equals("..") || (prior != null && prior.compareTo(n)>=0))
                    throw new IOException("Nome de entrada NUP inválido ou fora de ordem.");
                prior=n;
            }
        }
        for(int i=0;i<nf;i++) {
            int off=filesOffset+i*FILE_SIZE;
            checkName(off);
            long original=toc.getLong(off+8), extent=toc.getLong(off+16),
                 stored=toc.getLong(off+24);
            int codec=Byte.toUnsignedInt(toc.get(off+64));
            if(original<0||extent<0||stored<0||codec>1||toc.get(off+65)!=0
               || (original==0 && (stored!=0||codec!=0))
               || (original>0 && (extent<blob||extent%16!=0||stored==0
                                  || extent>size||stored>size-extent))
               || (codec==0&&stored!=original))
                throw new IOException("Extensão inválida no NUP: "+name(nd+i));
        }
        for(int i=0;i<pkCount;i++) {
            int off=TOC_HEADER+i*PKG_SIZE;
            long tid=toc.getLong(off);
            int root=toc.getInt(off+8), rom=toc.getInt(off+16),
                v=toc.getInt(off+20), k=Byte.toUnsignedInt(toc.get(off+24));
            if(root<0||root>=nd||k>=5|| (rom!=NONE&&(rom<0||rom>=nd)))
                throw new IOException("Registro de pacote NUP inválido.");
            packages.add(new Package(tid,v,k,rom));
        }
    }
    private byte[] read(long offset, int length) throws IOException {
        if(offset<0||length<0||offset>size||length>size-offset)
            throw new IOException("Leitura NUP fora dos limites.");
        byte[] out=new byte[length];
        ByteBuffer dst=ByteBuffer.wrap(out);
        int got=0;
        while(got<length) {
            int n=channel.read(dst,offset+got);
            if(n<0) throw new EOFException("Arquivo NUP cortado.");
            if(n==0) throw new IOException("Provedor de arquivos não permite leitura aleatória do NUP.");
            got+=n;
        }
        return out;
    }
    private void checkName(int rec) throws IOException {
        long start=Integer.toUnsignedLong(toc.getInt(rec)),
             count=Integer.toUnsignedLong(toc.getInt(rec+4));
        if(start>poolLen || count>poolLen-start)
            throw new IOException("Nome NUP fora da tabela de strings.");
    }
    private String name(int id) throws IOException {
        int off=id<nd?dirsOffset+id*DIR_SIZE:filesOffset+(id-nd)*FILE_SIZE;
        checkName(off);
        int s=toc.getInt(off), n=toc.getInt(off+4);
        return new String(toc.array(),poolOffset+s,n,StandardCharsets.UTF_8);
    }
    private int find(int root,String path) throws IOException {
        int current=root;
        for(String p:path.split("/")) {
            if(current<0 || current>=nd) return -1;
            int rec=dirsOffset+current*DIR_SIZE;
            int first=toc.getInt(rec+8), n=toc.getInt(rec+12), found=-1;
            for(int i=0;i<n;i++) {
                int child=children[first+i];
                if(name(child).equals(p)) {found=child;break;}
            }
            if(found<0) return -1;
            current=found;
        }
        return current>=nd?current:-1;
    }
    public List<Package> ocarinaPackages(){
        ArrayList<Package> matches=new ArrayList<>();
        for(Package p:packages)
            if(p.titleId==OCARINA && (p.kind==0||p.kind==1) && p.romfs!=NONE)
                matches.add(p);
        matches.sort(Comparator.comparingInt((Package p)->p.kind).thenComparingInt(p->p.version));
        return matches;
    }
    /**
     * List the selected package's RomFS index, without reading game file bodies.
     * Keeps a cycle guard and bounded traversal for malformed package metadata.
     */
    public List<String> listRomfsPaths(Package chosen) throws IOException {
        ArrayList<String> out=new ArrayList<>();
        if(chosen.romfs==NONE)return out;
        java.util.ArrayDeque<DirectoryWalk> queue=new java.util.ArrayDeque<>();
        java.util.HashSet<Integer> visited=new java.util.HashSet<>();
        queue.add(new DirectoryWalk(chosen.romfs,""));
        while(!queue.isEmpty()) {
            DirectoryWalk current=queue.removeFirst();
            if(!visited.add(current.directory))continue;
            if(visited.size()>200000||out.size()>300000)
                throw new IOException("Índice de arquivos excedeu limite seguro.");
            int rec=dirsOffset+current.directory*DIR_SIZE;
            int first=toc.getInt(rec+8), count=toc.getInt(rec+12);
            for(int i=0;i<count;i++) {
                int id=children[first+i];
                String full=current.prefix+name(id);
                if(full.length()>4096)throw new IOException("Caminho NUP grande demais.");
                if(id<nd)queue.addLast(new DirectoryWalk(id,full+"/"));
                else out.add(full);
            }
        }
        return out;
    }
    private static final class DirectoryWalk {
        final int directory;
        final String prefix;
        DirectoryWalk(int directory,String prefix) {
            this.directory=directory;
            this.prefix=prefix;
        }
    }

    /** TOC-only length check; does not load an archive into memory. */
    public long resourceLength(Package chosen,String path) throws IOException {
        int idx=find(chosen.romfs,path);
        if(idx<0 && chosen.kind==1)
            for(Package p:packages) if(p.kind==0 && p.titleId==OCARINA && p.romfs!=NONE) {
                idx=find(p.romfs,path);
                if(idx>=0)break;
            }
        if(idx<0)throw new IOException("Arquivo não existe no índice: "+path);
        return toc.getLong(filesOffset+(idx-nd)*FILE_SIZE+8);
    }

    public Resource resource(Package chosen,String path) throws IOException {
        int idx=find(chosen.romfs,path);
        Package source=chosen;
        if(idx<0 && chosen.kind==1) {
            for(Package p:packages) if(p.kind==0 && p.titleId==OCARINA && p.romfs!=NONE) {
                idx=find(p.romfs,path);
                if(idx>=0) {source=p;break;}
            }
        }
        if(idx<0) throw new IOException("Arquivo "+path+" não está neste pacote NUP. "
                                      +"Ele pode estar no arquivo BASE separado.");
        int pos=filesOffset+(idx-nd)*FILE_SIZE;
        long uncompressed=toc.getLong(pos+8), off=toc.getLong(pos+16), stored=toc.getLong(pos+24);
        int codec=Byte.toUnsignedInt(toc.get(pos+64));
        if(uncompressed>MAX_RESOURCE||stored>MAX_RESOURCE)
            throw new IOException("Recurso excede limite seguro de 192 MiB: "+path);
        byte[] extent=read(off,(int)stored);
        byte[] unpacked;
        if(codec==0) unpacked=extent;
        else {
            try(ZstdDecompressCtx ctx=new ZstdDecompressCtx()) {
                unpacked=ctx.decompress(extent,(int)uncompressed);
            } catch(RuntimeException e) {
                throw new IOException("Falha ao descompactar entrada Zstd do NUP: "+path,e);
            }
        }
        if(unpacked.length!=uncompressed || !Arrays.equals(sha256(unpacked),
            Arrays.copyOfRange(toc.array(),pos+32,pos+64)))
            throw new IOException("Arquivo do NUP não confere com seu SHA-256: "+path);
        return new Resource(unpacked,source.label());
    }
    private static byte[] sha256(byte[] data) throws IOException {
        try {return MessageDigest.getInstance("SHA-256").digest(data);}
        catch(NoSuchAlgorithmException e){throw new IOException(e);}
    }
}
