#!/usr/bin/env python3
"""
04_ui.py - メイン画面と設定画面 (AltaCast)

  [メイン画面の一覧]
    1. Time 列        接続時間 (00:00:00)
    2. 列の記憶       列幅 / 並び順 / 接続チェック / ウィンドウサイズを設定ファイルに保存
                      (ListColumnWidths / ListColumnOrder / ListChecked / WindowSize)
                      Mount / Stream Name 列、接続チェックボックス、列の並べ替え
    3. サイズ変更     枠をドラッグして拡大縮小・最大化。メーター・Live Recording も幅に追従
    4. メーター       幅の変化に合わせて描画領域を作り直す (バッファ 4096 x 128)
  [Live Recording]
    5. 無音で全点灯   メーターが無音で全点灯する問題 (log10(0) = -inf) を修正
    6. スピーカー選択 入力ごとの音量調整がないデバイスは、ソフトウェア音量 (0〜100%) に切替
  [Basic Settings]
    7. Comment        エンコーダーごとの自分用メモ (配信には送らない)。
                      入力欄 + 一覧の一番右の Comment 列。接続中はロック

使い方:  python tools/04_ui.py trunk/AltaCast/src
冪等。アンカーが見つからなければエラーで停止。
"""

import re
import sys
from pathlib import Path

import patchlib as P

TAG = "altacast_ui"
P.init(TAG)
SRC = P.SRC
from patchlib import fail, sub_once, sub_n, after, patch_file, c_wide  # noqa: E402,F401


# ----------------------------------------------------------------------
# 1. Time 列 (接続時間)
# ----------------------------------------------------------------------

MARK_TIME = TAG + ": time"


def fix_time_header(t):
    if MARK_TIME in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)afx_msg void OnTimer\(UINT nIDEvent\);\n",
        lambda m: m.group(0) + m.group(1) + "void UpdateConnectionTimes();   /* %s */\n" % MARK_TIME,
        "MainWindow.h OnTimer declaration",
    )


TIME_FUNC = '/* %s: shows how long each encoder has been connected (hh:mm:ss) in the list */\nvoid CMainWindow::UpdateConnectionTimes() {\n\tstatic ULONGLONG\tconnStart[MAX_ENCODERS];\n\tstatic BOOL\t\t\twasConnected[MAX_ENCODERS];\n\tint\t\t\t\t\tnumItems = m_Encoders.GetItemCount();\n\tint\t\t\t\t\ti;\n\tstatic int\t\t\twidenedBy = 0;\t/* extra characters (100 hours or more) the column was widened for */\n\n\tfor (i = 0; i < numItems && i < MAX_ENCODERS; i++) {\n\t\tBOOL\tconnected = %s;\n\t\tCString\ttext;\n\n\t\tif (connected && !wasConnected[i]) {\n\t\t\tconnStart[i] = GetTickCount64();\n\t\t}\n\t\twasConnected[i] = connected;\n\t\tif (connected) {\n\t\t\tULONGLONG sec = (GetTickCount64() - connStart[i]) / 1000;\n\t\t\ttext.Format("%%02u:%%02u:%%02u", (unsigned int) (sec / 3600), (unsigned int) ((sec / 60) %% 60), (unsigned int) (sec %% 60));\n\t\t}\n\t\tif (m_Encoders.GetItemText(i, %d) != text) {\n\t\t\tm_Encoders.SetItemText(i, %d, text);\n\t\t}\n\t\tif (text.GetLength() > 8 && text.GetLength() - 8 > widenedBy) {\n\t\t\tm_Encoders.SetColumnWidth(%d, m_Encoders.GetColumnWidth(%d) + (text.GetLength() - 8 - widenedBy) * 8);\n\t\t\twidenedBy = text.GetLength() - 8;\n\t\t}\n\t}\n}\n\n'


TIME_EARLY = '\tif (nIDEvent == 74) {\t/* %s: connection time */\n\t\tUpdateConnectionTimes();\n\t\treturn;\n\t}\n'


TIME_COLS = 'm_Encoders.InsertColumn(1, "Transfer Rate");\n\tm_Encoders.InsertColumn(2, "Time");\t/* %s: connection time */\n\tm_Encoders.SetColumnWidth(0, 170);\n\tm_Encoders.SetColumnWidth(1, 165);\n\tm_Encoders.SetColumnWidth(2, 60);\n\tSetTimer(74, 1000, 0);\t/* once a second: update the connection time */'


def fix_time_cpp(t):
    if MARK_TIME in t:
        return t
    t = sub_once(
        t,
        r"m_Encoders\.InsertColumn\(1, \"Transfer Rate\"\);\s*m_Encoders\.SetColumnWidth\(0, 195\);\s*m_Encoders\.SetColumnWidth\(1, 200\);",
        lambda m: TIME_COLS % MARK_TIME,
        "MainWindow.cpp list columns",
    )
    t = sub_once(
        t,
        r"void CMainWindow::OnTimer\(UINT nIDEvent\) \{\n",
        lambda m: (TIME_FUNC % (MARK_TIME, '(g[i] != NULL && g[i]->weareconnected)', 2, 2, 2, 2)) + 'void CMainWindow::OnTimer(UINT nIDEvent) {\n' + (TIME_EARLY % MARK_TIME),
        "MainWindow.cpp OnTimer",
    )
    return t


# ----------------------------------------------------------------------
# 2. 列幅・並び順・チェック・ウィンドウサイズの記憶
# ----------------------------------------------------------------------

MARK_COLW = TAG + ": colw"


LIST_VARS = ["ListColumnWidths", "ListColumnOrder", "ListChecked", "WindowSize"]


LIST_MEMB = ['gListColumnWidths', 'gListColumnOrder', 'gListChecked', 'gWindowSize']


def fix_colw_libheader(t):
    if MARK_COLW in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)int    autoconnect;\n",
        lambda m: m.group(0) + m.group(1) + "char   gListColumnWidths[64];   /* altacast_ui: colw */\n" + m.group(1) + "char   gListColumnOrder[64];\n" + m.group(1) + "char   gListChecked[128];\n" + m.group(1) + "char   gWindowSize[32];\n",
        "libheader members",
    )


