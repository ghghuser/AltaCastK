#!/usr/bin/env python3
"""
alc_03_encoders.py - エンコーダーの種類・品質まわり (AltaCast)

  1. AAC Quality     AAC は Quality 欄を使う (0/空 なら 100)。Bitrate 欄は無効
  2. OggVorbis       Quality を 0〜10 に制限、標準値を 3 に
  3. Quality の記憶  encoder type ごとに Quality を記憶 (AAC=100 / Ogg系=3)
  4. Ogg FLAC        録音ファイルに拡張子 .flac を付ける
  5. AAC Plus        接続直後に切れる問題 (altacast_aacp.ini をフルパスで書く、
                     チャンネルモードが空になる穴、失敗理由のログ表示)
  6. 使えない種類    一覧に全種類を出し、DLLがないものは下に「(DLLなし)」付き。
                     選ぶと原因をポップアップして選択を戻す
  7. ドロップダウン  自動並べ替えをやめる / 開いたリストの幅を最長項目に合わせる /
                     種類を切り替えた直後に補正値を画面へ反映

使い方:  python tools/alc_03_encoders.py trunk/AltaCast/src
冪等。アンカーが見つからなければエラーで停止。
"""

import re
import sys
from pathlib import Path

import patchlib as P

TAG = "altacast_encoders"
P.init(TAG)
SRC = P.SRC
from patchlib import fail, sub_once, sub_n, after, patch_file, c_wide  # noqa: E402,F401


# ----------------------------------------------------------------------
# 1. AAC の Quality
# ----------------------------------------------------------------------

MARK_AAC = "altacast_encoders: aac"


AAC_UI_BLOCK = """if (m_EncoderType == "AAC") {
\t\t/* %(m)s: faac is quality based. The bitrate and "Use bitrate" (Ogg only)
\t\t * are ignored, so only Quality is editable, and an empty/0 Quality
\t\t * (what the field holds after switching from another type) becomes 100. */
\t\tm_BitrateCtrl.EnableWindow(FALSE);
\t\tm_QualityCtrl.EnableWindow(TRUE);
\t\tif (m_QualityCtrl.GetSafeHwnd()) {
\t\t\tCString	aacQuality;

\t\t\tm_QualityCtrl.GetWindowText(aacQuality);
\t\t\tif (atoi(LPCSTR(aacQuality)) <= 0) {
\t\t\t\tm_QualityCtrl.SetWindowText(_T("100"));
\t\t\t\tm_Quality = _T("100");
\t\t\t}
\t\t}
""" % {"m": MARK_AAC}


def fix_aac_ui(t):
    if MARK_AAC in t:
        print("altacast_encoders: AAC settings (UI) already patched, skipped")
        return t
    t = sub_once(
        t,
        r'if \(m_EncoderType == "AAC"\) \{\n'
        r"\s*if \(m_UseBitrate\) \{\n\s*m_BitrateCtrl\.EnableWindow\(TRUE\);\n\s*m_QualityCtrl\.EnableWindow\(FALSE\);\n\s*\}\n"
        r"\s*else \{\n\s*m_QualityCtrl\.EnableWindow\(TRUE\);\n\s*m_BitrateCtrl\.EnableWindow\(FALSE\);\n\s*\}\n",
        lambda m: AAC_UI_BLOCK,
        "BasicSettings.cpp AAC branch of UpdateFields",
    )
    print("altacast_encoders: AAC settings (UI) fixed: Quality only, empty/0 -> 100")
    return t


def fix_aac_quality(t):
    if MARK_AAC in t:
        print("altacast_encoders: AAC quality default already patched, skipped")
        return t
    t = sub_once(
        t,
        r"([ \t]*)m_pConfig->quantqual = atoi\(g->gAACQuality\);\n",
        lambda m: m.group(1) + "m_pConfig->quantqual = (atoi(g->gAACQuality) > 0) ? atoi(g->gAACQuality) : 100;\t/* "
        + MARK_AAC + ": 0/empty -> 100 */\n",
        "libaltacast.cpp quantqual",
    )
    print("altacast_encoders: AAC quality 0/empty -> 100 in the encoder")
    return t


# ----------------------------------------------------------------------
# 2. OggVorbis の Quality
# ----------------------------------------------------------------------

# Ogg Vorbis Quality is 0..10 (x0.1 -> libvorbis 0.0..1.0; anything >= 10 is clamped to the
# maximum, about 500 kbps). The Quality field is shared with AAC (10..500), so the value 100
# set for AAC must not carry over to Ogg. Ogg default: 3 = what oggenc uses (about 112 kbps).
OGG_DEFAULT_QUALITY = "3"


MARK_OGG = "altacast_encoders: ogg"


