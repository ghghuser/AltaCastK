#!/usr/bin/env python3
"""
altacast_fixes3.py - third batch of AltaCast fixes (applied at build time).

  1. Level meter lit up completely during silence
       log10(0) = -infinity was converted to int (undefined, gives INT_MIN) and then
       multiplied by the meter width in the drawing code. The result overflowed, and
       with an even meter width the whole bar was drawn as lit.
       Now: silence = 0, the value is limited to 0..60, the drawing code clamps again,
       and the 'peak' member (never set in AltaCast) starts at 0.
  2. Live Recording: volume slider / input list with speakers (loopback devices)
       - Loopback ("speakers") devices have no input list and no input volume control,
         so the slider did nothing. Now the slider falls back to a software volume
         (0..100 %) applied to the recorded samples.
         The same fallback is used when an input has no volume control.
       - At start-up the input list was read from recording device 0 even when another
         recording device was selected; now it is read from the selected device.
       - A status line tells when the software volume is used.

Usage:  python tools/altacast_fixes3.py trunk/AltaCast/src
Idempotent (MARK_* strings), fails loudly if an anchor is missing.
"""
import re
import sys
from pathlib import Path

TAG = "altacast_fixes3"


def fail(msg):
    print(TAG + ": ERROR: " + msg)
    sys.exit(1)


if len(sys.argv) != 2:
    fail("usage: altacast_fixes3.py <source dir>")
SRC = Path(sys.argv[1])
if not SRC.is_dir():
    fail("source dir not found: " + str(SRC))


def sub_once(text, pattern, repl, label, flags=0):
    new, n = re.subn(pattern, repl, text, flags=flags)
    if n != 1:
        fail("%s: expected exactly 1 match, found %d" % (label, n))
    return new


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


# ------------------------------------------------------------ 1. level meter
MARK_METER = TAG + ": meter"


def fix_meter_main(t):
    if MARK_METER in t:
        return t
    new = (
        "/* " + MARK_METER + ": silence gives log10(0) = -inf; keep the meter values in 0..60 */\n"
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


def fix_meter_cpp(t):
    if MARK_METER in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)if \(!y_size\) return ;\n",
        lambda m: m.group(0)
        + m.group(1) + "/* " + MARK_METER + ": clamp, so that the width * value arithmetic cannot overflow */\n"
        + m.group(1) + "if (value < 0) value = 0;\n"
        + m.group(1) + "if (value > MAX_VALUE) value = MAX_VALUE;\n"
        + m.group(1) + "if (peak < 0) peak = 0;\n"
        + m.group(1) + "if (peak > MAX_VALUE) peak = MAX_VALUE;\n",
        "FlexMeters.cpp drawmeter_horizontal",
    )


def fix_meter_h(t):
    if MARK_METER in t:
        return t
    return sub_once(
        t,
        r"([ \t]*)value = 100;\n",
        lambda m: m.group(0) + m.group(1) + "peak = 0;   // " + MARK_METER + "\n",
        "FlexMeters.h default values",
    )


# ------------------------------------------------------------ 2. live recording volume
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


patch_file("MainWindow.cpp", lambda t: fix_rec_main(fix_meter_main(t)))
patch_file("FlexMeters.cpp", fix_meter_cpp)
patch_file("FlexMeters.h", fix_meter_h)
print(TAG + ": done")
