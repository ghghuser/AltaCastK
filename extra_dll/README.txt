extra_dll フォルダ
ここに置いた DLL は、ビルド時に配布物 (artifact) へコピーされます
(trunk/external/lib の同じ名前の DLL は上書きされます)。

置くファイル (すべて 32bit / x86 版)
 ・bass.dll         BASS (un4seen) https://www.un4seen.com/
                    非商用は無料。再販・サブライセンスは不可。
                    入手した zip の bass.txt もここに置く
 ・lame_enc.dll     LAME (LGPL) https://lame.sourceforge.io/
 ・libmpg123-0.dll  mpg123 (LGPL 2.1) https://mpg123.org/
                    LAME 4.0 の lame_enc.dll に必要
 lame_enc.dll と libmpg123-0.dll の入手元: RareWares の LAME bundle
   https://www.rarewares.org/mp3-lame-bundle.php (lame-4.0-x86.zip)
   ファイル名は変えない

ソースコード (LGPL)
 ・LAME   https://sourceforge.net/projects/lame/files/lame/
 ・mpg123 https://sourceforge.net/projects/mpg123/files/mpg123/
 ・DLL と同じ版のソースの圧縮ファイルを extra_dll/source/ に置くと、より確実

ライセンス文
 ・LICENSE_LAME_LGPL-2.0.txt
 ・LICENSE_libmpg123_LGPL-2.1.txt
 ・DLL は変更せず、入手したまま置いています

置かないファイル (再配布の許可を確認できないもの)
 ・enc_aacplus.dll, enc_fhgaac.dll, nsutil.dll (Winamp の部品)
 ・FHGAAC を使う場合は、手元で exe と同じ場所に置く (libmp4v2.dll も)