def fix_colw_lib(t):
    if MARK_COLW in t:
        return t
    load = ""
    store = ""
    add = ""
    for v, mb in zip(LIST_VARS, LIST_MEMB):
        load += '\tGetConfigVariable(g, g->gAppName, "%s", "", g->%s, sizeof(g->%s), NULL);\n' % (v, mb, mb)
        store += '\tPutConfigVariable(g, g->gAppName, "%s", g->%s);\n' % (v, mb)
        add += '\taddConfigVariable(g, "%s");\n' % v
    t = sub_once(
        t,
        r'([ \t]*)g->autoconnect = GetConfigVariableLong\(g, g->gAppName, "AutoConnect", 0, NULL\);\n',
        lambda m: m.group(0) + m.group(1) + '/* %s: remembered list state (widths, order, checks, window size) */\n' % MARK_COLW + load,
        "lib load",
    )
    t = sub_once(
        t,
        r'([ \t]*)PutConfigVariableLong\(g, g->gAppName, "AutoConnect", g->autoconnect\);\n',
        lambda m: m.group(0) + store,
        "lib store",
    )
    t, n = re.subn(
        r'([ \t]*)addConfigVariable\(g, "AutoConnect"\);\n',
        lambda m: m.group(0) + add,
        t,
    )
    if n != 2:
        fail("lib AddConfigVariable AutoConnect: expected 2, found %d" % n)
    return t


UI3_STATICS = '/* altacast_ui: colw: list state kept in the config file (column widths / order, checked encoders, window size) */\n#define LIST_NUMCOLS 5\nstatic bool\ts_encUnchecked[MAX_ENCODERS + 1];\nstatic bool\ts_syncingChecks = false;\nstatic bool\ts_layoutReady = false;\n#define RS_MAX 160\nenum { RS_FIXED = 0, RS_STRETCH_W, RS_STRETCH_WH, RS_STATUS, RS_MOVE_DX, RS_PROP, RS_HALF_STRETCH, RS_HALF_MOVE_STRETCH, RS_HALF_MOVE };\nstatic HWND\ts_rsWnd[RS_MAX];\nstatic RECT\ts_rsRect[RS_MAX];\nstatic int\ts_rsMode[RS_MAX];\nstatic int\ts_rsCount = 0;\nstatic int\ts_meterLeft = 0, s_meterWidth = 1;\nstatic bool\ts_meterReady = false;\nstatic int\ts_initCx = 0, s_initCy = 0, s_minWinW = 0, s_minWinH = 0;\n\nstatic bool IsEncoderChecked(int i) {\n\tif (i < 0 || i >= MAX_ENCODERS) {\n\t\treturn true;\n\t}\n\treturn !s_encUnchecked[i];\n}\n\n'


