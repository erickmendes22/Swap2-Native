package dev.nxnative.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Insets;
import android.text.TextUtils;
import android.view.WindowInsets;
import android.content.res.ColorStateList;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.util.Locale;

/** Presentation only. PrepareActivity owns the job, lifecycle and all actions. */
final class PrepareScreen {
    interface Actions { void pause(); void resume(); void play(); void back(); void importShaders(); void freeSpace(); void battery(); }
    private final Activity a;
    private final FrameLayout root;
    private final TextView name, version, headline, phase, percent, status, count, step, hint;
    private final ProgressBar bar;
    private final Button go, play, importShaders, extra;
    private Runnable extraAction;
    private final ImageView cover;
    private final TextView[] stages = new TextView[5];
    private String coverId;
    private PrepareState last;
    private final LinearLayout page, header, layout, identity, identityText, progress, stageRow;
    private final TextView local;
    private int fittedWidth = -1, fittedHeight = -1;
    private Insets safeInsets = Insets.NONE;

    private final Actions actions;

    PrepareScreen(Activity a, Actions actions) {
        this.a = a;
        this.actions = actions;
        Ui.immersive(a);
        root = new FrameLayout(a) {
            @Override protected void onMeasure(int widthSpec, int heightSpec) {
                fit(MeasureSpec.getSize(widthSpec) - safeInsets.left - safeInsets.right,
                        MeasureSpec.getSize(heightSpec) - safeInsets.top - safeInsets.bottom);
                super.onMeasure(widthSpec, heightSpec);
            }
            @Override public void onWindowFocusChanged(boolean focus) {
                super.onWindowFocusChanged(focus);
                if (focus) Ui.immersive(a);
            }
        };
        root.addView(Ui.background(a), new FrameLayout.LayoutParams(-1, -1));
        page = new LinearLayout(a);
        page.setOrientation(LinearLayout.VERTICAL);
        root.addView(page, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        root.setOnApplyWindowInsetsListener((v, in) -> {
            Insets i = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            if (!safeInsets.equals(i)) {
                safeInsets = i;
                fittedWidth = -1;
                v.requestLayout();
            }
            return in;
        });
        root.requestApplyInsets();
        header = Ui.header(a, Ui.back(a, v -> actions.back()), a.getString(R.string.s2_prep_title), Ui.badge(a, 32));
        page.addView(header);
        layout = new LinearLayout(a);
        layout.setBaselineAligned(false);
        LinearLayout.LayoutParams main = new LinearLayout.LayoutParams(-1, 0, 1);
        main.topMargin = Ui.dp(a, 8);
        page.addView(layout, main);
        identity = Ui.card(a);
        layout.addView(identity);
        cover = new ImageView(a);
        cover.setImageDrawable(Ui.icon(a, R.drawable.s2_ic_gamepad, R.color.bn_text_2));
        cover.setScaleType(ImageView.ScaleType.FIT_CENTER);
        cover.setBackground(Ui.round(Ui.col(a, R.color.bn_tint), Ui.dp(a, 14), 0, 0));
        cover.setClipToOutline(true);
        cover.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        identity.addView(cover);
        identityText = new LinearLayout(a);
        identityText.setOrientation(LinearLayout.VERTICAL);
        identity.addView(identityText);
        name = Ui.heading(a, "");
        name.setMaxLines(2);
        name.setEllipsize(TextUtils.TruncateAt.END);
        identityText.addView(name);
        version = Ui.small(a, "");
        oneLine(version);
        Ui.add(identityText, version, 4);
        local = Ui.small(a, a.getString(R.string.s2_prep_local));
        oneLine(local);
        Ui.add(identityText, local, 4);
        progress = Ui.card(a);
        layout.addView(progress);
        headline = Ui.text(a, "", 22, R.color.bn_text, 800);
        oneLine(headline);
        headline.setAccessibilityHeading(true);
        progress.addView(headline);
        LinearLayout top = Ui.row(a);
        phase = Ui.text(a, "", 13, R.color.bn_banana, 700);
        oneLine(phase);
        top.addView(phase, Ui.weight());
        percent = Ui.text(a, "", 28, R.color.bn_text, 800);
        oneLine(percent);
        top.addView(percent);
        progress.addView(top);
        bar = Ui.progress(a);
        bar.setMax(1000);
        LinearLayout.LayoutParams barParams = new LinearLayout.LayoutParams(-1, Ui.dp(a, 6));
        barParams.topMargin = Ui.dp(a, 6);
        progress.addView(bar, barParams);
        step = Ui.text(a, "", 15, R.color.bn_text, 600);
        oneLine(step);
        Ui.add(progress, step, 8);
        count = Ui.small(a, "");
        oneLine(count);
        Ui.add(progress, count, 2);
        status = Ui.body(a, "");
        status.setEllipsize(TextUtils.TruncateAt.END);
        status.setGravity(Gravity.TOP);
        status.setOnClickListener(v -> {
            if (last == null) return;
            // Details: the sentence, then the job's own words and where its logs are (for a bug report)
            String more = last.error.isEmpty() ? "" : "\n\n" + a.getString(R.string.s2_prep_details, last.error);
            more += "\n\n" + a.getString(R.string.s2_prep_logs_at, new java.io.File(last.file.getParentFile(), "logs").getPath());
            AlertDialog dialog = new AlertDialog.Builder(a).setTitle(headline.getText())
                    .setMessage(last.status + more).setPositiveButton(android.R.string.ok, null).show();
            TextView message = dialog.findViewById(android.R.id.message);
            if (message != null) message.setTextIsSelectable(true);
        });
        status.setTooltipText(a.getString(R.string.s2_prep_status_details));
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, 0, 1);
        statusParams.topMargin = Ui.dp(a, 6);
        progress.addView(status, statusParams);
        stageRow = Ui.row(a);
        stageRow.setBaselineAligned(false);
        int[] labels = {R.string.s2_prep_identify, R.string.s2_prep_rewrite, R.string.s2_prep_split,
                R.string.s2_prep_translate, R.string.s2_prep_pack};
        for (int i = 0; i < stages.length; i++) {
            stages[i] = Ui.small(a, a.getString(labels[i]));
            stages[i].setTag(a.getString(labels[i]));
            stages[i].setMaxLines(2);
            stages[i].setEllipsize(TextUtils.TruncateAt.END);
            stages[i].setGravity(Gravity.CENTER_VERTICAL);
            stages[i].setIncludeFontPadding(false);
            LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(0, -1, 1);
            if (i > 0) sp.leftMargin = Ui.dp(a, 6);
            stageRow.addView(stages[i], sp);
        }
        LinearLayout.LayoutParams stagesParams = new LinearLayout.LayoutParams(-1, Ui.dp(a, 36));
        stagesParams.topMargin = Ui.dp(a, 6);
        page.addView(stageRow, stagesParams);
        go = Ui.button(a, "", Ui.Kind.PREPARE, v -> {
            if (last == null) return;
            if (last.canPause) actions.pause(); else if (last.canResume) actions.resume();
        });
        play = Ui.button(a, a.getString(R.string.s2_play), Ui.Kind.PRIMARY, null);
        play.setOnClickListener(v -> {   // no Confirm: Play's one cue is the library's Launch as the game starts (or its Error when it refuses)
            if (last != null && last.canPlay) actions.play();
        });
        go.setEnabled(false);
        play.setEnabled(false);
        FrameLayout primary = new FrameLayout(a);
        primary.addView(go, new FrameLayout.LayoutParams(-1, -1));
        primary.addView(play, new FrameLayout.LayoutParams(-1, -1));
        play.setVisibility(View.GONE);
        LinearLayout footer = Ui.pair(a,
                Ui.button(a, a.getString(R.string.s2_prep_back), Ui.Kind.SOFT, v -> actions.back()), primary);
        // Stopped at the split or the translation: shaders made elsewhere (a computer, another phone) instead; Resume then skips those steps
        importShaders = Ui.button(a, a.getString(R.string.s2_shaders_import), Ui.Kind.SOFT, v -> actions.importShaders());
        LinearLayout.LayoutParams ip = Ui.weight();
        ip.leftMargin = Ui.dp(a, 10);
        footer.addView(importShaders, 1, ip);
        importShaders.setVisibility(View.GONE);
        // A stopped job's fix beside Try again: Free up space (no space), Allow in background (Android stopped it); hidden otherwise
        extra = Ui.button(a, "", Ui.Kind.SOFT, v -> { if (extraAction != null) extraAction.run(); });
        LinearLayout.LayoutParams ep = Ui.weight();
        ep.leftMargin = Ui.dp(a, 10);
        footer.addView(extra, 1, ep);
        extra.setVisibility(View.GONE);
        LinearLayout.LayoutParams footerParams = new LinearLayout.LayoutParams(-1, Ui.dp(a, 48));
        for (int i = 0; i < footer.getChildCount(); i++) {
            LinearLayout.LayoutParams fp = (LinearLayout.LayoutParams)footer.getChildAt(i).getLayoutParams();
            fp.height = -1;
            footer.getChildAt(i).setLayoutParams(fp);
        }
        footerParams.topMargin = Ui.dp(a, 6);
        page.addView(footer, footerParams);
        hint = Ui.small(a, a.getString(R.string.s2_prep_keep_open));
        oneLine(hint);
        hint.setGravity(Gravity.CENTER);
        Ui.add(page, hint, 4);
        LauncherEffects.enter(page, false);
    }