OGG_UI_BLOCK = """\t\t/* %(m)s: Quality is 0..10 here. An empty value or the AAC value (100)
\t\t * must not carry over - 10 or more means maximum quality (about 500 kbps). */
\t\tif (m_QualityCtrl.GetSafeHwnd()) {
\t\t\tCString	oggQuality;

\t\t\tm_QualityCtrl.GetWindowText(oggQuality);
\t\t\tif (oggQuality.IsEmpty() || atof(LPCSTR(oggQuality)) < 0 || atof(LPCSTR(oggQuality)) > 10) {
\t\t\t\tm_QualityCtrl.SetWindowText(_T("%(q)s"));
\t\t\t\tm_Quality = _T("%(q)s");
\t\t\t}
\t\t}
""" % {"m": MARK_OGG, "q": OGG_DEFAULT_QUALITY}


def fix_ogg_ui(t):
    if MARK_OGG in t:
        print("altacast_encoders: Ogg quality (UI) already patched, skipped")
        return t
    t = sub_once(
        t,
        r'(if \(m_EncoderType == "OggVorbis"\) \{\n\s*m_UseBitrateCtrl\.EnableWindow\(TRUE\);\n)',
        lambda m: m.group(1) + OGG_UI_BLOCK,
        "BasicSettings.cpp OggVorbis branch of UpdateFields",
    )
    print("altacast_encoders: Ogg quality kept within 0..10 (fallback %s)" % OGG_DEFAULT_QUALITY)
    return t


def fix_ogg_default(t):
    """Initial Ogg quality (no config file yet): 0 (about 64 kbps) -> OGG_DEFAULT_QUALITY."""
    if re.search(r'"OggQuality", "%s"' % re.escape(OGG_DEFAULT_QUALITY), t):
        print("altacast_encoders: Ogg default quality already %s, skipped" % OGG_DEFAULT_QUALITY)
        return t
    t = sub_once(
        t,
        r'("OggQuality", )"0"',
        lambda m: m.group(1) + '"%s"' % OGG_DEFAULT_QUALITY,
        "libaltacast.cpp OggQuality default",
    )
    print("altacast_encoders: Ogg default quality 0 -> %s" % OGG_DEFAULT_QUALITY)
    return t


# ----------------------------------------------------------------------
# 3. Quality を encoder type ごとに記憶
# ----------------------------------------------------------------------

# The dialog has ONE Quality field for AAC (10..500) and for Ogg Vorbis / MP3 / FLAC (the
# 0..10 "OggQuality"). Both values are kept in the dialog, switched together with the
# encoder type, and both are saved with OK.
MARK_QMEM = "altacast_encoders: qmem"


QMEM_VALID_AAC = "atoi(LPCSTR(%s)) > 0"


QMEM_VALID_OGG = "!%(s)s.IsEmpty() && atof(LPCSTR(%(s)s)) >= 0 && atof(LPCSTR(%(s)s)) <= 10"


def fix_qmem_header(t):
    if MARK_QMEM in t:
        print("altacast_encoders: quality memory (header) already patched, skipped")
        return t
    return sub_once(
        t,
        r"([ \t]*CString[ \t]+m_Quality;\n)",
        lambda m: m.group(1)
        + "\tCString\tm_QualityAAC;\t// " + MARK_QMEM + ": Quality of the AAC type\n"
        + "\tCString\tm_QualityOgg;\t// Quality of Ogg Vorbis / MP3 / FLAC (0..10)\n",
        "BasicSettings.h m_Quality",
    )


QMEM_LOAD = (
    "    /* " + MARK_QMEM + ": both Quality values are known to the dialog */\n"
    "    basicSettings->m_QualityAAC = g->gAACQuality;\n"
    "    basicSettings->m_QualityOgg = g->gOggQuality;\n"
)


QMEM_SAVE = """    /* %(m)s: also store the Quality of the type that is not selected */
    if (g->gAACFlag || g->gAACPFlag) {
        if (%(ogg)s) {
            strcpy(g->gOggQuality, LPCSTR(basicSettings->m_QualityOgg));
        }
    }
    if (g->gLAMEFlag || g->gOggFlag || g->gFLACFlag || g->gAACPFlag) {
        if (%(aac)s) {
            strcpy(g->gAACQuality, LPCSTR(basicSettings->m_QualityAAC));
        }
    }
""" % {"m": MARK_QMEM,
       "ogg": QMEM_VALID_OGG % {"s": "basicSettings->m_QualityOgg"},
       "aac": QMEM_VALID_AAC % "basicSettings->m_QualityAAC"}


def fix_qmem_config(t):
    if MARK_QMEM in t:
        print("altacast_encoders: quality memory (Config.cpp) already patched, skipped")
        return t
    t = sub_once(
        t,
        r'([ \t]*currentEnc = g->encoderNumber;\n)(?=\s*sprintf\(buf, "%d", getCurrentBitrate\(g\)\);)',
        lambda m: m.group(1) + QMEM_LOAD,
        "Config.cpp currentEnc",
    )
    t = sub_once(
        t,
        r"([ \t]*if \(g->gOggFlag\) \{\n\s*strcpy\(g->gOggQuality, LPCSTR\(basicSettings->m_Quality\)\);\n\s*\}\n)",
        lambda m: m.group(1) + QMEM_SAVE,
        "Config.cpp gOggQuality save",
    )
    return t


