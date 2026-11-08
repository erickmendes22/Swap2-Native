package dev.nxnative.android;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import java.util.Locale;

/** Movable performance panel. Charts contain 500ms aggregate samples, not individual frame timings. */
final class PerformanceOverlay extends View {
    private final Paint paint = new Paint(3);
    private final Path path = new Path();
    private final float dp;
    private final GestureDetector gestures;
    private final float[][] history = new float[3][96];
    private int count, next;
    private long lastSample;
    private boolean detail, dragging;
    private float scale = .75f;
    private final android.content.SharedPreferences.OnSharedPreferenceChangeListener styleListener = (prefs, key) -> {
        if ("overlay_scale".equals(key) || "overlay_opacity".equals(key)) post(this::applyStyle);
    };
    private float downX, downY, startX, startY;
    private Overlay.Sample data = new Overlay.Sample();
    private String gpu = "GPU", driver = "", brand = "GPU";
    private final OnLayoutChangeListener parentLayout = (v,l,t,r,b,ol,ot,or,ob) -> { if (r-l != or-ol || b-t != ob-ot) { requestLayout(); post(this::place); } };

    PerformanceOverlay(Context c) {
        super(c); dp = getResources().getDisplayMetrics().density;
        detail = Prefs.of(c).getBoolean("overlay_detail", false);
        applyStyle();
        setContentDescription(c.getString(R.string.s2_overlay_gesture));
        gestures = new GestureDetector(c, new GestureDetector.SimpleOnGestureListener() {
            @Override public boolean onDown(MotionEvent e) { return true; }
            @Override public boolean onDoubleTapEvent(MotionEvent e) {
                if (e.getActionMasked() == MotionEvent.ACTION_UP && !dragging) {
                    detail = !detail; Prefs.of(c).edit().putBoolean("overlay_detail", detail).commit(); requestLayout(); invalidate();
                }
                return true;
            }
        });
    }

    void gpu(String name, String driverName) {
        gpu = name == null ? "GPU" : name; driver = driverName == null ? "" : driverName;
        String n = gpu.toLowerCase(Locale.ROOT);
        brand = n.contains("adreno") ? "QUALCOMM" : n.contains("mali") || n.contains("immortalis") ? "ARM" : n.contains("nvidia") ? "NVIDIA" : n.contains("xclipse") ? "SAMSUNG" : "GPU";
        invalidate();
    }

    void update(Overlay.Sample value) {
        applyStyle();
        long now = android.os.SystemClock.elapsedRealtime();
        if (lastSample != 0 && now - lastSample > 2000) { count = 0; next = 0; }
        lastSample = now;
        data = value;
        boolean mode = Prefs.of(getContext()).getBoolean("overlay_detail", false);
        if (detail != mode) { detail = mode; requestLayout(); }
        history[0][next] = data.fps; history[1][next] = data.ms; history[2][next] = data.rss < 0 ? Float.NaN : data.rss / 1048576f;
        next = (next + 1) % 96; count = Math.min(count + 1, 96); invalidate();
    }