    private static void oneLine(TextView t) {
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        t.setIncludeFontPadding(false);
    }

    /** Fit the measured window, including resize/rotation without Activity recreation. No scrolling container. */
    private void fit(int width, int height) {
        if (width <= 0 || height <= 0 || width == fittedWidth && height == fittedHeight) return;
        fittedWidth = width; fittedHeight = height;
        float density = a.getResources().getDisplayMetrics().density;
        float w = width / density, h = height / density;
        boolean wide = w >= 600 || w > h, compact = h < 480, tiny = h < 320;
        FrameLayout.LayoutParams pp = (FrameLayout.LayoutParams)page.getLayoutParams();
        pp.width = Math.min(width, Ui.dp(a, 1100)); pp.height = height;
        pp.leftMargin = safeInsets.left; pp.topMargin = safeInsets.top;
        pp.rightMargin = safeInsets.right; pp.bottomMargin = safeInsets.bottom;
        page.setLayoutParams(pp);
        int gutter = Ui.dp(a, compact ? 12 : 20), vertical = Ui.dp(a, compact ? 8 : 16);
        page.setPadding(gutter, vertical, gutter, vertical);
        header.setMinimumHeight(0);
        header.setLayoutParams(new LinearLayout.LayoutParams(-1, Ui.dp(a, compact ? 48 : 56)));
        layout.setOrientation(wide ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        identity.setVisibility(tiny ? View.GONE : View.VISIBLE);
        identity.setOrientation(wide ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        int pad = Ui.dp(a, compact ? 12 : 18);
        identity.setPadding(pad, pad, pad, pad);
        progress.setPadding(pad, pad, pad, pad);
        identity.setLayoutParams(wide ? new LinearLayout.LayoutParams(Ui.dp(a, compact ? 172 : 230), -1)
                : new LinearLayout.LayoutParams(-1, Ui.dp(a, 104)));
        cover.setLayoutParams(wide ? new LinearLayout.LayoutParams(-1, 0, 1)
                : new LinearLayout.LayoutParams(Ui.dp(a, 72), -1));
        LinearLayout.LayoutParams info = wide ? new LinearLayout.LayoutParams(-1, -2)
                : new LinearLayout.LayoutParams(0, -1, 1);
        if (wide) info.topMargin = Ui.dp(a, 8); else info.leftMargin = Ui.dp(a, 12);
        identityText.setGravity(Gravity.CENTER_VERTICAL);
        identityText.setLayoutParams(info);
        LinearLayout.LayoutParams body = wide ? new LinearLayout.LayoutParams(0, -1, 1)
                : new LinearLayout.LayoutParams(-1, 0, 1);
        if (wide && !tiny) body.leftMargin = Ui.dp(a, 12);
        else if (!tiny) body.topMargin = Ui.dp(a, 10);
        progress.setLayoutParams(body);
        local.setVisibility(compact || !wide ? View.GONE : View.VISIBLE);
        headline.setTextSize(compact ? 18 : 24);
        percent.setTextSize(compact ? 26 : 34);
        status.setTextSize(compact ? 13 : 15);
        status.setMaxLines(compact ? 2 : 4);
        for (TextView t : stages) t.setTextSize(compact ? 11 : 12);
        LinearLayout.LayoutParams steps = (LinearLayout.LayoutParams)stageRow.getLayoutParams();
        steps.height = Ui.dp(a, compact ? 32 : 40);
        stageRow.setLayoutParams(steps);
        hint.setTextSize(11);
        hint.setVisibility(tiny ? View.GONE : View.VISIBLE);
    }

    View view() { return root; }

    void render(PrepareState s) { render(s, false, false); }

    /** quickPlay: Play's short job (the game starts when it is done); notifyOff: the progress notification is off */
    void render(PrepareState s, boolean quickPlay, boolean notifyOff) {
        last = s;
        Actions act = actions;
        name.setText(s.name);
        version.setText(s.version == 0 ? a.getString(R.string.s2_version_base) : a.getString(R.string.s2_version_update, s.version));
        if (!s.titleId.equals(coverId)) {
            coverId = s.titleId;
            String requested = coverId;
            android.graphics.Bitmap art = Covers.get(requested, b -> {
                if (requested.equals(coverId)) cover.setImageBitmap(b);
            });
            if (art != null) cover.setImageBitmap(art);
        }
        int label = s.canPlay ? R.string.s2_prep_ready : s.phase == PrepareState.Phase.FAILED ? R.string.s2_prep_failed
                : s.phase == PrepareState.Phase.PAUSED ? R.string.s2_prep_paused
                : s.phase == PrepareState.Phase.PENDING ? R.string.s2_prep_pending
                : s.phase == PrepareState.Phase.DONE ? R.string.s2_prep_review : R.string.s2_prep_title;
        int color = s.canPlay ? R.color.bn_leaf : s.phase == PrepareState.Phase.FAILED ? R.color.s2_coral
                : s.phase == PrepareState.Phase.PAUSED ? R.color.s2_warning : R.color.bn_banana;
        boolean quick = s.codeOnly && !s.canPlay && s.phase != PrepareState.Phase.FAILED;   // the short job: one bar, no stage list
        headline.setText(a.getString(quick ? R.string.s2_quick_title : label));
        stageRow.setVisibility(s.codeOnly ? View.GONE : View.VISIBLE);
        phase.setText(a.getString(R.string.s2_prep_step, s.step, s.steps));
        phase.setTextColor(Ui.col(a, color));
        percent.setText(String.format(Locale.getDefault(), "%d%%", (int) Math.floor(s.overall * 100)));
        bar.setProgress((int) Math.round(s.overall * 1000));
        bar.setProgressTintList(ColorStateList.valueOf(Ui.col(a, color)));
        // the time left on this phone: the current step at its measured rate, the rest at the phone's rates (Job.remaining)
        String left = s.phase == PrepareState.Phase.RUNNING || s.phase == PrepareState.Phase.PAUSED ? s.leftText(a) : "";
        step.setText(left.isEmpty() ? s.stepName : s.stepName + " · " + left);
        String said = s.saveFailed ? a.getString(R.string.s2_prep_save_failed) + " " + s.status : s.status;
        status.setText(said);
        status.setContentDescription(said + ". " + a.getString(R.string.s2_prep_status_details));
        count.setText(s.shadersImported ? a.getString(R.string.s2_prep_shaders_imported) : s.shadersTotal > 0 ? a.getString(R.string.s2_prep_processed, s.shadersDone, s.shadersTotal)
                : a.getString(R.string.s2_prep_count_pending));
        for (int i = 0; i < stages.length; i++) {
            boolean done = s.canPlay || i + 1 < s.step;
            stages[i].setText((done ? "✓  " : i + 1 == s.step ? "●  " : "○  ") + stages[i].getTag());
            stages[i].setTextColor(Ui.col(a, done ? R.color.bn_leaf : i + 1 == s.step ? color : R.color.bn_text_2));
        }
        go.setText(a.getString(s.canPause ? R.string.s2_prep_pause : s.phase == PrepareState.Phase.FAILED ? R.string.s2_prep_retry : R.string.s2_prep_resume));
        go.setEnabled(s.canPause || s.canResume);
        go.setVisibility(s.canPlay ? View.GONE : View.VISIBLE);
        play.setEnabled(s.canPlay);
        play.setVisibility(s.canPlay ? View.VISIBLE : View.GONE);
        importShaders.setVisibility(s.canImportShaders ? View.VISIBLE : View.GONE);
        boolean stopped = !s.canPause && !s.canPlay;
        if (stopped && s.why == GameFlow.Why.NO_SPACE) { extra.setText(a.getString(R.string.s2_free_space)); extraAction = act::freeSpace; }
        else if (stopped && (s.why == GameFlow.Why.KILLED || s.why == GameFlow.Why.REFUSED || s.why == GameFlow.Why.INTERRUPTED)) { extra.setText(a.getString(R.string.s2_prep_battery)); extraAction = act::battery; }
        else extraAction = null;
        extra.setVisibility(extraAction != null && !s.canImportShaders ? View.VISIBLE : View.GONE);
        hint.setText(a.getString(s.canPlay ? (quickPlay ? R.string.s2_quick_starting : R.string.s2_prep_ready_hint) : notifyOff && s.canPause ? R.string.s2_prep_no_notify : R.string.s2_prep_keep_open));
    }
}