QMEM_DIALOG = """m_QualityCtrl.EnableWindow(TRUE);
\t/* %(m)s: remember the Quality per encoder type. AAC has its own value,
\t * Ogg Vorbis / MP3 / FLAC share the Ogg one (0..10). */
\t{
\t\tCString\tleavingQuality;

\t\tm_QualityCtrl.GetWindowText(leavingQuality);
\t\tif (m_EncoderType == "AAC") {
\t\t\tm_QualityAAC = leavingQuality;
\t\t}
\t\telse if (m_EncoderType == "OggVorbis" || m_EncoderType == "MP3 Lame" || m_EncoderType == "Ogg FLAC") {
\t\t\tm_QualityOgg = leavingQuality;
\t\t}
\t}
\tm_EncoderType = selectedString;
\t{
\t\tCString\tenteringQuality;
\t\tbool\tsetQuality = false;

\t\tif (m_EncoderType == "AAC") {
\t\t\tenteringQuality = (%(aac)s) ? m_QualityAAC : CString(_T("%(aacdef)s"));
\t\t\tsetQuality = true;
\t\t}
\t\telse if (m_EncoderType == "OggVorbis" || m_EncoderType == "MP3 Lame" || m_EncoderType == "Ogg FLAC") {
\t\t\tenteringQuality = (%(ogg)s) ? m_QualityOgg : CString(_T("%(oggdef)s"));
\t\t\tsetQuality = true;
\t\t}
\t\tif (setQuality && m_QualityCtrl.GetSafeHwnd()) {
\t\t\tm_QualityCtrl.SetWindowText(enteringQuality);
\t\t\tm_Quality = enteringQuality;
\t\t}
\t}
\t"""


def fix_qmem_dialog(t):
    if MARK_QMEM in t:
        print("altacast_encoders: quality memory (dialog) already patched, skipped")
        return t
    block = QMEM_DIALOG % {
        "m": MARK_QMEM,
        "aac": QMEM_VALID_AAC % "m_QualityAAC",
        "aacdef": "100",
        "ogg": QMEM_VALID_OGG % {"s": "m_QualityOgg"},
        "oggdef": OGG_DEFAULT_QUALITY,
    }
    t = sub_once(
        t,
        r"m_QualityCtrl\.EnableWindow\(TRUE\);\n\s*m_EncoderType = selectedString;\n\s*",
        lambda m: block,
        "BasicSettings.cpp OnSelendokEncoderType",
    )
    print("altacast_encoders: Quality remembered per encoder type")
    return t


for _name, _blk in (("QMEM_LOAD", QMEM_LOAD), ("QMEM_SAVE", QMEM_SAVE), ("QMEM_DIALOG", QMEM_DIALOG)):
    if not _blk.isascii():
        fail("internal: inserted C++ (%s) must be ASCII" % _name)


# ----------------------------------------------------------------------
# 4. Ogg FLAC の拡張子
# ----------------------------------------------------------------------

def fix_flac_ext(t):
    if 'strcat(outputFile, ".flac")' in t:
        return t
    return sub_once(
        t,
        r'([ \t]*)if\(g->gAACPFlag\) \{\n[ \t]*strcat\(outputFile, "\.aac"\);\n[ \t]*\}\n',
        lambda m: m.group(0)
        + m.group(1) + "if(g->gFLACFlag) {\n"
        + m.group(1) + '\tstrcat(outputFile, ".flac");\t/* %s: Ogg FLAC archive extension */\n' % TAG
        + m.group(1) + "}\n",
        "libaltacast.cpp archive extension",
    )


# ----------------------------------------------------------------------
# 5. AAC Plus
# ----------------------------------------------------------------------

MARK_AACP = TAG + ": aacp"


