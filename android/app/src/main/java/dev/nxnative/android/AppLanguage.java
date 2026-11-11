package dev.nxnative.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.os.LocaleList;

import java.util.Locale;

/** App-selected locale and matching emulated Switch language, without
 * changing system-wide Locale defaults or affecting a running game.
 * Language changes take effect on the next game start, after the launcher
 * is recreated. Strings not yet localized fall back to the English base.
 */
final class AppLanguage {
    private AppLanguage() {}
    static final String[] CODES = {
        "", "en-US", "pt-BR", "es-ES", "es-419", "fr-FR",
        "de-DE", "it-IT", "ru-RU", "tr-TR", "pl-PL",
        "ja-JP", "ko-KR", "zh-Hans", "zh-Hant", "id-ID",
        "hi-IN", "nl-NL"
    };
    static final String[] LABELS = {
        "System / Automático", "English (US)", "Português (Brasil)",
        "Español (España)", "Español (Latinoamérica)", "Français",
        "Deutsch", "Italiano", "Русский", "Türkçe", "Polski",
        "日本語", "한국어", "简体中文", "繁體中文",
        "Bahasa Indonesia", "हिन्दी", "Nederlands"
    };

    static String selection(Context c) {
        SharedPreferences p = c.getSharedPreferences("launcher", Context.MODE_MULTI_PROCESS);
        String code = p.getString("ui_lang", "");
        if (code == null) return "";
        for (String c2 : CODES) if (c2.equals(code)) return code;
        return "";
    }
    static int selectedIndex(Context c) {
        String code = selection(c);
        for (int i=0; i<CODES.length; i++) if (CODES[i].equals(code)) return i;
        return 0;
    }
    static String selectedLabel(Context c) { return LABELS[selectedIndex(c)]; }

    static Locale effective(Context c) {
        String s=selection(c);
        if (!s.isEmpty()) return Locale.forLanguageTag(s);
        Configuration config=c.getResources().getConfiguration();
        LocaleList ls=config.getLocales();
        return ls!=null && !ls.isEmpty() ? ls.get(0) : Locale.getDefault();
    }
    static Context wrap(Context base) {
        String code=selection(base);
        if (code.isEmpty()) return base;
        Configuration config=new Configuration(base.getResources().getConfiguration());
        Locale chosen=Locale.forLanguageTag(code);
        config.setLocale(chosen);
        config.setLocales(new LocaleList(chosen));
        config.setLayoutDirection(chosen);
        return base.createConfigurationContext(config);
    }
    /** Horizon's language query reads exactly DM_LANG at process start. No
     * 'translated game' is invented: only languages actually supplied by
     * the user's RomFS/updates can appear in-game. */
    static String gameCode(Context c) {
        String choice=selection(c);
        if (!choice.isEmpty()) return choice;
        Locale l=effective(c);
        String tag=l.toLanguageTag();
        String lang=l.getLanguage();
        if ("pt".equals(lang)) return "PT".equalsIgnoreCase(l.getCountry()) ? "pt-PT":"pt-BR";
        if ("es".equals(lang)) return "ES".equalsIgnoreCase(l.getCountry()) ? "es-ES":"es-419";
        if ("zh".equals(lang)) return l.getScript().equals("Hant") || "TW".equalsIgnoreCase(l.getCountry()) ? "zh-Hant":"zh-Hans";
        if ("en".equals(lang)) return "GB".equalsIgnoreCase(l.getCountry()) ? "en-GB":"en-US";
        for (String c2:CODES) if (!c2.isEmpty() && c2.startsWith(lang+"-")) return c2;
        return tag.length()<=7 ? tag : "en-US"; // 8-byte nn::settings LanguageCode
    }
    static void pick(Activity a) {
        new AlertDialog.Builder(a)
            .setTitle(a.getString(R.string.s2_language))
            .setSingleChoiceItems(LABELS,selectedIndex(a),(dialog,which)->{
                dialog.dismiss();
                String previous=selection(a), selected=CODES[which];
                if (previous.equals(selected)) return;
                a.getSharedPreferences("launcher",Context.MODE_MULTI_PROCESS)
                    .edit().putString("ui_lang",selected).commit();
                a.recreate(); // only app UI; game process uses next launch
            })
            .setNegativeButton(android.R.string.cancel,null)
            .show();
    }
}
