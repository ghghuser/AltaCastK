#!/usr/bin/env python3
"""
02_stability.py - 安定性の修正 (AltaCast)

  [録音・保存]
    1. fflush         書き込みごとにフラッシュ (クラッシュしても直前まで残る)
    2. パスワード     URLize が元の文字列を壊す問題 (コピーをエンコードする方式に)
                      送信用 / 曲名用 / パスワード用のバッファも拡大
    3. 録音復旧       デバイスが失われたら 3秒おき・最大20回まで再オープン
                      約4GB に達する前に録音を自動再起動 (3時間バグ対策)
  [接続中のクラッシュ防止]
    4. 接続中ロック   接続中は Encoder Type / Bitrate / Quality / Samplerate /
                      Channels をグレーアウト (変更するとクラッシュした)
    5. 多重起動警告   同じフォルダ (= 同じ .cfg) のインスタンスが起動中なら確認
  [設定ファイル]
    6. バックアップ   変更前を .bak1 / .bak2 (2世代) に残す。一度 .new に書いてから置き換え

使い方:  python tools/02_stability.py trunk/AltaCast/src
冪等 (何度当てても同じ)。アンカーが見つからなければエラーで停止。
"""

import re
import sys
from pathlib import Path

import patchlib as P

TAG = "altacast_stability"
P.init(TAG)
SRC = P.SRC
from patchlib import fail, sub_once, sub_n, after, patch_file, c_wide  # noqa: E402,F401


# ----------------------------------------------------------------------
# 設定値 (録音復旧の間隔と回数、長時間録音の再起動)
# ----------------------------------------------------------------------

RETRY_INTERVAL_MS = 3000        # wait between two attempts to re-open the device


MAX_TRIES = 20                  # attempts in a row before giving up (20 x 3 s = about 1 minute)


ENABLE_LONG_RUN_RESTART = True  # restart recording before the 4 GB limit ("3 hour bug")


LONG_RUN_LIMIT_BYTES = "0xFF000000UL"   # same threshold as ShuiCast


# ----------------------------------------------------------------------
# 1. fflush
# ----------------------------------------------------------------------

def fix_fflush(t):
    if re.search(r"fwrite\(data, length, 1, g->gSaveFile\);\s*fflush\(g->gSaveFile\);", t):
        print("altacast_stability: fflush already present, skipped")
        return t
    t = sub_once(
        t,
        r"([ \t]*)fwrite\(data, length, 1, g->gSaveFile\);\n",
        lambda m: m.group(0)
        + m.group(1)
        + "fflush(g->gSaveFile);\t/* altacast_stability: keep the archive file current */\n",
        "libaltacast.cpp archive fwrite",
    )
    print("altacast_stability: fflush added")
    return t


# ----------------------------------------------------------------------
# 2. パスワード・曲名バッファ
# ----------------------------------------------------------------------

PW_BLOCK = """{i}/*
{i} * altacast_stability: URLize() works in place. Encode a copy, otherwise g->gPassword
{i} * itself is overwritten with its URL-encoded form.
{i} */
{i}{{
{i}	char_t	pwCopy[1024] = "";

{i}	strncpy(pwCopy, g->gPassword, sizeof(pwCopy) - 1);
{i}	memset(URLPassword, '\\000', sizeof(URLPassword));
{i}	URLize(pwCopy, URLPassword, sizeof(pwCopy), sizeof(URLPassword));
{i}}}
"""


SONG_BLOCK = """{i}/*
{i} * altacast_stability: same for the song title. Encoding can make it 3 times longer, so
{i} * work on a 4096 byte copy (the title itself is at most 1023 bytes).
{i} */
{i}{{
{i}	char_t	songCopy[4096] = "";

{i}	strncpy(songCopy, g->gCurrentSong, sizeof(songCopy) - 1);
{i}	memset(URLSong, '\\000', sizeof(URLSong));
{i}	URLize(songCopy, URLSong, sizeof(songCopy), sizeof(URLSong));
{i}}}
"""