UI3_MEMBERS = '/* altacast_ui: colw: restore / save the list state (widths, order, checked encoders, window size) */\nvoid CMainWindow::ApplyListState() {\n\tconst char\t*p;\n\tint\t\t\ti;\n\tint\t\t\torder[LIST_NUMCOLS];\n\tint\t\t\tused[LIST_NUMCOLS];\n\tint\t\t\tn = 0;\n\tint\t\t\tok = 1;\n\n\t/* widths: "a,b,c,..." */\n\tp = gMain.gListColumnWidths;\n\ti = 0;\n\twhile (i < LIST_NUMCOLS && *p) {\n\t\tint v = atoi(p);\n\t\tif (v >= 20 && v <= 800) {\n\t\t\tm_Encoders.SetColumnWidth(i, v);\n\t\t}\n\t\ti++;\n\t\tp = strchr(p, \',\');\n\t\tif (p == NULL) {\n\t\t\tbreak;\n\t\t}\n\t\tp++;\n\t}\n\n\t/* order: a permutation of 0..LIST_NUMCOLS-1 with column 0 (the check box column) first */\n\tmemset(used, 0, sizeof(used));\n\tp = gMain.gListColumnOrder;\n\twhile (n < LIST_NUMCOLS && *p) {\n\t\tint v = atoi(p);\n\t\tif (v < 0 || v >= LIST_NUMCOLS || used[v]) {\n\t\t\tok = 0;\n\t\t\tbreak;\n\t\t}\n\t\tused[v] = 1;\n\t\torder[n++] = v;\n\t\tp = strchr(p, \',\');\n\t\tif (p == NULL) {\n\t\t\tbreak;\n\t\t}\n\t\tp++;\n\t}\n\tif (ok && n == LIST_NUMCOLS && order[0] == 0) {\n\t\tm_Encoders.SetColumnOrderArray(LIST_NUMCOLS, order);\n\t}\n\n\t/* checked encoders: one character per encoder, 1 = checked, 0 = not checked */\n\tp = gMain.gListChecked;\n\ti = 0;\n\tfor (; *p && i < MAX_ENCODERS; p++) {\n\t\tif (*p == \'0\') {\n\t\t\ts_encUnchecked[i++] = true;\n\t\t}\n\t\telse if (*p == \'1\') {\n\t\t\ts_encUnchecked[i++] = false;\n\t\t}\n\t}\n}\n\nvoid CMainWindow::SaveListState() {\n\tint\t\t\t\ti;\n\tint\t\t\t\torder[LIST_NUMCOLS];\n\tchar\t\t\ttmp[32];\n\tWINDOWPLACEMENT\twp;\n\n\tgMain.gListColumnWidths[0] = \'\\000\';\n\tfor (i = 0; i < LIST_NUMCOLS; i++) {\n\t\tsprintf(tmp, "%s%d", (i > 0) ? "," : "", m_Encoders.GetColumnWidth(i));\n\t\tstrcat(gMain.gListColumnWidths, tmp);\n\t}\n\n\tif (m_Encoders.GetColumnOrderArray(order, LIST_NUMCOLS)) {\n\t\tgMain.gListColumnOrder[0] = \'\\000\';\n\t\tfor (i = 0; i < LIST_NUMCOLS; i++) {\n\t\t\tsprintf(tmp, "%s%d", (i > 0) ? "," : "", order[i]);\n\t\t\tstrcat(gMain.gListColumnOrder, tmp);\n\t\t}\n\t}\n\n\tfor (i = 0; i < gMain.gNumEncoders && i < MAX_ENCODERS; i++) {\n\t\tgMain.gListChecked[i] = s_encUnchecked[i] ? \'0\' : \'1\';\n\t\tgMain.gListChecked[i + 1] = \'\\000\';\n\t}\n\n\tmemset(&wp, 0, sizeof(wp));\n\twp.length = sizeof(wp);\n\tif (GetWindowPlacement(&wp)) {\n\t\tsprintf(gMain.gWindowSize, "%d,%d", (int) (wp.rcNormalPosition.right - wp.rcNormalPosition.left), (int) (wp.rcNormalPosition.bottom - wp.rcNormalPosition.top));\n\t}\n}\n\n/* altacast_ui: colw: the window can be resized; the list, the level meter and the Live Recording box grow with it */\nvoid CMainWindow::InitResizeLayout() {\n\tCRect\trc;\n\tRECT\trcMeter;\n\tCWnd\t*pWnd;\n\tint\t\tw = 0, h = 0;\n\n\tGetClientRect(&rc);\n\ts_initCx = rc.Width();\n\ts_initCy = rc.Height();\n\tGetWindowRect(&rc);\n\ts_minWinW = rc.Width();\n\ts_minWinH = rc.Height();\n\n\tmemset(&rcMeter, 0, sizeof(rcMeter));\n\tpWnd = GetDlgItem(IDC_METER);\n\tif (pWnd != NULL) {\n\t\tpWnd->GetWindowRect(&rcMeter);\n\t\tScreenToClient(&rcMeter);\n\t}\n\ts_meterLeft = rcMeter.left;\n\ts_meterWidth = (rcMeter.right - rcMeter.left > 0) ? (rcMeter.right - rcMeter.left) : 1;\n\n\ts_rsCount = 0;\n\tfor (pWnd = GetWindow(GW_CHILD); pWnd != NULL && s_rsCount < RS_MAX; pWnd = pWnd->GetWindow(GW_HWNDNEXT)) {\n\t\tRECT\tr;\n\t\tchar\tcls[32] = "";\n\t\tint\t\tid = pWnd->GetDlgCtrlID();\n\t\tint\t\tmode = RS_FIXED;\n\t\tint\t\tisGroup;\n\n\t\tpWnd->GetWindowRect(&r);\n\t\tScreenToClient(&r);\n\t\tGetClassNameA(pWnd->m_hWnd, cls, 31);\n\t\tisGroup = (_stricmp(cls, "Button") == 0 && (pWnd->GetStyle() & BS_TYPEMASK) == BS_GROUPBOX);\n\t\tif (id == IDC_ENCODERS) {\n\t\t\tmode = RS_STRETCH_WH;\n\t\t}\n\t\telse if (id == IDC_METADATA || id == IDC_METER || id == IDC_RECVOLUME || isGroup) {\n\t\t\tmode = RS_STRETCH_W;\n\t\t}\n\t\telse if (id == IDC_STATIC_STATUS) {\n\t\t\tmode = RS_STATUS;\n\t\t}\n\t\telse if (id == IDC_RECCARDS) {\n\t\t\tmode = RS_HALF_STRETCH;\n\t\t}\n\t\telse if (id == IDC_RECDEVICES) {\n\t\t\tmode = RS_HALF_MOVE_STRETCH;\n\t\t}\n\t\telse if (rcMeter.right > rcMeter.left && r.top >= rcMeter.top - 8 && r.bottom <= rcMeter.bottom + 20) {\n\t\t\t/* labels around the level meter: left of it stay, right of it move, the scale follows the meter */\n\t\t\tif (r.left < rcMeter.left + 2) {\n\t\t\t\tmode = RS_FIXED;\n\t\t\t}\n\t\t\telse if (r.left >= rcMeter.right) {\n\t\t\t\tmode = RS_MOVE_DX;\n\t\t\t}\n\t\t\telse {\n\t\t\t\tmode = RS_PROP;\n\t\t\t}\n\t\t}\n\t\ts_rsWnd[s_rsCount] = pWnd->m_hWnd;\n\t\ts_rsRect[s_rsCount] = r;\n\t\ts_rsMode[s_rsCount] = mode;\n\t\ts_rsCount++;\n\t}\n#ifdef IDC_LIMITDB\n\t/* the Limiter box: the Gain and Limit sliders share the width, the Pre-Emphasis slider uses all of it */\n\t{\n\t\tCWnd\t*pGain = GetDlgItem(IDC_GAINDB);\n\t\tCWnd\t*pPre = GetDlgItem(IDC_LIMITPREEMPH);\n\n\t\tif (pGain != NULL && pPre != NULL) {\n\t\t\tRECT\trg, rp;\n\t\t\tint\t\tk;\n\n\t\t\tpGain->GetWindowRect(&rg);\n\t\t\tScreenToClient(&rg);\n\t\t\tpPre->GetWindowRect(&rp);\n\t\t\tScreenToClient(&rp);\n\t\t\tfor (k = 0; k < s_rsCount; k++) {\n\t\t\t\tint\t\tid = ::GetDlgCtrlID(s_rsWnd[k]);\n\t\t\t\tRECT\t*r = &s_rsRect[k];\n\n\t\t\t\tif (id == IDC_GAINDB) {\n\t\t\t\t\ts_rsMode[k] = RS_HALF_STRETCH;\n\t\t\t\t}\n\t\t\t\telse if (id == IDC_LIMITDB) {\n\t\t\t\t\ts_rsMode[k] = RS_HALF_MOVE_STRETCH;\n\t\t\t\t}\n\t\t\t\telse if (id == IDC_LIMITPREEMPH) {\n\t\t\t\t\ts_rsMode[k] = RS_STRETCH_W;\n\t\t\t\t}\n\t\t\t\telse if (s_rsMode[k] == RS_FIXED && r->top >= rp.top - 3 && r->bottom <= rp.bottom + 3 && r->left >= rp.right - 1) {\n\t\t\t\t\ts_rsMode[k] = RS_MOVE_DX;\n\t\t\t\t}\n\t\t\t\telse if (s_rsMode[k] == RS_FIXED && r->top >= rg.top - 3 && r->bottom < rp.top - 3 && r->left >= rg.right + 8) {\n\t\t\t\t\ts_rsMode[k] = RS_HALF_MOVE;\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n#endif\n\ts_layoutReady = true;\n\n\tif (sscanf(gMain.gWindowSize, "%d,%d", &w, &h) == 2 && w >= s_minWinW && h >= s_minWinH &&\n\t\tw <= GetSystemMetrics(SM_CXSCREEN) && h <= GetSystemMetrics(SM_CYSCREEN)) {\n\t\tSetWindowPos(NULL, 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);\n\t\tCenterWindow();\n\t}\n}\n\nvoid CMainWindow::OnSize(UINT nType, int cx, int cy) {\n\tint\t\tdx, dy, i;\n\n\tCDialog::OnSize(nType, cx, cy);\n\tif (!s_layoutReady || nType == SIZE_MINIMIZED || m_Encoders.GetSafeHwnd() == NULL) {\n\t\treturn;\n\t}\n\tdx = cx - s_initCx;\n\tdy = cy - s_initCy;\n\tfor (i = 0; i < s_rsCount; i++) {\n\t\tRECT r = s_rsRect[i];\n\n\t\tswitch (s_rsMode[i]) {\n\t\t\tcase RS_STRETCH_W:\n\t\t\t\tr.right += dx;\n\t\t\t\tbreak;\n\t\t\tcase RS_STRETCH_WH:\n\t\t\t\tr.right += dx;\n\t\t\t\tr.bottom += dy;\n\t\t\t\tbreak;\n\t\t\tcase RS_STATUS:\n\t\t\t\tr.top += dy;\n\t\t\t\tr.bottom += dy;\n\t\t\t\tr.right += dx;\n\t\t\t\tbreak;\n\t\t\tcase RS_MOVE_DX:\n\t\t\t\tr.left += dx;\n\t\t\t\tr.right += dx;\n\t\t\t\tbreak;\n\t\t\tcase RS_PROP: {\n\t\t\t\tint shift = (int) (((__int64) (s_rsRect[i].left - s_meterLeft)) * dx / s_meterWidth);\n\t\t\t\tr.left += shift;\n\t\t\t\tr.right += shift;\n\t\t\t\tbreak;\n\t\t\t}\n\t\t\tcase RS_HALF_STRETCH:\n\t\t\t\tr.right += dx / 2;\n\t\t\t\tbreak;\n\t\t\tcase RS_HALF_MOVE:\n\t\t\t\tr.left += dx / 2;\n\t\t\t\tr.right += dx / 2;\n\t\t\t\tbreak;\n\t\t\tcase RS_HALF_MOVE_STRETCH:\n\t\t\t\tr.left += dx / 2;\n\t\t\t\tr.right += dx;\n\t\t\t\tbreak;\n\t\t\tdefault:\n\t\t\t\tcontinue;\n\t\t}\n\t\t::SetWindowPos(s_rsWnd[i], NULL, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_NOZORDER | SWP_NOACTIVATE);\n\t}\n\tif (s_meterReady) {\n\t\tflexmeters.RecalcGeometry();\n\t}\n\tRedrawWindow(NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN);\n}\n\nvoid CMainWindow::OnGetMinMaxInfo(MINMAXINFO *lpMMI) {\n\tCDialog::OnGetMinMaxInfo(lpMMI);\n\tif (s_layoutReady) {\n\t\tlpMMI->ptMinTrackSize.x = s_minWinW;\n\t\tlpMMI->ptMinTrackSize.y = s_minWinH;\n\t}\n}\n\n/* altacast_ui: colw: the first column (with the check box) stays first; check box clicks are remembered */\nBOOL CMainWindow::OnNotify(WPARAM wParam, LPARAM lParam, LRESULT *pResult) {\n\tNMHDR\t*pHdr = (NMHDR *) lParam;\n\n\tif (pHdr != NULL) {\n\t\tif (pHdr->code == HDN_BEGINDRAG) {\n\t\t\tNMHEADER *ph = (NMHEADER *) lParam;\n\t\t\tif (ph->iItem == 0) {\n\t\t\t\t*pResult = TRUE;\n\t\t\t\treturn TRUE;\n\t\t\t}\n\t\t}\n\t\telse if (pHdr->code == HDN_ENDDRAG) {\n\t\t\tNMHEADER *ph = (NMHEADER *) lParam;\n\t\t\tif (ph->iItem == 0 || (ph->pitem != NULL && (ph->pitem->mask & HDI_ORDER) && ph->pitem->iOrder == 0)) {\n\t\t\t\t*pResult = TRUE;\n\t\t\t\treturn TRUE;\n\t\t\t}\n\t\t}\n\t\telse if (pHdr->code == LVN_ITEMCHANGED && pHdr->hwndFrom == m_Encoders.m_hWnd) {\n\t\t\tNMLISTVIEW *pnm = (NMLISTVIEW *) lParam;\n\t\t\tif (!s_syncingChecks && (pnm->uChanged & LVIF_STATE) && pnm->iItem >= 0 && pnm->iItem < MAX_ENCODERS) {\n\t\t\t\tUINT oldImg = (pnm->uOldState & LVIS_STATEIMAGEMASK) >> 12;\n\t\t\t\tUINT newImg = (pnm->uNewState & LVIS_STATEIMAGEMASK) >> 12;\n\t\t\t\tif (oldImg != 0 && newImg != 0 && oldImg != newImg) {\n\t\t\t\t\ts_encUnchecked[pnm->iItem] = (newImg != 2);\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n\treturn CDialog::OnNotify(wParam, lParam, pResult);\n}\n\n/* altacast_ui: colw: fills the Mount / Stream Name columns and keeps the check boxes in step */\nvoid CMainWindow::UpdateExtraColumns() {\n\tint\t\tnumItems = m_Encoders.GetItemCount();\n\tint\t\ti;\n\n\tfor (i = 0; i < numItems && i < MAX_ENCODERS && i < gMain.gNumEncoders; i++) {\n\t\tint want = s_encUnchecked[i] ? 0 : 1;\n\n\t\tif (g[i] == NULL) {\n\t\t\tcontinue;\n\t\t}\n\t\tif (m_Encoders.GetItemText(i, 3) != g[i]->gMountpoint) {\n\t\t\tm_Encoders.SetItemText(i, 3, g[i]->gMountpoint);\n\t\t}\n\t\tif (m_Encoders.GetItemText(i, 4) != g[i]->gServName) {\n\t\t\tm_Encoders.SetItemText(i, 4, g[i]->gServName);\n\t\t}\n\t\tif (m_Encoders.GetCheck(i) != want) {\n\t\t\ts_syncingChecks = true;\n\t\t\tm_Encoders.SetCheck(i, want);\n\t\t\ts_syncingChecks = false;\n\t\t}\n\t}\n}\n\n'


