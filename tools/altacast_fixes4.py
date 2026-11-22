#!/usr/bin/env python3
"""
altacast_fixes4.py - fourth batch of AltaCast changes (applied at build time).

  Encoder comment: a personal note per encoder ("what is this encoder set for").
    * Basic Settings: new "Comment" field below "Reconnect Seconds"
      (the dialog is made 17 dialog units taller to make room)
    * main window list: new last column "Comment"
    * stored in the encoder's config file as EncoderComment=...
      (up to 255 bytes; the field accepts 200 bytes = 100 full-width characters)
    * it is NEVER sent to the server or written into the stream
    * the field is greyed out while the encoder is connected (same as the other locked fields)
    * old settings keep working: a saved column order / width list with 5 columns is
      accepted and the new column is appended at the end

Usage:  python tools/altacast_fixes4.py trunk/AltaCast/src
Idempotent, fails loudly if an anchor is missing.
"""
import re
import sys
from pathlib import Path

TAG = "altacast_fixes4"
MARK = TAG + ": comment"
GROW = 17           # dialog units added to the Basic Settings page


def fail(msg):
    print(TAG + ": ERROR: " + msg)
    sys.exit(1)


if len(sys.argv) != 2:
    fail("usage: altacast_fixes4.py <source dir>")
SRC = Path(sys.argv[1])
if not SRC.is_dir():
    fail("source dir not found: " + str(SRC))


def sub_once(text, pattern, repl, label, flags=0):
    new, n = re.subn(pattern, repl, text, flags=flags)
    if n != 1:
        fail("%s: expected exactly 1 match, found %d" % (label, n))
    return new


def after(text, pattern, insert, label):
    """insert text right after the (single) match of pattern"""
    return sub_once(text, pattern, lambda m: m.group(0) + insert, label)


def patch_file(rel, func):
    path = SRC / rel
    if not path.exists():
        fail("%s not found under %s" % (rel, SRC))
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("latin-1").replace("\r\n", "\n")
    new = func(text)
    if new == text:
        return
    if crlf:
        new = new.replace("\n", "\r\n")
    path.write_bytes(new.encode("latin-1"))
    print(TAG + ": patched " + rel)


def grow(m):
    return m.group(1) + str(int(m.group(2)) + GROW)


# ------------------------------------------------------------------ resource.h
def p_resource(t):
    if "IDC_ENCCOMMENT" in t:
        return t
    return after(
        t,
        r"#define IDC_RECONNECTSECS[^\n]*\n",
        "#define IDC_ENCCOMMENT\t\t\t\t\t1990\n",
        "resource.h IDC_RECONNECTSECS",
    )


# ------------------------------------------------------------------ altacast.rc
def rc_block(t, header, func, label):
    m = re.search(r"^" + header + r".*?^END", t, re.S | re.M)
    if not m:
        fail("altacast.rc: block not found: " + label)
    return t[: m.start()] + func(m.group(0)) + t[m.end():]


def p_rc(t):
    if "IDC_ENCCOMMENT" in t:
        return t

    def config_dlg(b):
        b = sub_once(b, r"(IDD_CONFIG DIALOGEX \d+, \d+, \d+, )(\d+)", grow, "rc IDD_CONFIG height")
        b = sub_once(b, r'(IDC_TAB1,"SysTabControl32",WS_TABSTOP,\d+,\d+,\d+,)(\d+)', grow, "rc tab height")
        b = sub_once(b, r'(DEFPUSHBUTTON\s+"OK",IDOK,\d+,)(\d+)', grow, "rc OK button")
        b = sub_once(b, r'(PUSHBUTTON\s+"Cancel",IDCANCEL,\d+,)(\d+)', grow, "rc Cancel button")
        return b

    def basic_page(b):
        b = sub_once(b, r"(IDD_PROPPAGE_LARGE DIALOGEX \d+, \d+, \d+, )(\d+)", grow, "rc page height")
        b = sub_once(b, r'(GROUPBOX\s+"General Settings",IDC_STATIC,\d+,\d+,\d+,)(\d+)', grow, "rc group height")
        m = re.search(r"EDITTEXT\s+IDC_RECONNECTSECS,\d+,(\d+),\d+,14[^\n]*\n", b)
        if not m:
            fail("altacast.rc: IDC_RECONNECTSECS not found")
        y = int(m.group(1)) + GROW
        b = b[: m.end()] + "    EDITTEXT        IDC_ENCCOMMENT,112,%d,190,14,ES_AUTOHSCROLL\n" % y + b[m.end():]
        return after(
            b,
            r'    RTEXT\s+"Reconnect Seconds",IDC_STATIC,\d+,\d+,\d+,8\n',
            '    RTEXT           "Comment",IDC_STATIC,33,%d,70,8\n' % (y + 2),
            "rc Reconnect label",
        )

    t = rc_block(t, r"IDD_CONFIG DIALOGEX", config_dlg, "IDD_CONFIG")
    t = rc_block(t, r"IDD_PROPPAGE_LARGE DIALOGEX", basic_page, "IDD_PROPPAGE_LARGE")
    return t