def fix_aacp(t):
    if MARK_AACP in t:
        return t
    # ini file: full path, so it is written where we expect it
    t = sub_once(
        t,
        r'([ \t]*)char_t\s+\*conf_file = "altacast_aacp\.ini";[^\n]*\n',
        lambda m: (
            m.group(1) + "char_t\t\t\tconf_file_buf[MAX_PATH] = \"\";\t/* %s */\n" % MARK_AACP
            + m.group(1) + "char_t\t\t\t*conf_file = conf_file_buf;\n"
            + m.group(1) + "{\n"
            + m.group(1) + "\tchar_t *confFilePart = NULL;\n"
            + m.group(1) + "\tDWORD confLen = GetFullPathName(\"altacast_aacp.ini\", MAX_PATH, conf_file_buf, &confFilePart);\n"
            + m.group(1) + "\tif(confLen == 0 || confLen >= MAX_PATH) {\n"
            + m.group(1) + "\t\tstrcpy(conf_file_buf, \"altacast_aacp.ini\");\n"
            + m.group(1) + "\t}\n"
            + m.group(1) + "}\n"
        ),
        "libaltacast.cpp aacp ini path",
    )
    # channel mode: always set a value
    t = sub_once(
        t,
        r'([ \t]*)sprintf\(bitrateValue, "%d", bitrateLong\);\n',
        lambda m: m.group(0)
        + m.group(1) + 'strcpy(channelMode, (g->currentChannels == 2) ? "2" : "1");\t/* %s: default, no empty value */\n' % TAG,
        "libaltacast.cpp aacp channel mode default",
    )
    # extra keys
    t = sub_once(
        t,
        r'([ \t]*)WritePrivateProfileString\("audio_aacplus", "nsignallingmode", "0", conf_file\);\n',
        lambda m: m.group(0)
        + m.group(1) + 'WritePrivateProfileString("audio_aacplus", "signallingmode", "0", conf_file);\n'
        + m.group(1) + 'WritePrivateProfileString("audio_aacplus", "speech", "0", conf_file);\n'
        + m.group(1) + 'WritePrivateProfileString("audio_aacplus", "pns", "0", conf_file);\n',
        "libaltacast.cpp aacp extra keys",
    )
    # log the real reason
    t = sub_once(
        t,
        r'([ \t]*)LogMessage\(g,LOG_ERROR, "Invalid AAC\+ settings"\);\n',
        lambda m: (
            m.group(1) + "{\n"
            + m.group(1) + "\tchar_t aacpDiag[1024];\n"
            + m.group(1) + "\tsprintf(aacpDiag, \"Invalid AAC+ settings (channels=%d samplerate=%d bitrate=%ld channelmode=%s ini=%s)\",\n"
            + m.group(1) + "\t\t(int) g->currentChannels, (int) g->currentSamplerate, bitrateLong, channelMode, conf_file);\n"
            + m.group(1) + "\tLogMessage(g,LOG_ERROR, aacpDiag);\n"
            + m.group(1) + "}\n"
        ),
        "libaltacast.cpp aacp log",
    )
    # status line
    t = sub_once(
        t,
        r'(g->serverStatusCallback\(g, \(void \*\) "cannot find libfaac\.dll"\);\n[ \t]*\}\n[ \t]*else \{\n)([ \t]*)g->serverStatusCallback\(g, \(void \*\) "Encoder init failed"\);\n',
        lambda m: m.group(1)
        + m.group(2) + "if(g->gAACPFlag) {\n"
        + m.group(2) + '\tg->serverStatusCallback(g, (void *) "AAC Plus init failed (see log)");\n'
        + m.group(2) + "}\n"
        + m.group(2) + "else {\n"
        + m.group(2) + '\tg->serverStatusCallback(g, (void *) "Encoder init failed");\n'
        + m.group(2) + "}\n",
        "libaltacast.cpp init failed status",
    )
    return t


# ----------------------------------------------------------------------
# 6. 使えない種類の表示 (DLLなし)
# ----------------------------------------------------------------------

MARK_AVAIL = TAG + ": avail"