def fix_colw_header(t):
    if MARK_COLW in t:
        return t
    decl = (
        "void ApplyListState();   /* " + MARK_COLW + "*/\n"
        "void SaveListState();\n"
        "void InitResizeLayout();\n"
        "void UpdateExtraColumns();\n"
        "afx_msg void OnSize(UINT nType, int cx, int cy);\n"
        "afx_msg void OnGetMinMaxInfo(MINMAXINFO *lpMMI);\n"
        "virtual BOOL OnNotify(WPARAM wParam, LPARAM lParam, LRESULT *pResult);\n"
    )
    return sub_once(
        t,
        r"([ \t]*)afx_msg void OnTimer\(UINT nIDEvent\);\n",
        lambda m: m.group(0) + "".join(m.group(1) + line + "\n" for line in decl.splitlines()),
        "MainWindow.h declarations (colw)",
    )


def fix_colw_cpp(t):
    if MARK_COLW in t:
        return t
    t = sub_once(
        t,
        r"([ \t]*)ON_WM_TIMER\(\)\n",
        lambda m: m.group(0) + m.group(1) + "ON_WM_SIZE()\n" + m.group(1) + "ON_WM_GETMINMAXINFO()\n",
        "MainWindow.cpp message map (size)",
    )
    t = sub_once(
        t,
        r"int CMainWindow::startaltacast\(int which\) \{\n",
        lambda m: UI3_STATICS + m.group(0),
        "MainWindow.cpp start function (statics)",
    )
    t = sub_once(
        t,
        r"(\t\t\tif\(!g\[i\]->weareconnected)(\) \{\n\t\t\t\tsetForceStop\(g\[i\], 0\);)",
        lambda m: m.group(1) + " && IsEncoderChecked(i)" + m.group(2),
        "MainWindow.cpp connect only checked encoders",
    )
    t = sub_once(
        t,
        r"([ \t]*)m_Encoders\.SetCheck\(m_Encoders\.GetSelectionMark\(\), true\);\n",
        lambda m: m.group(1) + '/* %s: the focus must not force the check box on */\n' % MARK_COLW,
        "MainWindow.cpp focus check",
    )
    t = sub_once(
        t,
        r"([ \t]*)m_Encoders\.SetExtendedStyle\(LVS_EX_FULLROWSELECT\);\n",
        lambda m: '\tm_Encoders.InsertColumn(3, "Mount");   /* %s */\n\tm_Encoders.InsertColumn(4, "Stream Name");\n\tm_Encoders.SetColumnWidth(3, 90);\n\tm_Encoders.SetColumnWidth(4, 130);\n' % MARK_COLW + m.group(1) + 'm_Encoders.SetExtendedStyle(LVS_EX_FULLROWSELECT | LVS_EX_CHECKBOXES | LVS_EX_HEADERDRAGDROP);   /* %s */\n' % MARK_COLW + m.group(1) + "ApplyListState();\n" + m.group(1) + "InitResizeLayout();\n",
        "MainWindow.cpp list style",
    )
    t = sub_once(
        t,
        r"([ \t]*)setAuto\(m_AutoConnect\);\n",
        lambda m: m.group(0) + m.group(1) + "SaveListState();\n",
        "MainWindow.cpp OnDestroy",
    )
    t = sub_once(
        t,
        r"void CMainWindow::UpdateConnectionTimes\(\) \{\n",
        lambda m: 'void CMainWindow::UpdateConnectionTimes() {\n\tUpdateExtraColumns();   /* %s */\n' % MARK_COLW,
        "MainWindow.cpp UpdateConnectionTimes",
    )
    t = sub_once(
        t,
        r"void CMainWindow::OnTimer\(UINT nIDEvent\) \{\n",
        lambda m: UI3_MEMBERS + m.group(0),
        "MainWindow.cpp members",
    )
    t = sub_once(
        t,
        r"(fmis->max_x\s*=\s*)512;",
        lambda m: m.group(1) + "4096;",
        "MainWindow.cpp meter buffer width",
    )
    t = sub_once(
        t,
        r"(fmis->max_y\s*=\s*)512;",
        lambda m: m.group(1) + "128;",
        "MainWindow.cpp meter buffer height",
    )
    t = sub_once(
        t,
        r"([ \t]*)flexmeters\.Initialize_Step3\(\);[^\n]*\n",
        lambda m: m.group(0) + m.group(1) + "s_meterReady = true;\n",
        "MainWindow.cpp meter ready flag",
    )
    return t