def fix_password(t):
    if "altacast_stability: URLize() works in place" in t:
        print("altacast_stability: password/song fix already present, skipped")
        return t
    marker = "int updateSongTitle(altacastGlobals *g, int forceURL) {"
    pos = t.find(marker)
    if pos < 0:
        fail("libaltacast.cpp: updateSongTitle() not found")
    head, tail = t[:pos], t[pos:]
    tail = sub_once(
        tail,
        r"([ \t]*)URLize\(g->gPassword, URLPassword, sizeof\(g->gPassword\), sizeof\(URLPassword\)\);\n",
        lambda m: PW_BLOCK.format(i=m.group(1)),
        "libaltacast.cpp URLize(g->gPassword ...)",
    )
    tail = sub_once(
        tail,
        r"([ \t]*)URLize\(g->gCurrentSong, URLSong, sizeof\(g->gSongTitle\), sizeof\(URLSong\)\);\n",
        lambda m: SONG_BLOCK.format(i=m.group(1)),
        "libaltacast.cpp URLize(g->gCurrentSong ...)",
    )
    tail = sub_once(
        tail, r"URLPassword\[255\]", "URLPassword[1024]", "libaltacast.cpp URLPassword size"
    )
    tail = sub_once(
        tail, r"URLSong\[1024\]", "URLSong[4096]", "libaltacast.cpp URLSong size"
    )
    tail = sub_once(
        tail, r"contentString\[2056\]", "contentString[16384]", "libaltacast.cpp contentString size"
    )
    print("altacast_stability: password/song fix added (buffers: request 16384, song 4096)")
    return head + tail


# ----------------------------------------------------------------------
# 3. 録音復旧 / 長時間録音の再起動
# ----------------------------------------------------------------------

LONG_RUN_RESTART_CODE = """
#ifdef ALTACAST_LONG_RUN_RESTART
			if(altacastRecRestart) {
				generalStatusCallback((void *) "Restarting recording (long-run workaround for the 4 GB limit)");
				stopRecording();
				startRecording(m_CurrentInputCard);
			}
#endif"""


REC_BLOCK = """#ifdef ALTACASTSTANDALONE
	/*
	 * altacast_stability: recording device recovery.
	 * When the recording device is lost the BASS record channel stops. Re-open it, but
	 * only every ALTACAST_REC_RETRY_MS and at most ALTACAST_REC_MAX_TRIES times in a
	 * row, so a device that stays away does not cause a flood of init attempts and
	 * status messages. The counter is re-armed as soon as recording works again.
	 * Also restarts the recording before the 4 GB limit (see BASSwaveInputProc).
	 */
#define ALTACAST_REC_RETRY_MS	%(retry)d
#define ALTACAST_REC_MAX_TRIES	%(tries)d
	if(nIDEvent == 73) {
		static int		recTries = 0;
		static DWORD	recLastTry = 0;

		if(BASS_ChannelIsActive(inRecHandle) != BASS_ACTIVE_STOPPED) {
			recTries = 0;%(longrun)s
		}
		else if(recTries < ALTACAST_REC_MAX_TRIES &&
				(recTries == 0 || GetTickCount() - recLastTry >= ALTACAST_REC_RETRY_MS)) {
			recTries++;
			recLastTry = GetTickCount();
			stopRecording();
			startRecording(m_CurrentInputCard);

			if(recTries >= ALTACAST_REC_MAX_TRIES && BASS_ChannelIsActive(inRecHandle) == BASS_ACTIVE_STOPPED) {
				generalStatusCallback((void *) "Recording device lost - gave up retrying. Select the device again to resume.");
			}
		}
	}
#undef ALTACAST_REC_RETRY_MS
#undef ALTACAST_REC_MAX_TRIES
#endif

""" % {
    "retry": RETRY_INTERVAL_MS,
    "tries": MAX_TRIES,
    "longrun": (LONG_RUN_RESTART_CODE if ENABLE_LONG_RUN_RESTART else ""),
}