AVAIL_CODE = r'''/* @@M@@: encoder types whose DLL cannot be loaded stay in the list and are marked "(DLL...)".
 * Selecting one shows the reason (missing / not 32bit / missing dependency). */
#define ENC_NA_SUFFIX " (DLL\x82\xc8\x82\xb5)"
#define ENC_ALL_PLUGINS 0

static BOOL EncFileExists(const CString &path)
{
	return GetFileAttributes(path) != INVALID_FILE_ATTRIBUTES;
}

static DWORD EncRvaToOffset(IMAGE_NT_HEADERS32 *nt, DWORD rva)
{
	IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
	WORD i;

	for (i = 0; i < nt->FileHeader.NumberOfSections; i++) {
		DWORD size = sec[i].Misc.VirtualSize;
		if (sec[i].SizeOfRawData > size) size = sec[i].SizeOfRawData;
		if (rva >= sec[i].VirtualAddress && rva < sec[i].VirtualAddress + size) {
			return rva - sec[i].VirtualAddress + sec[i].PointerToRawData;
		}
	}
	return 0;
}

/* names of the DLLs that the given (32bit) DLL imports directly but that cannot be found */
static CString EncFindMissingImports(const CString &dllPath)
{
	CString missing;
	CString dllDir = dllPath;
	int slash = dllDir.ReverseFind('\\');
	HANDLE hf;
	DWORD size;
	DWORD got = 0;
	BYTE *buf = NULL;

	if (slash >= 0) dllDir = dllDir.Left(slash + 1);
	else dllDir = "";

	hf = CreateFile(dllPath, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
	if (hf == INVALID_HANDLE_VALUE) return missing;
	size = GetFileSize(hf, NULL);
	if (size != INVALID_FILE_SIZE && size > 1024 && size < 64 * 1024 * 1024) {
		buf = (BYTE *) malloc(size);
	}
	if (buf != NULL && ReadFile(hf, buf, size, &got, NULL) && got == size) {
		IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *) buf;
		if (dos->e_magic == IMAGE_DOS_SIGNATURE && dos->e_lfanew > 0 &&
			(DWORD) dos->e_lfanew + sizeof(IMAGE_NT_HEADERS32) < size) {
			IMAGE_NT_HEADERS32 *nt = (IMAGE_NT_HEADERS32 *) (buf + dos->e_lfanew);
			if (nt->Signature == IMAGE_NT_SIGNATURE && nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR32_MAGIC &&
				(size_t) ((BYTE *) (IMAGE_FIRST_SECTION(nt) + nt->FileHeader.NumberOfSections) - buf) <= size) {
				DWORD impRva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
				DWORD impOff = (impRva != 0) ? EncRvaToOffset(nt, impRva) : 0;
				int guard = 0;
				while (impOff != 0 && impOff + sizeof(IMAGE_IMPORT_DESCRIPTOR) <= size && guard++ < 512) {
					IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *) (buf + impOff);
					DWORD nameOff;
					if (d->Name == 0) break;
					nameOff = EncRvaToOffset(nt, d->Name);
					if (nameOff != 0 && nameOff < size) {
						const char *name = (const char *) (buf + nameOff);
						DWORD len = 0;
						while (nameOff + len < size && name[len] != 0 && len < 260) len++;
						if (nameOff + len < size && name[len] == 0 && len > 0 &&
							_strnicmp(name, "api-ms-", 7) != 0 && _strnicmp(name, "ext-ms-", 7) != 0) {
							char found[MAX_PATH];
							char *filePart = NULL;
							CString own = dllDir + name;
							if (SearchPathA(NULL, name, NULL, MAX_PATH, found, &filePart) == 0 && !EncFileExists(own)) {
								if (!missing.IsEmpty()) missing += ", ";
								missing += name;
							}
						}
					}
					impOff += sizeof(IMAGE_IMPORT_DESCRIPTOR);
				}
			}
		}
	}
	if (buf != NULL) free(buf);
	CloseHandle(hf);
	return missing;
}

/* Two passes: pass 0 adds the usable encoders, pass 1 adds the unusable ones below them. */
void CBasicSettings::AddEncoderItem(const char *label, const char *dll, BOOL plugins, BOOL unavailablePass)
{
	HINSTANCE h = LoadLibrary(dll);

	if (h == NULL && plugins) {
		CString p;
		p.Format("plugins\\%s", dll);
		h = LoadLibrary(p);
	}
	if (h != NULL) {
		FreeLibrary(h);
		if (!unavailablePass) m_EncoderTypeCtrl.AddString(label);
	}
	else if (unavailablePass) {
		CString s = label;
		s += ENC_NA_SUFFIX;
		m_EncoderTypeCtrl.AddString(s);
	}
}

/* select by exact name (also the "(DLL...)" variant); SelectString would match prefixes ("AAC" / "AAC Plus") */
void CBasicSettings::SelectEncoderItem(const CString &name)
{
	int idx = m_EncoderTypeCtrl.FindStringExact(-1, name);

	if (idx == CB_ERR) {
		CString s = name;
		s += ENC_NA_SUFFIX;
		idx = m_EncoderTypeCtrl.FindStringExact(-1, s);
	}
	if (idx != CB_ERR) m_EncoderTypeCtrl.SetCurSel(idx);
}

void CBasicSettings::ShowEncoderUnavailable(const CString &selected)
{
	CString type = selected;
	int cut = type.Find(" (");
	const char *dll = "";
	BOOL plugins = (ENC_ALL_PLUGINS != 0);
	char exe[MAX_PATH] = "";
	char cwd[MAX_PATH] = "";
	CString exeDir;
	CString cwdDir;
	CString cand[4];
	CString found;
	int n = 0;
	int i;
	int sl;
	wchar_t msg[2048];
	wchar_t body[1900];

	if (cut > 0) type = type.Left(cut);
	if (type == "MP3 Lame") dll = "lame_enc.dll";
	else if (type == "AAC") dll = "libfaac.dll";
	else if (type == "AAC Plus" || type == "HE-AAC" || type == "HE-AAC High" || type == "LC-AAC") {
		dll = "enc_aacplus.dll";
		plugins = TRUE;
	}
	else if (type.Left(6) == "FHGAAC") {
		dll = "enc_fhgaac.dll";
		plugins = TRUE;
	}
	if (dll[0] == 0) return;

	GetModuleFileNameA(NULL, exe, MAX_PATH);
	exeDir = exe;
	sl = exeDir.ReverseFind('\\');
	if (sl >= 0) exeDir = exeDir.Left(sl + 1);
	else exeDir = "";
	GetCurrentDirectoryA(MAX_PATH, cwd);
	cwdDir = cwd;
	if (!cwdDir.IsEmpty() && cwdDir.Right(1) != "\\") cwdDir += "\\";

	cand[n++] = exeDir + dll;
	if (plugins) cand[n++] = exeDir + "plugins\\" + dll;
	cand[n++] = cwdDir + dll;
	if (plugins) cand[n++] = cwdDir + "plugins\\" + dll;
	for (i = 0; i < n; i++) {
		if (EncFileExists(cand[i])) {
			found = cand[i];
			break;
		}
	}

	if (found.IsEmpty()) {
		_snwprintf(body, 1899, L"\u7406\u7531: %S \u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3002\n\n\u5b9f\u884c\u30d5\u30a1\u30a4\u30eb(exe)\u3068\u540c\u3058\u30d5\u30a9\u30eb\u30c0%s\u306b\u7f6e\u3044\u3066\u304f\u3060\u3055\u3044\u3002", dll, plugins ? L"\u3001\u307e\u305f\u306f plugins \u30d5\u30a9\u30eb\u30c0" : L"");
	}
	else {
		HMODULE h = LoadLibraryExA(found, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
		if (h != NULL) {
			FreeLibrary(h);
			_snwprintf(body, 1899, L"%S \u306f\u8aad\u307f\u8fbc\u3081\u307e\u3057\u305f\u3002\u8a2d\u5b9a\u753b\u9762\u3092\u958b\u304d\u76f4\u3059\u3068\u9078\u3079\u308b\u3088\u3046\u306b\u306a\u308a\u307e\u3059\u3002", dll);
		}
		else {
			DWORD err = GetLastError();
			if (err == ERROR_BAD_EXE_FORMAT) {
				_snwprintf(body, 1899, L"\u7406\u7531: %S \u306f\u898b\u3064\u304b\u308a\u307e\u3057\u305f\u304c\u300132bit\u7248\u3067\u306f\u306a\u3044\u305f\u3081\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093(\u30a8\u30e9\u30fc193)\u3002\n\n\u3053\u306e\u30a2\u30d7\u30ea\u306f32bit\u7248\u306a\u306e\u3067\u300132bit\u7248\u306e %S \u304c\u5fc5\u8981\u3067\u3059\u3002\n\n\u5834\u6240: %s", dll, dll, (LPCWSTR) CStringW(found));
			}
			else if (err == ERROR_MOD_NOT_FOUND) {
				CString missing = EncFindMissingImports(found);
				if (missing.IsEmpty()) {
					_snwprintf(body, 1899, L"\u7406\u7531: %S \u306f\u898b\u3064\u304b\u308a\u307e\u3057\u305f\u304c\u3001\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093(\u30a8\u30e9\u30fc126)\u3002\n\n\u3053\u306eDLL\u304c\u5fc5\u8981\u3068\u3059\u308b\u5225\u306eDLL\u304c\u8db3\u308a\u306a\u3044\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002\n\n\u8db3\u308a\u306a\u3044DLL: %s\n\n\u5834\u6240: %s", dll, L"(\u7279\u5b9a\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002VC\u30e9\u30f3\u30bf\u30a4\u30e0\u306a\u3069\u304c\u8db3\u308a\u306a\u3044\u5834\u5408\u304c\u3042\u308a\u307e\u3059)", (LPCWSTR) CStringW(found));
				}
				else {
					_snwprintf(body, 1899, L"\u7406\u7531: %S \u306f\u898b\u3064\u304b\u308a\u307e\u3057\u305f\u304c\u3001\u8aad\u307f\u8fbc\u3081\u307e\u305b\u3093(\u30a8\u30e9\u30fc126)\u3002\n\n\u3053\u306eDLL\u304c\u5fc5\u8981\u3068\u3059\u308b\u5225\u306eDLL\u304c\u8db3\u308a\u306a\u3044\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002\n\n\u8db3\u308a\u306a\u3044DLL: %s\n\n\u5834\u6240: %s", dll, (LPCWSTR) CStringW((LPCSTR) missing), (LPCWSTR) CStringW(found));
				}
			}
			else {
				_snwprintf(body, 1899, L"\u7406\u7531: %S \u306e\u8aad\u307f\u8fbc\u307f\u306b\u5931\u6557\u3057\u307e\u3057\u305f(\u30a8\u30e9\u30fc%lu)\u3002\n\n\u5834\u6240: %s", dll, (unsigned long) err, (LPCWSTR) CStringW(found));
			}
		}
	}
	body[1899] = 0;
	_snwprintf(msg, 2047, L"\u300c%S\u300d\u306f\u4f7f\u3048\u307e\u305b\u3093\u3002\n\n%s", (LPCSTR) type, body);
	msg[2047] = 0;
	MessageBoxW(m_hWnd, msg, L"\u30a8\u30f3\u30b3\u30fc\u30c0\u30fc\u3092\u9078\u3079\u307e\u305b\u3093", MB_OK | MB_ICONINFORMATION);
}

'''