# ------------------------------------------------------------ BasicSettings.h/.cpp
def p_bs_h(t):
    if "m_EncComment" in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)CString([ \t]+)m_ReconnectSecs;\n",
        lambda m: m.group(0) + m.group(1) + "CString" + m.group(2) + "m_EncComment;   // " + MARK + "\n",
        "BasicSettings.h m_ReconnectSecs",
    )


def p_bs_cpp(t):
    if MARK in t:
        return t
    t = after(
        t,
        r'\tm_ReconnectSecs = _T\(""\);\n',
        '\tm_EncComment = _T("");   /* ' + MARK + ' */\n',
        "BasicSettings.cpp ctor",
    )
    t = after(
        t,
        r"\tDDX_Text\(pDX, IDC_RECONNECTSECS, m_ReconnectSecs\);\n",
        "\tDDX_Text(pDX, IDC_ENCCOMMENT, m_EncComment);\n",
        "BasicSettings.cpp DDX",
    )
    t = after(
        t,
        r"\tCDialog::OnInitDialog\(\);\n",
        "\t/* " + MARK + ": at most 200 bytes (100 full-width characters) */\n"
        "\t{\n"
        "\t\tCWnd *pComment = GetDlgItem(IDC_ENCCOMMENT);\n"
        "\t\tif (pComment != NULL) {\n"
        "\t\t\tpComment->SendMessage(EM_LIMITTEXT, 200, 0);\n"
        "\t\t}\n"
        "\t}\n",
        "BasicSettings.cpp OnInitDialog",
    )
    t = after(
        t,
        r"void CBasicSettings::ApplyEncoderLock\s*\(\)\s*\{\s*CWnd \*w;\n",
        "\t/* " + MARK + ": locked while connected, like the other fields */\n"
        "\t{\n"
        "\t\tCWnd *wc = GetDlgItem(IDC_ENCCOMMENT);\n"
        "\t\tif (wc != NULL) wc->EnableWindow(m_LockEncoder ? FALSE : TRUE);\n"
        "\t}\n",
        "BasicSettings.cpp ApplyEncoderLock",
    )
    return t


# ------------------------------------------------------------------- Config.cpp
def p_config(t):
    if "gEncComment" in t:
        return t
    t = sub_once(
        t,
        r"([ \t]*)basicSettings->m_ReconnectSecs = buf;\n",
        lambda m: m.group(0) + m.group(1) + "basicSettings->m_EncComment = g->gEncComment;   /* " + MARK + " */\n",
        "Config.cpp dialog <- globals",
    )
    t = sub_once(
        t,
        r"([ \t]*)g->gReconnectSec = atoi\(LPCSTR\(basicSettings->m_ReconnectSecs\)\);\n",
        lambda m: m.group(0)
        + m.group(1) + "strncpy(g->gEncComment, LPCSTR(basicSettings->m_EncComment), sizeof(g->gEncComment) - 1);   /* " + MARK + " */\n"
        + m.group(1) + "g->gEncComment[sizeof(g->gEncComment) - 1] = '\\000';\n",
        "Config.cpp globals <- dialog",
    )
    return t