# ----------------------------------------------------------------------
# 3. ウィンドウのサイズ変更
# ----------------------------------------------------------------------

def fix_resize_rc(t):
    m = re.search(r"IDD_ALTACAST DIALOGEX[^\n]*\nSTYLE [^\n]*", t)
    if m is None:
        fail("rc: IDD_ALTACAST STYLE not found")
    if "WS_THICKFRAME" in m.group(0):
        return t
    end = m.end()
    if t[end - 1] == "\r":
        end -= 1
    return t[:end] + " | WS_THICKFRAME | WS_MAXIMIZEBOX" + t[end:]


# ----------------------------------------------------------------------
# 4. メーターの幅追従
# ----------------------------------------------------------------------

MARK_METER = TAG + ": meter"


def fix_meter_cpp(t):
    if MARK_METER in t:
        return t
    return sub_once(
        t,
        r"(    intbuffer = \(int \*\) buffer;\n)(\s*)(    RECT rect;\n\s*GetClientRect\(fmis\.hWndFrame, &rect\);\n)",
        lambda m: m.group(1)
        + "\n    RecalcGeometry();\n}\n\n"
        + "// " + MARK_METER + ": the meter positions are calculated again when the window is resized\n"
        + "void CFlexMeters::RecalcGeometry()\n{\n"
        + "    RECT rect;\n\n    GetClientRect(fmis.hWndFrame, &rect);\n"
        + "    if (rect.right - rect.left > fmis.max_x) rect.right = rect.left + fmis.max_x;\n"
        + "    if (rect.bottom - rect.top > fmis.max_y) rect.bottom = rect.top + fmis.max_y;\n",
        "FlexMeters.cpp Initialize_Step3",
    )