INIT_PAT = r"hDLL = LoadLibrary\(_T\(\"lame_enc\.dll\"\)\);.*?(?=\s*return TRUE;)"


INIT_REPL = '{\n\tint encPass;\n\tfor (encPass = 0; encPass < 2; encPass++) {\n\tAddEncoderItem("MP3 Lame", "lame_enc.dll", FALSE, encPass != 0);   /* @@M@@ */\n\t\tAddEncoderItem("AAC", "libfaac.dll", FALSE, encPass != 0);\n\t\tAddEncoderItem("AAC Plus", "enc_aacplus.dll", TRUE, encPass != 0);\n\t}\n}'


C_OPEN = "/*"


C_CLOSE = "*/"


def fix_avail_header(t):
    if MARK_AVAIL in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)void UpdateFields\s*\(\);\n",
        lambda m: m.group(0)
        + m.group(1) + "void AddEncoderItem(const char *label, const char *dll, BOOL plugins, BOOL unavailablePass);   " + C_OPEN + " " + MARK_AVAIL + " " + C_CLOSE + "\n"
        + m.group(1) + "void SelectEncoderItem(const CString &name);\n"
        + m.group(1) + "void ShowEncoderUnavailable(const CString &selected);\n",
        "BasicSettings.h avail declarations",
    )