COUNTER_DECL = """/*
 * altacast_stability: long-run restart. Counts the recorded bytes; the timer restarts the
 * recording before BASS reaches 4 GB (the "3 hour bug").
 */
#define ALTACAST_LONG_RUN_RESTART
static DWORD			altacastRecBytes = 0;
static volatile LONG	altacastRecRestart = 0;

"""


COUNTER_CODE = """	altacastRecBytes += length;	/* altacast_stability: long-run restart */
	if(altacastRecBytes > %s) {
		altacastRecRestart = 1;
	}

""" % LONG_RUN_LIMIT_BYTES


COUNTER_RESET = "\taltacastRecBytes = 0;\t/* altacast_stability: long-run restart */\n\taltacastRecRestart = 0;\n"


def fix_recording(t):
    if "altacast_stability: recording device recovery" in t:
        print("altacast_stability: recording recovery already present, skipped")
        return t
    if re.search(r"if\s*\(\s*!\s*BASS_ChannelIsActive\(\s*inRecHandle\s*\)\s*\)", t):
        fail("MainWindow.cpp already contains an unconditional BASS_ChannelIsActive() restart "
             "(ImagoTrigger fork?). Remove it first, otherwise the retry limit is bypassed.")
    t = sub_once(
        t,
        r"(void CMainWindow::OnTimer\(UINT nIDEvent\)\s*\{\n)(\n?)",
        lambda m: m.group(1) + REC_BLOCK,
        "MainWindow.cpp OnTimer",
    )
    if ENABLE_LONG_RUN_RESTART:
        t = sub_once(
            t,
            r"(BOOL CALLBACK BASSwaveInputProc\(HRECORD handle, const void \*buffer, DWORD length, void \*user\) \{\n)",
            lambda m: COUNTER_DECL + m.group(1) + COUNTER_CODE,
            "MainWindow.cpp BASSwaveInputProc",
        )
        t = sub_once(
            t,
            r"([ \t]*inRecHandle = BASS_RecordStart\(44100, 2, 0, &BASSwaveInputProc, NULL\);\n)",
            lambda m: m.group(1) + COUNTER_RESET,
            "MainWindow.cpp BASS_RecordStart",
        )
    print("altacast_stability: recording recovery added (retry every %d ms, max %d tries)"
          % (RETRY_INTERVAL_MS, MAX_TRIES))
    if ENABLE_LONG_RUN_RESTART:
        print("altacast_stability: long-run restart added (limit %s bytes)" % LONG_RUN_LIMIT_BYTES)
    return t


for _name, _blk in (("REC_BLOCK", REC_BLOCK), ("PW_BLOCK", PW_BLOCK), ("SONG_BLOCK", SONG_BLOCK),
                    ("COUNTER_DECL", COUNTER_DECL), ("COUNTER_CODE", COUNTER_CODE)):
    if not _blk.isascii():
        fail("internal: inserted C++ (%s) must be ASCII" % _name)


# ----------------------------------------------------------------------
# 4. 接続中ロック
# ----------------------------------------------------------------------

MARK_LOCK = TAG + ": lock"


def fix_lock_header(t):
    if MARK_LOCK in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)void UpdateFields\(\);\n",
        lambda m: m.group(0)
        + m.group(1) + "void UpdateFieldsCore();   /* %s */\n" % MARK_LOCK
        + m.group(1) + "void ApplyEncoderLock();\n"
        + m.group(1) + "BOOL m_LockEncoder = FALSE;   /* TRUE while the encoder is connected */\n",
        "BasicSettings.h UpdateFields declaration",
    )