def fix_meter_h(t):
    if MARK_METER in t:
        return t
    return sub_once(
        t,
        r"([ \t]*void[ \t]+Initialize_Step3\(\);[^\n]*\n)",
        lambda m: m.group(1) + "\tvoid RecalcGeometry();   // " + MARK_METER + "\n",
        "FlexMeters.h",
    )


# ----------------------------------------------------------------------
# 5. メーター 無音で全点灯する問題
# ----------------------------------------------------------------------

MARK_SILENCE = TAG + ": silence"


def fix_silence_main(t):
    if MARK_SILENCE in t:
        return t
    new = (
        "/* " + MARK_SILENCE + ": silence gives log10(0) = -inf; keep the meter values in 0..60 */\n"
        "\t{\n"
        "\t\tint\tpl = (leftMax > 0) ? ((int) newL + 60) : 0;\n"
        "\t\tint\tpr = (rightMax > 0) ? ((int) newR + 60) : 0;\n"
        "\t\tif (pl < 0) pl = 0;\n"
        "\t\tif (pl > 60) pl = 60;\n"
        "\t\tif (pr < 0) pr = 0;\n"
        "\t\tif (pr > 60) pr = 60;\n"
        "\t\tUpdatePeak(pl, pr);\n"
        "\t}"
    )
    return sub_once(
        t,
        r"UpdatePeak\(\(int\) newL \+ 60, \(int\) newR \+ 60\);",
        lambda m: new,
        "MainWindow.cpp UpdatePeak call",
    )


def fix_silence_cpp(t):
    if MARK_SILENCE in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)if \(!y_size\) return ;\n",
        lambda m: m.group(0)
        + m.group(1) + "/* " + MARK_SILENCE + ": clamp, so that the width * value arithmetic cannot overflow */\n"
        + m.group(1) + "if (value < 0) value = 0;\n"
        + m.group(1) + "if (value > MAX_VALUE) value = MAX_VALUE;\n"
        + m.group(1) + "if (peak < 0) peak = 0;\n"
        + m.group(1) + "if (peak > MAX_VALUE) peak = MAX_VALUE;\n",
        "FlexMeters.cpp drawmeter_horizontal",
    )


def fix_silence_h(t):
    if MARK_SILENCE in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)value = 100;\n",
        lambda m: m.group(0) + m.group(1) + "peak = 0;   // " + MARK_SILENCE + "\n",
        "FlexMeters.h default values",
    )


# ----------------------------------------------------------------------
# 6. Live Recording スピーカー選択時のソフトウェア音量
# ----------------------------------------------------------------------

MARK_REC = TAG + ": rec"


REC_HELPERS = r'''/* __MARK__: software volume for recording devices without an input volume control (loopback / speakers) */
static volatile int s_recSoftOn = 0;
static volatile int s_recSoftVol = 100;

static float RecSoftGain() {
	return s_recSoftOn ? ((float) s_recSoftVol / 100.0f) : 1.0f;
}

static int RecCountInputs() {
	int n = 0;

	while (BASS_RecordGetInputName(n) != NULL) {
		n++;
	}
	return n;
}

static void RecSoftMode(bool on) {
	s_recSoftVol = 100;
	s_recSoftOn = on ? 1 : 0;
}

/* tries the real input volume first; if the input does not exist or has no volume control, the software volume is used */
static void RecApplyVolume(int input, int percent) {
	BOOL ok = FALSE;

	if (percent < 0) {
		percent = 0;
	}
	if (percent > 100) {
		percent = 100;
	}
	if (input >= 0 && BASS_RecordGetInputName(input) != NULL) {
		ok = BASS_RecordSetInput(input, BASS_INPUT_ON, (float) percent / 100.0f);
	}
	if (ok) {
		RecSoftMode(false);
	}
	else {
		s_recSoftVol = percent;
		s_recSoftOn = 1;
	}
}

'''.replace("__MARK__", MARK_REC)


# placed right after the input list of the selected device has been read (BASS device initialised)
REC_DEVICE_CHANGED = (
    "\t/* " + MARK_REC + ": no inputs (loopback / speakers) -> the slider is a software volume */\n"
    "\tif (RecCountInputs() == 0) {\n"
    "\t\tRecSoftMode(true);\n"
    "\t\tm_RecVolume = 100;\n"
    "\t\tm_RecDevicesCtrl.AddString(\"Speakers (software volume)\");\n"
    "\t\tm_RecDevicesCtrl.SetCurSel(0);\n"
    "\t\tm_RecDevices = \"Speakers (software volume)\";\n"
    "\t\tgeneralStatusCallback((void *) \"This recording device has no input volume control: the slider works as a software volume\");\n"
    "\t}\n"
    "\telse {\n"
    "\t\tRecSoftMode(false);\n"
    "\t}\n"
)


