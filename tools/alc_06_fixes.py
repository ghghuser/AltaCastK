#!/usr/bin/env python3
"""
alc_06_fixes.py - 追加の修正 (AltaCast)。05 の後に適用する

  1. Comment    接続中も Comment を編集できる (配信には送らない)
  2. 証明書     保存した指紋と違う証明書が来たら、新しい証明書を信頼するか確認する (標準は「いいえ」)
  3. AAC        一時バッファを広げ、上限を超えて書かない

使い方:  python tools/alc_06_fixes.py trunk/AltaCast/src
冪等。アンカーが見つからなければエラーで停止。
"""

import patchlib as P

TAG = "altacast_fixes"
P.init(TAG)
from patchlib import sub_once, sub_n, patch_file, c_wide  # noqa: E402


# 1. Comment は接続中も編集できる
def fix_comment(t):
    mark = TAG + ": comment"
    if mark in t:
        return t
    return sub_once(
        t,
        r"[ \t]*/\* altacast_ui: comment: locked while connected[^\n]*\n[ \t]*\{\n(?:[^\n]*\n){2}[ \t]*\}\n",
        lambda m: "\t/* " + mark + ": the comment stays editable while connected */\n",
        "comment lock",
    )


# 2. 保存した指紋と違う証明書
CHANGED_MSG = (
    "保存してある証明書と違う証明書が届きました。\n\n"
    "サーバー: %ls\n保存した指紋:\n%ls\n今回の指紋:\n%ls\n\n"
    "サーバーの証明書を更新した場合は変わります。心当たりがない場合は、偽のサーバーの可能性があるので「いいえ」を選んでください。\n\n"
    "新しい証明書を信頼して、以後この証明書だけを許可しますか？"
)


def fix_cert(t):
    mark = TAG + ": cert"
    if mark in t:
        return t
    # no more silent refusal: only log, then ask like the first time (but with the old fingerprint shown)
    t = sub_once(
        t,
        r"(if \(g->gTLSPinned\[0\] != '\\000'\) \{\n[^\n]*LOG_ERROR[^\n]*\n)[ \t]*return 0;\n",
        lambda m: m.group(1).replace("To trust a new certificate, delete ServerTLSTrustedCert in the config file.", "Asking whether to trust it."),
        "cert pinned",
    )
    new = (
        "\t/* " + mark + ": a different certificate than the trusted one */\n"
        "\tif (g->gTLSPinned[0] != '\\000') {\n"
        "\t\tWCHAR\twold[100];\n"
        "\t\tMultiByteToWideChar(CP_ACP, 0, g->gTLSPinned, -1, wold, 99);\n"
        "\t\twold[99] = 0;\n"
        '\t\t_snwprintf(msg, 1499, L"' + c_wide(CHANGED_MSG) + '", whost, wold, wfp);\n'
        "\t\tmsg[1499] = 0;\n"
        "\t}\n"
    )
    return sub_once(t, r"(?m)^[ \t]*answer = MessageBoxW\(", lambda m: new + m.group(0), "cert message")


# 3. AAC の一時バッファ
def fix_fifo(t):
    mark = TAG + ": fifo"
    if mark in t:
        return t
    t = sub_once(t, r"(g->samplesInput \* sizeof\(\s*float\s*\) \* )16\b",
                 lambda m: m.group(1) + "64 /* " + mark + " */", "fifo size")
    return sub_once(t, r"for\s*\(\s*int i = 0; i < numsamples; i\+\+\s*\)(?=\s*\{\s*g->faacFIFO\[currentFIFO\])",
                    lambda m: "for (int i = 0; i < numsamples && currentFIFO < (int) (g->samplesInput * 64); i++)", "fifo limit")


patch_file("BasicSettings.cpp", fix_comment)
patch_file("libaltacast/libaltacast.cpp", lambda t: fix_fifo(fix_cert(t)))
print(TAG + ": done")