def fix_avail_cpp(t):
    if MARK_AVAIL in t:
        return t
    # 1. helper code before OnInitDialog
    t = sub_once(
        t,
        r"BOOL CBasicSettings::OnInitDialog\s*\(\)",
        lambda m: AVAIL_CODE.replace("@@M@@", MARK_AVAIL) + m.group(0),
        "BasicSettings.cpp OnInitDialog (helpers)",
    )
    # 2. the list is built without DLL checks
    t = sub_once(t, INIT_PAT, lambda m: INIT_REPL.replace("@@M@@", MARK_AVAIL), "BasicSettings.cpp encoder list", flags=re.S)
    # 3. selecting an unavailable type: explain and go back
    t = sub_once(
        t,
        r"(void CBasicSettings::OnSelendokEncoderType\s*\(\)\s*\{\n)",
        lambda m: m.group(1)
        + "\t" + C_OPEN + " " + MARK_AVAIL + " " + C_CLOSE + "\n"
        + "\t{\n"
        + "\t\tCString selStr;\n"
        + "\t\tint selIdx = m_EncoderTypeCtrl.GetCurSel();\n"
        + "\t\tif (selIdx >= 0) {\n"
        + "\t\t\tm_EncoderTypeCtrl.GetLBText(selIdx, selStr);\n"
        + "\t\t\tif (selStr.Find(\" (\") > 0) {\n"
        + "\t\t\t\tShowEncoderUnavailable(selStr);\n"
        + "\t\t\t\tSelectEncoderItem(m_EncoderType);\n"
        + "\t\t\t\treturn;\n"
        + "\t\t\t}\n"
        + "\t\t}\n"
        + "\t}\n",
        "BasicSettings.cpp OnSelendokEncoderType",
    )
    # 4. the "(DLL...)" mark never reaches the settings
    t = sub_once(
        t,
        r"([ \t]*)//\}\}AFX_DATA_MAP\n",
        lambda m: m.group(0)
        + m.group(1) + "if (pDX->m_bSaveAndValidate) {\t" + C_OPEN + " " + MARK_AVAIL + ": drop the (DLL..) mark " + C_CLOSE + "\n"
        + m.group(1) + "\tint markPos = m_EncoderType.Find(\" (\");\n"
        + m.group(1) + "\tif (markPos > 0) m_EncoderType = m_EncoderType.Left(markPos);\n"
        + m.group(1) + "}\n",
        "BasicSettings.cpp DoDataExchange",
    )
    return t


def fix_avail_config(t):
    if "SelectEncoderItem" in t:
        return t
    t = sub_once(
        t,
        r"basicSettings->m_EncoderTypeCtrl\.SelectString\(\s*0,\s*basicSettings->m_EncoderType\s*\);",
        "basicSettings->SelectEncoderItem( basicSettings->m_EncoderType );   " + C_OPEN + " " + MARK_AVAIL + " " + C_CLOSE,
        "Config.cpp encoder selection",
    )
    # DDX_CBString may match by prefix ("AAC" -> "AAC Plus"): select the exact item again
    return sub_once(
        t,
        r"([ \t]*)basicSettings->UpdateData\(FALSE\);\n",
        lambda m: m.group(0) + m.group(1) + "basicSettings->SelectEncoderItem( basicSettings->m_EncoderType );\n",
        "Config.cpp basicSettings UpdateData",
    )


