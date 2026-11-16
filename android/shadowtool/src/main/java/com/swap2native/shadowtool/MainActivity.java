package com.swap2native.shadowtool;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Standalone Android SAF tool: choose any local .nup in the phone's Files UI,
 * choose base or update, inspect the game-owned ModelSceneConfigParam BYML,
 * save diagnostics, and export a patch ONLY after strict verification.
 *
 * The selected .nup is ALWAYS opened read-only; never copied or overwritten.
 * No broad storage, network, or all-files-access permissions.
 */
public final class MainActivity extends Activity {
    private static final int OPEN_NUP=21, SAVE_LOG=22, SAVE_OVERLAY=23;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private Uri selected;
    private List<NupReader.Package> versions=new ArrayList<>();
    private ShadowPack.Result result;
    private String report="";
    private TextView status, details, title;
    private Button pick, inspect, saveLog, patchNormal, patchLow;
    private Spinner packages;
    private int shadowDynamic=512, shadowStatic=2048;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(0xff151e2b);
        getWindow().setNavigationBarColor(0xff151e2b);
        ScrollView scroll=new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(0xff101b2b);
        LinearLayout body=new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(22,28,22,40);
        scroll.addView(body);

        title=new TextView(this);
        title.setText("Ocarina · Shadow Tool");
        title.setTextColor(0xffecf3ff);
        title.setTextSize(23);
        title.setTypeface(Typeface.DEFAULT,Typeface.BOLD);
        body.addView(title);
        TextView subtitle=text("Selecione um NUP dos arquivos do Android. "
            +"O NUP original nunca será modificado.",14,0xffb9cadc);
        subtitle.setPadding(0,10,0,14);body.addView(subtitle);
        pick=button(body,"1 · Selecionar arquivo .nup",()->openNup());
        packages=new Spinner(this);
        packages.setVisibility(View.GONE);
        body.addView(packages);
        inspect=button(body,"2 · Analisar mapas de sombra",()->analyse());
        inspect.setEnabled(false);
        status=text("Nenhum NUP selecionado.",14,0xffa4c7ea);
        status.setPadding(0,14,0,10);body.addView(status);
        details=text("",13,0xffe3e8f0);
        details.setTypeface(Typeface.MONOSPACE);
        details.setTextIsSelectable(true);
        body.addView(details);
        saveLog=button(body,"Salvar relatório (.txt)",()->exportReport());
        saveLog.setEnabled(false);
        TextView notice=text("A redução só é permitida quando os nomes e tamanhos "
            +"dos campos no ModelSceneConfigParam do NUP selecionado forem "
            +"reconhecidos. Caso contrário, salve o relatório.",13,0xffd0c7a5);
        notice.setPadding(0,14,0,14);body.addView(notice);
        patchNormal=button(body,"3 · Exportar sombras 512 / 2048",()->requestOverlay(512,2048));
        patchLow=button(body,"3 · Exportar sombras 256 / 1024",()->requestOverlay(256,1024));
        patchNormal.setEnabled(false);
        patchLow.setEnabled(false);
        TextView explain=text("O patch é salvo na pasta escolhida, preservando "
            +"o caminho original do recurso encontrado no NUP. Não é instalado "
            +"automaticamente no emulador nesta versão.",13,0xff90a9bd);
        explain.setPadding(0,10,0,0);body.addView(explain);
        setContentView(scroll);
    }
    private TextView text(String s,int size,int color) {
        TextView t=new TextView(this);t.setText(s);t.setTextSize(size);
        t.setTextColor(color);return t;
    }
    private Button button(LinearLayout body,String label,Runnable action) {
        Button b=new Button(this);
        b.setText(label);b.setAllCaps(false);
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);
        params.topMargin=9;
        body.addView(b,params);
        b.setOnClickListener(v->action.run());
        return b;
    }
    private void openNup() {
        Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.setType("*/*");
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        startActivityForResult(intent,OPEN_NUP);
    }
    private void locked(boolean busy) {
        pick.setEnabled(!busy);inspect.setEnabled(!busy && selected!=null && !versions.isEmpty());
        saveLog.setEnabled(!busy&&!report.isEmpty());
        patchNormal.setEnabled(!busy&&result!=null&&result.applicable);
        patchLow.setEnabled(!busy&&result!=null&&result.applicable);
    }
    private void runTask(String task,Task body) {
        locked(true);status.setText(task);
        worker.execute(()->{
            try {body.run();}
            catch(Exception e) {
                runOnUiThread(()->{
                    status.setText("Erro: "+e.getMessage());
                    details.setText(report+"\n"+e);
                    locked(false);
                });
            }
        });
    }
    @FunctionalInterface private interface Task {void run() throws Exception;}
    @Override protected void onActivityResult(int request,int resultCode,Intent data) {
        super.onActivityResult(request,resultCode,data);
        if(resultCode!=RESULT_OK||data==null||data.getData()==null)return;
        Uri uri=data.getData();
        if(request==OPEN_NUP) {
            selected=uri;
            versions.clear();result=null;report="";
            packages.setVisibility(View.GONE);
            runTask("Lendo apenas o índice NUP…",()->{
                List<NupReader.Package> found;
                try(ParcelFileDescriptor fd=getContentResolver().openFileDescriptor(uri,"r");
                    FileInputStream in=new FileInputStream(fd.getFileDescriptor())) {
                    NupReader reader=new NupReader(in.getChannel());
                    found=reader.ocarinaPackages();
                }
                if(found.isEmpty()) throw new IOException(
                    "NUP válido, porém não contém Ocarina (0400486024DEC000) base/atualização.");
                runOnUiThread(()->{
                    versions=found;
                    ArrayList<String> labels=new ArrayList<>();
                    for(NupReader.Package p:found)labels.add(p.label());
                    ArrayAdapter<String> adapter=new ArrayAdapter<>(this,
                        android.R.layout.simple_spinner_item,labels);
                    adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                    packages.setAdapter(adapter);
                    packages.setSelection(found.size()-1);
                    packages.setVisibility(View.VISIBLE);
                    status.setText("NUP verificado · selecione a versão e toque em Analisar.");
                    details.setText("Pacotes do Ocarina encontrados: "+found.size()
                        +"\nO arquivo não foi extraído nem modificado.");
                    locked(false);
                });
            });
        } else if(request==SAVE_LOG) {
            String snapshot=report;
            runTask("Salvando diagnóstico…",()->{
                try(OutputStream out=getContentResolver().openOutputStream(uri,"w")) {
                    if(out==null)throw new IOException("Não foi possível abrir arquivo de saída.");
                    out.write(snapshot.getBytes(StandardCharsets.UTF_8));
                }
                runOnUiThread(()->{status.setText("Relatório salvo.");locked(false);});
            });
        } else if(request==SAVE_OVERLAY) {
            final int dyn=shadowDynamic,stat=shadowStatic;
            final ShadowPack.Result snapshot=result;
            runTask("Verificando e criando o overlay…",()->{
                byte[] patch=ShadowPack.makeOverlay(snapshot,dyn,stat);
                Uri target=writeTree(uri,snapshot.packPath,patch);
                runOnUiThread(()->{
                    status.setText("Overlay criado com sucesso.");
                    new AlertDialog.Builder(this).setTitle("Patch exportado")
                        .setMessage("Arquivo salvo em "+snapshot.packPath
                            +" na pasta selecionada.\n\nO NUP original está intacto.\n"
                            +"O overlay ainda precisa ser importado no emulador.\n"+target)
                        .setPositiveButton("OK",null).show();
                    locked(false);
                });
            });
        }
    }
    private void analyse() {
        if(selected==null||versions.isEmpty())return;
        int pos=packages.getSelectedItemPosition();
        if(pos<0||pos>=versions.size())return;
        final NupReader.Package chosen=versions.get(pos);
        final Uri uri=selected;
        result=null;report="";
        runTask("Procurando parâmetros em todo o índice RomFS do NUP…",()->{
            ShadowDiscovery.Scan found;
            try(ParcelFileDescriptor fd=getContentResolver().openFileDescriptor(uri,"r");
                FileInputStream input=new FileInputStream(fd.getFileDescriptor())) {
                NupReader nup=new NupReader(input.getChannel());
                found=ShadowDiscovery.scan(nup,chosen);
            }
            runOnUiThread(()->{
                result=found.result;report=found.report;
                details.setText(report);
                status.setText(result!=null && result.applicable ?
                    "Dimensões reconhecidas no recurso "+result.packPath+". Pode exportar."
                    : "Varredura concluída; nenhum patch seguro identificado.");
                locked(false);
            });
        });
    }
    private void exportReport() {
        if(report.isEmpty())return;
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_TITLE,"Ocarina-shadow-diagnostico.txt");
        startActivityForResult(intent,SAVE_LOG);
    }
    private void requestOverlay(int dyn,int stat) {
        if(result==null||!result.applicable)return;
        shadowDynamic=dyn;shadowStatic=stat;
        new AlertDialog.Builder(this).setTitle("Salvar overlay do Ocarina")
            .setMessage("Exportar sombras dinâmicas "+dyn+"² e estáticas "+stat
                +"² em uma pasta escolhida por você?\n\n"
                +"O NUP original permanecerá intacto. "
                +"A compatibilidade e o FPS ainda precisam ser confirmados no jogo.")
            .setNegativeButton("Cancelar",null)
            .setPositiveButton("Escolher pasta",(d,w)->{
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                startActivityForResult(intent,SAVE_OVERLAY);
            }).show();
    }
    private Uri writeTree(Uri tree,String relative,byte[] data) throws IOException {
        Uri root=DocumentsContract.buildDocumentUriUsingTree(tree,
                    DocumentsContract.getTreeDocumentId(tree));
        String[] parts=relative.split("/");
        Uri parent=root;
        for(int i=0;i<parts.length;i++) {
            boolean last=i==parts.length-1;
            String mime=last?"application/octet-stream":DocumentsContract.Document.MIME_TYPE_DIR;
            Uri found=child(tree,parent,parts[i]);
            if(found!=null) {
                if(last)throw new IOException("O patch já existe na pasta escolhida. "
                    +"Escolha outra pasta para evitar sobrescrever.");
                parent=found;
            }else{
                Uri created=DocumentsContract.createDocument(getContentResolver(),parent,mime,parts[i]);
                if(created==null)throw new IOException("Provedor recusou criar "+parts[i]);
                parent=created;
            }
        }
        try(OutputStream out=getContentResolver().openOutputStream(parent,"w")) {
            if(out==null)throw new IOException("Não é possível gravar na pasta selecionada.");
            out.write(data);
        }
        return parent;
    }
    private Uri child(Uri tree,Uri parent,String name) throws IOException {
        Uri list=DocumentsContract.buildChildDocumentsUriUsingTree(tree,
                            DocumentsContract.getDocumentId(parent));
        String[] projection={DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                            DocumentsContract.Document.COLUMN_DISPLAY_NAME};
        try(Cursor c=getContentResolver().query(list,projection,null,null,null)) {
            if(c==null)throw new IOException("Não foi possível listar a pasta selecionada.");
            while(c.moveToNext())
                if(name.equals(c.getString(1)))
                    return DocumentsContract.buildDocumentUriUsingTree(tree,c.getString(0));
            return null;
        }catch(SecurityException e) {
            throw new IOException("Pasta sem permissão de gravação.",e);
        }
    }
    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }
}
