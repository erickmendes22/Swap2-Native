package com.swap2native.shadowtool;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;

/**
 * Search the selected NUP's RomFS index before choosing a resource to patch.
 * Neither the NUP nor the installed game is ever changed by this scanner.
 */
public final class ShadowDiscovery {
    private ShadowDiscovery() {}
    public static final class Scan {
        public final ShadowPack.Result result;
        public final String report;
        Scan(ShadowPack.Result result,String report) {
            this.result=result;this.report=report;
        }
    }
    public static Scan scan(NupReader nup,NupReader.Package chosen) throws IOException {
        LinkedHashSet<String> paths=new LinkedHashSet<>(nup.listRomfsPaths(chosen));
        // Updates may rely on files from the base package in the same NUP.
        if(chosen.kind==1) for(NupReader.Package p:nup.ocarinaPackages()) {
            if(p.kind==0)paths.addAll(nup.listRomfsPaths(p));
        }
        StringBuilder log=new StringBuilder("Ocarina Shadow Tool 0.2 — varredura RomFS\n");
        log.append("Pacote escolhido: ").append(chosen.label()).append('\n');
        log.append("Arquivos indexados: ").append(paths.size()).append('\n');
        ArrayList<String> matches=new ArrayList<>();
        ArrayList<String> direct=new ArrayList<>();
        ArrayList<String> packs=new ArrayList<>();
        for(String path:paths) {
            String lower=path.toLowerCase(Locale.ROOT);
            if(lower.contains("modelsceneconfigparam")) {
                matches.add(path);
                if(lower.endsWith(".bgyml"))direct.add(path);
            } else if(lower.contains("modelsceneshadowparam")) {
                matches.add(path);
            }
            if(path.startsWith("Pack/") && lower.endsWith(".pack.zs")
                 && !path.equals(ShadowPack.DICT_PATH))packs.add(path);
        }
        log.append("Caminhos ModelSceneConfigParam/ModelSceneShadowParam:\n");
        if(matches.isEmpty())log.append(" · Nenhum caminho direto no índice; verificando arquivos .pack.zs.\n");
        for(int i=0;i<Math.min(70,matches.size());i++)
            log.append(" · ").append(matches.get(i)).append('\n');
        if(matches.size()>70)log.append(" · ... mais ").append(matches.size()-70).append(" caminhos\n");
        ShadowPack.Result candidate=null;
        int inspectedDirect=0;
        for(String path:direct) {
            if(++inspectedDirect>40) {
                log.append("Limite seguro de 40 BYML diretos atingido.\n");
                break;
            }
            try {
                NupReader.Resource item=nup.resource(chosen,path);
                ShadowPack.Result found=ShadowPack.inspectStandalone(item.bytes,path);
                log.append("\n").append(found.report);
                if(found.applicable)return new Scan(found,log.toString());
                if(candidate==null)candidate=found;
            }catch(Exception ex) {
                log.append("Falha ao ler ").append(path).append(": ")
                    .append(ex.getMessage()).append('\n');
            }
        }
        // A missing direct file does not prove the setting is missing:
        // many RomFS resources are stored inside packed SARC archives.
        packs.sort(Comparator
            .comparingInt((String p)->p.equals(ShadowPack.PACK_PATH)?0:
                (p.toLowerCase(Locale.ROOT).contains("system") ||
                 p.toLowerCase(Locale.ROOT).contains("bootup") ||
                 p.toLowerCase(Locale.ROOT).contains("game"))?1:2)
            .thenComparing(String::compareTo));
        int attempted=0,failed=0,configPacks=0,skippedLarge=0;
        long readBudget=768L*1024*1024,readTotal=0;
        String dictionaryError=null;
        byte[] dict=null;
        try {
            dict=nup.resource(chosen,ShadowPack.DICT_PATH).bytes;
        }catch(IOException ex) {
            dictionaryError=ex.getMessage();
        }
        if(dict==null) {
            log.append("Dicionário de packs não encontrado: ")
                .append(dictionaryError).append('\n');
        }else for(String path:packs) {
            if(attempted>=60) {
                log.append("Limite de 60 packs atingido; ").append(packs.size()-attempted)
                   .append(" não foram inspecionados.\n");
                break;
            }
            try {
                long size=nup.resourceLength(chosen,path);
                if(size>192L*1024*1024) {
                    skippedLarge++;
                    log.append("Pack grande demais para leitura segura: ")
                       .append(path).append(" (").append(size).append(" bytes)\n");
                    continue;
                }
                if(readTotal+size>readBudget) {
                    log.append("Limite acumulado de 768 MiB atingido; varredura parcial.\n");
                    break;
                }
                readTotal+=size;
                attempted++;
                NupReader.Resource item=nup.resource(chosen,path);
                ShadowPack.Result found=ShadowPack.inspect(item.bytes,dict,
                    "Pacote "+chosen.label()+"\\nFonte pack: "+item.from,path);
                if(found.configFound) {
                    configPacks++;
                    log.append("\n").append(found.report);
                    if(found.applicable)return new Scan(found,log.toString());
                    if(candidate==null || !candidate.configFound)candidate=found;
                }else if(path.equals(ShadowPack.PACK_PATH)) {
                    // Keep the detailed previous Bootup diagnosis as evidence.
                    log.append("\n").append(found.report);
                }
            }catch(Exception ex) {
                failed++;
                log.append("Falha ao inspecionar ").append(path).append(": ")
                    .append(ex.getMessage()).append('\n');
            }
        }
        log.append("\\nResumo: ").append(inspectedDirect).append(" BYML diretos, ")
           .append(attempted).append("/").append(packs.size()).append(" packs tentados; ")
           .append(configPacks).append(" packs com ModelSceneConfigParam, ")
           .append(failed).append(" falhas, ").append(skippedLarge)
           .append(" packs grandes ignorados.\n");
        log.append("Nenhum patch será gerado sem dimensões 1024/4096 identificadas. ")
           .append("O NUP continua intacto.\n");
        return new Scan(candidate,log.toString());
    }
}