# ----------------------------------------------------------------------
# 7. ドロップダウン
# ----------------------------------------------------------------------

MARK_UI = TAG + ": ui"


def fix_unsorted_rc(t):
    if "IDC_ENCODER_TYPE" not in t:
        fail("rc: IDC_ENCODER_TYPE not found")
    t2, n = re.subn(r"(COMBOBOX\s+IDC_ENCODER_TYPE,[^\n]*?)CBS_SORT \| ", r"\1", t)
    if n > 1:
        fail("rc: CBS_SORT matched %d times" % n)
    return t2


def fix_dropdown_width(t):
    if MARK_UI in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)return TRUE;([ \t]*)// return TRUE unless you set the focus to a control",
        lambda m: (
            m.group(1) + "m_QualityCtrl.LimitText(24);\t/* " + MARK_UI + ": gOggQuality / gAACQuality are char[25] */\n"
            + m.group(1) + "{\t/* " + MARK_UI + ": widen the drop-down list so the (DLL...) mark is not cut off */\n"
            + m.group(1) + "\tCDC *encDC = m_EncoderTypeCtrl.GetDC();\n"
            + m.group(1) + "\tif (encDC != NULL) {\n"
            + m.group(1) + "\t\tCFont *encOldFont = encDC->SelectObject(m_EncoderTypeCtrl.GetFont());\n"
            + m.group(1) + "\t\tint encMaxW = 0;\n"
            + m.group(1) + "\t\tint encI;\n"
            + m.group(1) + "\t\tfor (encI = 0; encI < m_EncoderTypeCtrl.GetCount(); encI++) {\n"
            + m.group(1) + "\t\t\tCString encItem;\n"
            + m.group(1) + "\t\t\tm_EncoderTypeCtrl.GetLBText(encI, encItem);\n"
            + m.group(1) + "\t\t\tint encW = encDC->GetTextExtent(encItem).cx;\n"
            + m.group(1) + "\t\t\tif (encW > encMaxW) encMaxW = encW;\n"
            + m.group(1) + "\t\t}\n"
            + m.group(1) + "\t\tencDC->SelectObject(encOldFont);\n"
            + m.group(1) + "\t\tm_EncoderTypeCtrl.ReleaseDC(encDC);\n"
            + m.group(1) + "\t\tm_EncoderTypeCtrl.SetDroppedWidth(encMaxW + GetSystemMetrics(SM_CXVSCROLL) + 12);\n"
            + m.group(1) + "\t}\n"
            + m.group(1) + "}\n"
        ) + m.group(0),
        "BasicSettings.cpp OnInitDialog end",
    )


def fix_selendok_refresh(t):
    mark = TAG + ": refresh"
    if mark in t:
        return t
    # take over what was typed first: UpdateData(FALSE) below writes every member back
    t = sub_once(
        t,
        r"([ \t]*)//UpdateData\(TRUE\);\n",
        lambda m: (
            m.group(1) + "{\t" + C_OPEN + " " + mark + ": keep what was typed in the other fields " + C_CLOSE + "\n"
            + m.group(1) + "\tCString prevType = m_EncoderType;\n"
            + m.group(1) + "\tUpdateData(TRUE);\n"
            + m.group(1) + "\tm_EncoderType = prevType;\n"
            + m.group(1) + "}\n"
        ),
        "BasicSettings.cpp OnSelendokEncoderType start",
    )
    return sub_once(
        t,
        r"(void CBasicSettings::OnSelendokEncoderType\s*\(\)\s*\{(?:(?!\nvoid CBasicSettings::).)*?)(\n[ \t]*)UpdateFields\(\);([ \t]*\n\s*\})",
        lambda m: m.group(1) + m.group(2) + "UpdateFields();" + m.group(2)
        + "UpdateData( FALSE );   " + C_OPEN + " " + mark + ": show the values UpdateFields() corrected (bitrate / channels) " + C_CLOSE
        + m.group(3),
        "BasicSettings.cpp OnSelendokEncoderType end",
        flags=re.S,
    )


# ----------------------------------------------------------------------
# apply
# ----------------------------------------------------------------------

patch_file("Config.cpp", lambda t: fix_avail_config(fix_qmem_config(t)))
patch_file("BasicSettings.h", lambda t: fix_avail_header(fix_qmem_header(t)))
patch_file("BasicSettings.cpp", lambda t: fix_dropdown_width(fix_selendok_refresh(fix_avail_cpp(fix_qmem_dialog(fix_ogg_ui(fix_aac_ui(t)))))))
patch_file("libaltacast/libaltacast.cpp", lambda t: fix_aacp(fix_flac_ext(fix_ogg_default(fix_aac_quality(t)))))
patch_file("altacast.rc", fix_unsorted_rc)
print(TAG + ": done")