# ------------------------------------------------------------------ libaltacast
def p_lib_h(t):
    if "gEncComment" in t:
        return t
    return after(
        t,
        r"\tchar_t\t\tgServGenre\[100\];\n",
        "\tchar_t\t\tgEncComment[256];\t/* " + MARK + ": personal note, never sent to the server */\n",
        "libaltacast.h gServGenre",
    )


def p_lib_cpp(t):
    if "EncoderComment" in t:
        return t
    t = after(
        t,
        r"\tmemset\(g->gServDesc, '\\000', sizeof\(g->gServDesc\)\);\n",
        "\tmemset(g->gEncComment, '\\000', sizeof(g->gEncComment));\n",
        "libaltacast.cpp init",
    )
    t = after(
        t,
        r'\tGetConfigVariable\(g, g->gAppName, "ServerGenre",[^\n]*\n',
        '\tGetConfigVariable(g, g->gAppName, "EncoderComment", "", g->gEncComment, sizeof(g->gEncComment), NULL);\n',
        "libaltacast.cpp GetConfigVariable",
    )
    t = after(
        t,
        r'\tPutConfigVariable\(g, g->gAppName, "ServerGenre", g->gServGenre\);\n',
        '\tPutConfigVariable(g, g->gAppName, "EncoderComment", g->gEncComment);\n',
        "libaltacast.cpp PutConfigVariable",
    )
    t = after(
        t,
        r'[ \t]*addConfigVariable\(g, "ServerGenre"\);\n',
        '    addConfigVariable(g, "EncoderComment");\n',
        "libaltacast.cpp addConfigVariable",
    )
    return t


# ----------------------------------------------------------------- MainWindow.cpp
def p_main(t):
    if MARK in t:
        return t
    t = sub_once(
        t,
        r"#define LIST_NUMCOLS 5\n",
        lambda m: "#define LIST_NUMCOLS 6   /* " + MARK + ": 5 -> 6 (Comment column) */\n",
        "MainWindow.cpp LIST_NUMCOLS",
    )
    t = after(
        t,
        r"\tm_Encoders\.SetColumnWidth\(4, 130\);\n",
        '\tm_Encoders.InsertColumn(5, "Comment");   /* ' + MARK + ' */\n'
        "\tm_Encoders.SetColumnWidth(5, 200);\n",
        "MainWindow.cpp Comment column",
    )
    t = sub_once(
        t,
        r"\tif \(ok && n == LIST_NUMCOLS && order\[0\] == 0\) \{\n",
        lambda m: "\t/* " + MARK + ": a column order saved with one column less stays valid (the new column goes last) */\n"
        "\tif (ok && n == LIST_NUMCOLS - 1 && !used[LIST_NUMCOLS - 1]) {\n"
        "\t\torder[n++] = LIST_NUMCOLS - 1;\n"
        "\t}\n"
        + m.group(0),
        "MainWindow.cpp column order",
    )
    t = sub_once(
        t,
        r"\t\tif \(m_Encoders\.GetCheck\(i\) != want\) \{\n",
        lambda m: "\t\tif (m_Encoders.GetItemText(i, 5) != g[i]->gEncComment) {   /* " + MARK + " */\n"
        "\t\t\tm_Encoders.SetItemText(i, 5, g[i]->gEncComment);\n"
        "\t\t}\n"
        + m.group(0),
        "MainWindow.cpp UpdateExtraColumns",
    )
    return t


patch_file("resource.h", p_resource)
patch_file("altacast.rc", p_rc)
patch_file("BasicSettings.h", p_bs_h)
patch_file("BasicSettings.cpp", p_bs_cpp)
patch_file("Config.cpp", p_config)
patch_file("libaltacast/libaltacast.h", p_lib_h)
patch_file("libaltacast/libaltacast.cpp", p_lib_cpp)
patch_file("MainWindow.cpp", p_main)
print(TAG + ": done")