    private void applyStyle() {
        android.content.SharedPreferences prefs = Prefs.of(getContext());
        float requested = prefs.getFloat("overlay_scale", .75f);
        float opacity = prefs.getFloat("overlay_opacity", 1);
        requested = Float.isFinite(requested) ? Math.max(.4f, Math.min(1.5f, requested)) : .75f;
        opacity = Float.isFinite(opacity) ? Math.max(.2f, Math.min(1, opacity)) : 1;
        if (requested != scale) { scale = requested; requestLayout(); }
        setAlpha(opacity);
    }
    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); Prefs.of(getContext()).registerOnSharedPreferenceChangeListener(styleListener); applyStyle(); if (getParent() instanceof View) ((View)getParent()).addOnLayoutChangeListener(parentLayout); post(this::place); }
    @Override protected void onDetachedFromWindow() { Prefs.of(getContext()).unregisterOnSharedPreferenceChangeListener(styleListener); if (getParent() instanceof View) ((View)getParent()).removeOnLayoutChangeListener(parentLayout); super.onDetachedFromWindow(); }
    @Override protected void onMeasure(int w, int h) {
        int maxW = getParent() instanceof View ? ((View)getParent()).getWidth() : 0;
        int maxH = getParent() instanceof View ? ((View)getParent()).getHeight() : 0;
        float fit = Math.min(scale, Math.min((maxW > 0 ? maxW : MeasureSpec.getSize(w)) / ((detail ? 270f : 520f) * dp), (maxH > 0 ? maxH : MeasureSpec.getSize(h)) / ((detail ? 286f : 34f) * dp)));
        setMeasuredDimension(Math.max(1, Math.round((detail ? 270 : 520)*dp*fit)), Math.max(1, Math.round((detail ? 286 : 34)*dp*fit)));
    }
    @Override protected void onSizeChanged(int w,int h,int ow,int oh) { post(this::place); }
    @Override public android.view.WindowInsets onApplyWindowInsets(android.view.WindowInsets insets) { requestLayout(); post(this::place); return super.onApplyWindowInsets(insets); }

    private float[] bounds() {
        View p = (View)getParent(); float l=0,t=0,r=p.getWidth()-getWidth(),b=p.getHeight()-getHeight();
        return new float[] {l,t,Math.max(l,r),Math.max(t,b)};
    }
    /** At the user's position (overlay_x / overlay_y, a fraction of the free space), moved sideways off the on-screen controls (TouchControls.freeX, 2026-11-08) */
    void place() {
        if (!(getParent() instanceof View)) return;
        float[] b=bounds(); float x=b[0]+(b[2]-b[0])*Prefs.of(getContext()).getFloat("overlay_x",1), y=b[1]+(b[3]-b[1])*Prefs.of(getContext()).getFloat("overlay_y",0);
        if (getParent() instanceof android.view.ViewGroup) {
            android.view.ViewGroup p=(android.view.ViewGroup)getParent();
            for (int i=0;i<p.getChildCount();i++) if (p.getChildAt(i) instanceof TouchControls) { x=((TouchControls)p.getChildAt(i)).freeX(x,getWidth(),y,y+getHeight(),b[2]); break; }
        }
        setX(x); setY(y);
    }
    @Override public boolean onTouchEvent(MotionEvent e) {
        if (e.getActionMasked()==MotionEvent.ACTION_DOWN) { dragging=false;downX=e.getRawX();downY=e.getRawY();startX=getX();startY=getY(); }
        if (e.getActionMasked()==MotionEvent.ACTION_MOVE) {
            float dx=e.getRawX()-downX,dy=e.getRawY()-downY;
            if (Math.hypot(dx,dy)>ViewConfiguration.get(getContext()).getScaledTouchSlop()) dragging=true;
            if (dragging) { float[] b=bounds();setX(Math.max(b[0],Math.min(b[2],startX+dx)));setY(Math.max(b[1],Math.min(b[3],startY+dy))); }
        }
        gestures.onTouchEvent(e);
        if (e.getActionMasked()==MotionEvent.ACTION_UP && dragging) {
            float[] b=bounds(); Prefs.of(getContext()).edit().putFloat("overlay_x",(getX()-b[0])/Math.max(1,b[2]-b[0])).putFloat("overlay_y",(getY()-b[1])/Math.max(1,b[3]-b[1])).commit();
        }
        return true;
    }
    private void text(Canvas c,String value,float x,float y,float size,int color) { paint.setColor(color);paint.setTextSize(size);paint.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));c.drawText(value,x,y,paint); }
    private static String number(float n) { return Float.isFinite(n) ? String.format(Locale.ROOT,"%.1f",n) : "--"; }
    private String fps() { return number(data.fps)+(Float.isFinite(data.presented) && data.presented > data.fps+1 ? " > "+number(data.presented) : ""); }
    @Override protected void onDraw(Canvas raw) {
        super.onDraw(raw); raw.save(); raw.scale(getWidth() / (detail ? 270f : 520f),getHeight() / (detail ? 286f : 34f));
        Canvas c=raw; float width=detail ? 270 : 520;
        paint.setColor(0xE6101829); c.drawRoundRect(new RectF(0,0,width,detail?286:34),10,10,paint);
        paint.setColor(0xFF50DBEB);c.drawRoundRect(new RectF(0,8,3,detail?278:26),2,2,paint);
        if (!detail) {
            text(c,fps()+" FPS",12,23,15,0xFF6DE6EF);
            text(c,number(data.ms)+" ms",145,23,13,0xFFFFFFFF);
            text(c,"RAM "+(data.rss<0?"--":String.format(Locale.ROOT,"%.0f MB",data.rss/1048576f)),235,23,13,0xFFE3EAF5);
            text(c,"SoC "+number(data.soc)+"°",360,23,13,0xFFFFD477);
            text(c,"BAT "+number(data.battery)+"°",443,23,13,0xFFFFD477);
        } else {
            // Manufacturer wordmark badge, not an unofficial recreation of a corporate logo.
            paint.setColor(0xFF203A50);c.drawRoundRect(new RectF(178,9,260,29),5,5,paint);text(c,brand,184,23,10,0xFF6DE6EF);
            text(c,"SWAP2 / MONITOR",12,23,10,0xFF92A5BC);
            String title=gpu; paint.setTextSize(12);while(title.length()>1 && paint.measureText(title)>245) title=title.substring(0,title.length()-1);
            text(c,title,12,47,12,0xFFFFFFFF);
            text(c,fps()+" FPS",12,72,19,0xFF6DE6EF);text(c,number(data.ms)+" ms",175,72,15,0xFFFFFFFF);
            chart(c,0,82,0xFF50DBEB,"FPS"); chart(c,1,123,0xFFFFCE78,"ms"); chart(c,2,164,0xFFA699FF,"RAM MB");
            text(c,"GPU "+number(data.gpuMs)+" ms  |  RAM "+(data.rss<0?"--":String.format(Locale.ROOT,"%.0f MB",data.rss/1048576f)),12,212,11,0xFFE3EAF5);
            text(c,"CPU cap "+data.cpu,12,229,10,0xFFE3EAF5);
            text(c,"SoC "+number(data.soc)+"°  BAT "+number(data.battery)+"°  "+(data.batteryLevel<0?"--":data.batteryLevel+"%"),12,246,11,0xFFFFD477);
            text(c,"Free RAM "+(data.total<=0?"--":String.format(Locale.ROOT,"%.1f / %.1f GB",data.available/1073741824f,data.total/1073741824f))+"  T:"+(data.thermal<0?"--":data.thermal),12,263,10,0xFFE3EAF5);
            text(c,getContext().getString(R.string.s2_overlay_sample_note),12,279,9,0xFF92A5BC);
        }
        raw.restore();
    }
    private void chart(Canvas c,int metric,int y,int color,String label) {
        paint.setColor(0xFF1B293D);c.drawRoundRect(new RectF(12,y,258,y+34),4,4,paint);
        float max=1;for(int i=0;i<count;i++) {float v=history[metric][i];if(Float.isFinite(v))max=Math.max(max,v);}
        path.reset(); boolean connected=false;
        for(int i=0;i<count;i++) {float v=history[metric][(next-count+i+96)%96];if(!Float.isFinite(v)){connected=false;continue;}float x=14+242*i/95f, py=y+32-28*v/max;if(connected)path.lineTo(x,py);else path.moveTo(x,py);connected=true;}
        paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.3f);paint.setColor(color);c.drawPath(path,paint);paint.setStyle(Paint.Style.FILL);text(c,label,17,y+11,8,0xFFAFC0D6);
    }
}