LOCK_CODE = """void CBasicSettings::UpdateFields() {
	UpdateFieldsCore();
	ApplyEncoderLock();
}

/* %(m)s: while connected, the fields that change the running encoder are greyed out */
void CBasicSettings::ApplyEncoderLock() {
	CWnd *w;

	if (!m_LockEncoder) {
		m_EncoderTypeCtrl.EnableWindow(TRUE);
		w = GetDlgItem(IDC_SAMPLERATE);
		if (w != NULL) w->EnableWindow(TRUE);
		w = GetDlgItem(IDC_CHANNELS);
		if (w != NULL) w->EnableWindow(TRUE);
		return;
	}
	m_EncoderTypeCtrl.EnableWindow(FALSE);
	m_BitrateCtrl.EnableWindow(FALSE);
	m_QualityCtrl.EnableWindow(FALSE);
	m_UseBitrateCtrl.EnableWindow(FALSE);
	w = GetDlgItem(IDC_SAMPLERATE);
	if (w != NULL) w->EnableWindow(FALSE);
	w = GetDlgItem(IDC_CHANNELS);
	if (w != NULL) w->EnableWindow(FALSE);
}

void CBasicSettings::UpdateFieldsCore() {"""


def fix_lock_cpp(t):
    if MARK_LOCK in t:
        return t
    return sub_once(
        t,
        r"void CBasicSettings::UpdateFields\(\) \{",
        lambda m: LOCK_CODE % {"m": MARK_LOCK},
        "BasicSettings.cpp UpdateFields",
    )


def fix_lock_config(t):
    if MARK_LOCK in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)basicSettings->UpdateFields\(\);\n",
        lambda m: m.group(1)
        + "basicSettings->m_LockEncoder = (g->weareconnected != 0);   /* %s */\n" % MARK_LOCK
        + m.group(0),
        "Config.cpp GlobalsToDialog UpdateFields",
    )


# ----------------------------------------------------------------------
# 5. 多重起動警告
# ----------------------------------------------------------------------

MARK_INST = TAG + ": instance"


INST_TITLE = "多重起動の確認"


INST_MSG = (
    "同じフォルダ(設定ファイルの場所)を使うインスタンスが、すでに起動しています。\n\n"
    "設定ファイル(.cfg)を互いに上書きし合い、設定が壊れたり、"
    "意図しない内容で保存されたりするおそれがあります。\n\n"
    "それでも起動しますか?\n\n"
    "(別々に使いたい場合は、アプリのフォルダごとコピーして、別のフォルダから起動してください。)"
)


def instance_block(indent, dir_expr, prefix):
    lines = [
        "/* %s: warn when another instance uses the same folder (= the same .cfg files) */" % MARK_INST,
        "{",
        "\tchar instDir[MAX_PATH] = \"\";",
        "\tchar *instFilePart = NULL;",
        "\tchar instMutexName[MAX_PATH + 64];",
        "\tif (GetFullPathNameA(%s, MAX_PATH, instDir, &instFilePart) == 0) {" % dir_expr,
        "\t\tstrcpy(instDir, \".\");",
        "\t}",
        "\tfor (char *ip = instDir; *ip; ++ip) {",
        "\t\tif (*ip == '\\\\' || *ip == ':') *ip = '/';",
        "\t\telse if (*ip >= 'A' && *ip <= 'Z') *ip = (char)(*ip - 'A' + 'a');",
        "\t}",
        "\tsprintf(instMutexName, \"Local\\\\%s_inst_%%s\", instDir);" % prefix,
        "\tHANDLE instMutex = CreateMutexA(NULL, FALSE, instMutexName);",
        "\tif (instMutex != NULL && GetLastError() == ERROR_ALREADY_EXISTS) {",
        "\t\tif (MessageBoxW(NULL, L\"%s\", L\"%s\", MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) != IDYES) {"
        % (c_wide(INST_MSG), c_wide(INST_TITLE)),
        "\t\t\treturn FALSE;",
        "\t\t}",
        "\t}",
        "}",
    ]
    return "".join(indent + ln + "\n" for ln in lines)


def fix_instance(t):
    if MARK_INST in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)LoadConfigs\(currentDir, \"altacaststandalone\"\);\n",
        lambda m: instance_block(m.group(1), "currentDir", "altacast") + "\n" + m.group(0),
        "altacastStandalone.cpp LoadConfigs",
    )