REC_STARTUP = (
    "\t/* " + MARK_REC + ": read the inputs of the selected recording device (it was always device 0) */\n"
    "\tif (m_CurrentInputCard > 0 && m_CurrentInputCard < 256) {\n"
    "\t\tBASS_RecordFree();\n"
    "\t\tif (!BASS_RecordInit(m_CurrentInputCard)) {\n"
    "\t\t\tBASS_RecordInit(0);\n"
    "\t\t}\n"
    "\t}\n"
    "\tif (RecCountInputs() == 0) {\n"
    "\t\tRecSoftMode(true);\n"
    "\t\tm_RecVolume = 100;\n"
    "\t\tm_RecDevicesCtrl.AddString(\"Speakers (software volume)\");\n"
    "\t\tm_RecDevicesCtrl.SetCurSel(0);\n"
    "\t\tm_RecDevices = \"Speakers (software volume)\";\n"
    "\t}\n"
    "\telse {\n"
    "\t\tRecSoftMode(false);\n"
    "\t}\n"
)


def fix_rec_main(t):
    if MARK_REC in t:
        return t

    # (a) helpers before the record callback
    t = sub_once(
        t,
        r"(BOOL CALLBACK BASSwaveInputProc\(HRECORD handle, const void \*buffer, DWORD length, void \*user\) \{)",
        lambda m: REC_HELPERS + m.group(1),
        "MainWindow.cpp BASSwaveInputProc",
    )

    # (b) software gain on the recorded samples
    t = sub_once(
        t,
        r"(samples\[i\] = sample / 32767\.f;)",
        lambda m: "samples[i] = sample / 32767.f * RecSoftGain();   /* " + MARK_REC + " */",
        "MainWindow.cpp sample conversion",
    )

    # (c) slider
    t = sub_once(
        t,
        r"BASS_RecordSetInput\(m_CurrentInput, BASS_INPUT_ON, \(float\)\(\(float\)m_RecVolume/100\)\);",
        lambda m: "RecApplyVolume(m_CurrentInput, m_RecVolume);   /* " + MARK_REC + " */",
        "MainWindow.cpp OnHScroll volume",
    )

    # (d) start-up: input list of the selected device (before the first input loop that fills the combo box)
    t = sub_once(
        t,
        r"([ \t]*)(for\(n = 0; name = \(char \*\)BASS_RecordGetInputName\(n\); n\+\+\) \{\n"
        r"[ \t]*float vol = 0\.0;\n"
        r"[ \t]*int s = BASS_RecordGetInput\(n, &vol\);\n"
        r"[ \t]*m_RecDevicesCtrl\.AddString\(name\);)",
        lambda m: REC_STARTUP + m.group(1) + m.group(2),
        "MainWindow.cpp start-up input list",
    )

    # (e) card changed in the combo box: right after the combo box of inputs is cleared
    t = sub_once(
        t,
        r"([ \t]*m_RecDevicesCtrl\.ResetContent\(\);\n)",
        lambda m: m.group(1) + REC_DEVICE_CHANGED,
        "MainWindow.cpp OnSelchangeReccards",
    )
    return t


# ----------------------------------------------------------------------
# 7. エンコーダーの Comment
# ----------------------------------------------------------------------

MARK_COMMENT = TAG + ": comment"


COMMENT_GROW = 17           # dialog units added to the Basic Settings page
COMMENT_W = 125          # width of the Comment input field (dialog units; it was 190)


def comment_grow(m):
    return m.group(1) + str(int(m.group(2)) + COMMENT_GROW)


def comment_resource(t):
    if "IDC_ENCCOMMENT" in t:
        return t
    return after(
        t,
        r"#define IDC_RECONNECTSECS[^\n]*\n",
        "#define IDC_ENCCOMMENT\t\t\t\t\t1990\n",
        "resource.h IDC_RECONNECTSECS",
    )


def comment_rc_block(t, header, func, label):
    m = re.search(r"^" + header + r".*?^END", t, re.S | re.M)
    if not m:
        fail("altacast.rc: block not found: " + label)
    return t[: m.start()] + func(m.group(0)) + t[m.end():]


def comment_rc(t):
    if "IDC_ENCCOMMENT" in t:
        return t

    def config_dlg(b):
        b = sub_once(b, r"(IDD_CONFIG DIALOGEX \d+, \d+, \d+, )(\d+)", comment_grow, "rc IDD_CONFIG height")
        b = sub_once(b, r'(IDC_TAB1,"SysTabControl32",WS_TABSTOP,\d+,\d+,\d+,)(\d+)', comment_grow, "rc tab height")
        b = sub_once(b, r'(DEFPUSHBUTTON\s+"OK",IDOK,\d+,)(\d+)', comment_grow, "rc OK button")
        b = sub_once(b, r'(PUSHBUTTON\s+"Cancel",IDCANCEL,\d+,)(\d+)', comment_grow, "rc Cancel button")
        return b

    def basic_page(b):
        b = sub_once(b, r"(IDD_PROPPAGE_LARGE DIALOGEX \d+, \d+, \d+, )(\d+)", comment_grow, "rc page height")
        b = sub_once(b, r'(GROUPBOX\s+"General Settings",IDC_STATIC,\d+,\d+,\d+,)(\d+)', comment_grow, "rc group height")
        m = re.search(r"EDITTEXT\s+IDC_RECONNECTSECS,\d+,(\d+),\d+,14[^\n]*\n", b)
        if not m:
            fail("altacast.rc: IDC_RECONNECTSECS not found")
        y = int(m.group(1)) + COMMENT_GROW
        b = b[: m.end()] + "    EDITTEXT        IDC_ENCCOMMENT,112,%d,%d,14,ES_AUTOHSCROLL\n" % (y, COMMENT_W) + b[m.end():]
        return after(
            b,
            r'    RTEXT\s+"Reconnect Seconds",IDC_STATIC,\d+,\d+,\d+,8\n',
            '    RTEXT           "Comment",IDC_STATIC,33,%d,70,8\n' % (y + 2),
            "rc Reconnect label",
        )

    t = comment_rc_block(t, r"IDD_CONFIG DIALOGEX", config_dlg, "IDD_CONFIG")
    t = comment_rc_block(t, r"IDD_PROPPAGE_LARGE DIALOGEX", basic_page, "IDD_PROPPAGE_LARGE")
    return t