# ----------------------------------------------------------------------
# 6. 設定ファイルのバックアップ
# ----------------------------------------------------------------------

MARK_BAK = TAG + ": backup"


BACKUP_FUNC = """/*
 * %s: config file backups.
 * The new config is written to <file>.new first. When it differs from the current file, the
 * current file is kept as <file>.bak1 (the old .bak1 becomes .bak2). This is done once per
 * run and file, so many saves in one run do not push out the older backups.
 * Replacing the file from the finished .new file also protects against a half-written config.
 */
static void CommitConfigFile(const char *configFile, const char *tmpFile) {
	static char	backedUp[32][1100];
	static int	numBackedUp = 0;
	FILE		*fa = fopen(configFile, "rb");
	FILE		*fb = fopen(tmpFile, "rb");
	int			existed = (fa != NULL);
	int			same = 0;
	int			i;

	if (fa != NULL && fb != NULL) {
		same = 1;
		for (;;) {
			int ca = fgetc(fa);
			int cb = fgetc(fb);

			if (ca != cb) {
				same = 0;
				break;
			}
			if (ca == EOF) {
				break;
			}
		}
	}
	if (fa != NULL) {
		fclose(fa);
	}
	if (fb != NULL) {
		fclose(fb);
	}
	if (same) {
		remove(tmpFile);
		return;
	}
	if (existed) {
		int already = 0;

		for (i = 0; i < numBackedUp; i++) {
			if (!strcmp(backedUp[i], configFile)) {
				already = 1;
			}
		}
		if (!already && numBackedUp < 32) {
			char bak1[1100];
			char bak2[1100];

			strcpy(backedUp[numBackedUp++], configFile);
			sprintf(bak1, "%%s.bak1", configFile);
			sprintf(bak2, "%%s.bak2", configFile);
			CopyFileA(bak1, bak2, FALSE);
			CopyFileA(configFile, bak1, FALSE);
		}
	}
	if (!MoveFileExA(tmpFile, configFile, MOVEFILE_REPLACE_EXISTING | MOVEFILE_COPY_ALLOWED)) {
		CopyFileA(tmpFile, configFile, FALSE);
		remove(tmpFile);
	}
}

"""


def fix_backup(t):
    if MARK_BAK in t:
        return t
    t = sub_once(
        t,
        r"int writeConfigFile\(altacastGlobals \*g\) \{\n",
        lambda m: (BACKUP_FUNC % MARK_BAK) + m.group(0),
        "libaltacast.cpp writeConfigFile",
    )
    t = sub_once(
        t,
        r'([ \t]*)FILE\t\*filep = fopen\(configFile, "w"\);\n',
        lambda m: (
            m.group(1) + "char_t\ttmpFile[1100] = \"\";\n"
            + m.group(1) + "sprintf(tmpFile, \"%s.new\", configFile);\n"
            + m.group(1) + "FILE\t*filep = fopen(tmpFile, \"w\");\n"
        ),
        "libaltacast.cpp config fopen",
    )
    t = sub_once(
        t,
        r"(\tfclose\(filep\);\n)(\n\treturn 1;\n\}\n\nvoid printConfigFileValues)",
        lambda m: m.group(1) + "\tCommitConfigFile(configFile, tmpFile);\n" + m.group(2),
        "libaltacast.cpp config fclose",
    )
    return t


# ----------------------------------------------------------------------
# apply
# ----------------------------------------------------------------------

patch_file("Config.cpp", fix_lock_config)
patch_file("BasicSettings.h", fix_lock_header)
patch_file("BasicSettings.cpp", fix_lock_cpp)
patch_file("altacastStandalone.cpp", fix_instance)
patch_file("libaltacast/libaltacast.cpp", lambda t: fix_backup(fix_password(fix_fflush(t))))
patch_file("MainWindow.cpp", fix_recording)
print(TAG + ": done")