def comment_bs_h(t):
    if "m_EncComment" in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)CString([ \t]+)m_ReconnectSecs;\n",
        lambda m: m.group(0) + m.group(1) + "CString" + m.group(2) + "m_EncComment;   // " + MARK_COMMENT + "\n",
        "BasicSettings.h m_ReconnectSecs",
    )


def comment_bs_cpp(t):
    if MARK_COMMENT in t:
        return t
    t = after(
        t,
        r'\tm_ReconnectSecs = _T\(""\);\n',
        '\tm_EncComment = _T("");   /* ' + MARK_COMMENT + ' */\n',
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
        "\t/* " + MARK_COMMENT + ": at most 200 bytes (100 full-width characters) */\n"
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
        "\t/* " + MARK_COMMENT + ": locked while connected, like the other fields */\n"
        "\t{\n"
        "\t\tCWnd *wc = GetDlgItem(IDC_ENCCOMMENT);\n"
        "\t\tif (wc != NULL) wc->EnableWindow(m_LockEncoder ? FALSE : TRUE);\n"
        "\t}\n",
        "BasicSettings.cpp ApplyEncoderLock",
    )
    return t


def comment_config(t):
    if "gEncComment" in t:
        return t
    t = sub_once(
        t,
        r"([ \t]*)basicSettings->m_ReconnectSecs = buf;\n",
        lambda m: m.group(0) + m.group(1) + "basicSettings->m_EncComment = g->gEncComment;   /* " + MARK_COMMENT + " */\n",
        "Config.cpp dialog <- globals",
    )
    t = sub_once(
        t,
        r"([ \t]*)g->gReconnectSec = atoi\(LPCSTR\(basicSettings->m_ReconnectSecs\)\);\n",
        lambda m: m.group(0)
        + m.group(1) + "strncpy(g->gEncComment, LPCSTR(basicSettings->m_EncComment), sizeof(g->gEncComment) - 1);   /* " + MARK_COMMENT + " */\n"
        + m.group(1) + "g->gEncComment[sizeof(g->gEncComment) - 1] = '\\000';\n",
        "Config.cpp globals <- dialog",
    )
    return t


def comment_lib_h(t):
    if "gEncComment" in t:
        return t
    return after(
        t,
        r"\tchar_t\t\tgServGenre\[100\];\n",
        "\tchar_t\t\tgEncComment[256];\t/* " + MARK_COMMENT + ": personal note, never sent to the server */\n",
        "libaltacast.h gServGenre",
    )


def comment_lib_cpp(t):
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


def comment_main(t):
    if MARK_COMMENT in t:
        return t
    t = sub_once(
        t,
        r"#define LIST_NUMCOLS 5\n",
        lambda m: "#define LIST_NUMCOLS 6   /* " + MARK_COMMENT + ": 5 -> 6 (Comment column) */\n",
        "MainWindow.cpp LIST_NUMCOLS",
    )
    t = after(
        t,
        r"\tm_Encoders\.SetColumnWidth\(4, 130\);\n",
        '\tm_Encoders.InsertColumn(5, "Comment");   /* ' + MARK_COMMENT + ' */\n'
        "\tm_Encoders.SetColumnWidth(5, 200);\n",
        "MainWindow.cpp Comment column",
    )
    t = sub_once(
        t,
        r"\tif \(ok && n == LIST_NUMCOLS && order\[0\] == 0\) \{\n",
        lambda m: "\t/* " + MARK_COMMENT + ": a column order saved with one column less stays valid (the new column goes last) */\n"
        "\tif (ok && n == LIST_NUMCOLS - 1 && !used[LIST_NUMCOLS - 1]) {\n"
        "\t\torder[n++] = LIST_NUMCOLS - 1;\n"
        "\t}\n"
        + m.group(0),
        "MainWindow.cpp column order",
    )
    t = sub_once(
        t,
        r"\t\tif \(m_Encoders\.GetCheck\(i\) != want\) \{\n",
        lambda m: "\t\tif (m_Encoders.GetItemText(i, 5) != g[i]->gEncComment) {   /* " + MARK_COMMENT + " */\n"
        "\t\t\tm_Encoders.SetItemText(i, 5, g[i]->gEncComment);\n"
        "\t\t}\n"
        + m.group(0),
        "MainWindow.cpp UpdateExtraColumns",
    )
    return t


# ----------------------------------------------------------------------
# apply
# ----------------------------------------------------------------------

patch_file("resource.h", comment_resource)
patch_file("altacast.rc", lambda t: comment_rc(fix_resize_rc(t)))
patch_file("BasicSettings.h", comment_bs_h)
patch_file("BasicSettings.cpp", comment_bs_cpp)
patch_file("Config.cpp", comment_config)
patch_file("libaltacast/libaltacast.h", lambda t: comment_lib_h(fix_colw_libheader(t)))
patch_file("libaltacast/libaltacast.cpp", lambda t: comment_lib_cpp(fix_colw_lib(t)))
patch_file("MainWindow.h", lambda t: fix_colw_header(fix_time_header(t)))
patch_file("MainWindow.cpp", lambda t: comment_main(fix_rec_main(fix_silence_main(fix_colw_cpp(fix_time_cpp(t))))))
patch_file("FlexMeters.cpp", lambda t: fix_silence_cpp(fix_meter_cpp(t)))
patch_file("FlexMeters.h", lambda t: fix_silence_h(fix_meter_h(t)))
print(TAG + ": done")
