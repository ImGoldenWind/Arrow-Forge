@ECHO ---------------------------------------------------------------------
@ECHO Convert To USM.VP9 Ver.1.3
@ECHO Copyright (c) 2018 CRI Middleware Co., Ltd.
@ECHO ---------------------------------------------------------------------
@ECHO.

@REM =====================================================================
@IF "%1"=="" @(
@GOTO LBL_HELP
)
@IF NOT EXIST "%1\*" @(
@ECHO -- エラー --
@ECHO 指定したパスがフォルダーでないか、ファイルが含まれていません。
@ECHO.
@GOTO LBL_HELP
)

@REM =====================================================================
@REM 下記 ECHO を ON にすることでコマンドを確認できます。
@ECHO OFF

@REM =====================================================================
@REM 各種設定
@SET TARGETEXT=.usm
@SET SOFDEC2ENC=%~dp0sofdec2enc.exe
@SET SOFDEC2ENCVP9=%~dp0sofdec2encVP9.exe
@SET USF2CHUNK=%~dp0usf2chunk64.dll
@SET REMOVE_TEMPORARY=True
@SET MULTIPASS_ENABLED=True
@SET RESULT_LOG=%~dpn0.tsv

@REM 品質の設定：大きいほど画質向上（ファイルサイズ増大）。
@SET VP9_QUALITY=1.5

@ECHO 入力ファイル名^	出力ファイル名^	入力ファイルサイズ^	出力ファイルサイズ^	圧縮率 > %RESULT_LOG%

@REM =====================================================================
@REM ツールの存在チェック
@IF NOT EXIST "%SOFDEC2ENC%" @(
@ECHO 下記のツールが見つかりません。
@ECHO %SOFDEC2ENC%
@ECHO.
@GOTO LBL_END
)
@IF NOT EXIST "%SOFDEC2ENCVP9%" @(
@ECHO 下記のツールが見つかりません。
@ECHO %SOFDEC2ENCVP9%
@ECHO.
@GOTO LBL_END
)
@IF NOT EXIST "%USF2CHUNK%" @(
@ECHO 下記のツールが見つかりません。
@ECHO %USF2CHUNK%
@ECHO.
@GOTO LBL_END
)

@REM =====================================================================
@REM -----------------------------------------
@ECHO -- 出力モード選択 --
@ECHO サイズを削減したファイルの扱い方を下記から選択してください。
@ECHO.
@ECHO [1] 名前変更モード
@ECHO 　　※オリジナルファイルは「＊＊＊＊.usm」として残します。
@ECHO 　　※削減ファイルは「＊＊＊＊.vp9.usm」とします。
@ECHO [2] 上書きモード
@ECHO 　　※オリジナルファイルは「＊＊＊＊.original.usm」として残します。
@ECHO 　　※削減ファイルは「＊＊＊＊.usm」とします。
@ECHO [3] 指定フォルダーモード
@ECHO 　　※指定したフォルダーに出力します。
@ECHO 　　※出力ファイル名は入力ファイル名と同じになります。
@ECHO 　　※同名のファイルが存在した場合、上書きします。
@ECHO.
@SET /P OUTPUT_MODE="モードを「1」～「3」で指定→ "

@REM -----------------------------------------
@ECHO -- リサイズモード選択 --
@ECHO ビデオの解像度をリサイズしますか？
@ECHO.
@ECHO [1] リサイズなし
@ECHO 　　※入力解像度と同じ解像度で出力します。
@ECHO [2] 1280×720　（横長）
@ECHO 　　※すべての動画を1280×720で出力します。
@ECHO [3] 720×1280　（縦長）
@ECHO 　　※すべての動画を720×1280で出力します。
@ECHO [4] カスタム
@ECHO 　　※自分で指定します。
@ECHO.
@SET /P RESIZE_MODE="モードを「1」～「4」で指定→ "
@SET RESIZE_WIDTH=0
@SET RESIZE_HEIGHT=0
@IF "%RESIZE_MODE%"=="1" @(
@GOTO LBL_MODE_JUMP
)
@IF "%RESIZE_MODE%"=="2" @(
@SET RESIZE_WIDTH=1280
@SET RESIZE_HEIGHT=720
@GOTO LBL_MODE_JUMP
)
@IF "%RESIZE_MODE%"=="3" @(
@SET RESIZE_WIDTH=720
@SET RESIZE_HEIGHT=1280
@GOTO LBL_MODE_JUMP
)
@IF "%RESIZE_MODE%"=="4" @(
@SET /P RESIZE_WIDTH="幅　を指定→ "
@SET /P RESIZE_HEIGHT="高さを指定→ "
@GOTO LBL_MODE_JUMP
)
@ECHO 入力したモード「%RESIZE_MODE%」は存在しません。
@ECHO.
@GOTO LBL_END

@REM -----------------------------------------
:LBL_MODE_JUMP
@SET CMD_RESIZE_OPTION=
@SET /A RESIZE_PIXELS=%RESIZE_WIDTH%*%RESIZE_HEIGHT%
@IF %RESIZE_PIXELS% GTR 0 @(
@SET CMD_RESIZE_OPTION=-resize=%RESIZE_WIDTH%,%RESIZE_HEIGHT%
)

@IF "%OUTPUT_MODE%"=="1" @GOTO LBL_START_MODE1
@IF "%OUTPUT_MODE%"=="2" @GOTO LBL_START_MODE2
@IF "%OUTPUT_MODE%"=="3" @GOTO LBL_START_MODE3

@ECHO 入力したモード「%OUTPUT_MODE%」は存在しません。
@ECHO.
@GOTO LBL_END


@REM -----------------------------------------
@REM [1] 名前変更モード
:LBL_START_MODE1
@FOR /R "%~1" %%f IN ("*%TARGETEXT%") DO @(
	@CALL :LBL_SUB_TRANSCODE "%%~f" "%%~dpnf.vp9.usm"
)
@GOTO LBL_END

@REM -----------------------------------------
@REM [2] 上書きモード
:LBL_START_MODE2
@FOR /R "%~1" %%f IN ("*%TARGETEXT%") DO @(
	@REM 後で上書き（リネームします）
	@CALL :LBL_SUB_TRANSCODE "%%~f" "%%~dpnf.vp9.usm"
)
@GOTO LBL_END

@REM -----------------------------------------
@REM [3] 指定フォルダーモード
:LBL_START_MODE3
@SET /P OUTPUT_DIR="出力フォルダーを指定→ "
@IF NOT EXIST %OUTPUT_DIR% mkdir "%OUTPUT_DIR%"
@FOR /R "%~1" %%f IN ("*%TARGETEXT%") DO @(
	@CALL :LBL_SUB_TRANSCODE "%%~f" "%OUTPUT_DIR%\%%~nxf"
)
@GOTO LBL_END

@REM =====================================================================
@REM サブプログラム
:LBL_SUB_TRANSCODE
@SET PATH_USM_SRC=%~1
@SET PATH_USM_VP9=%~2
@SET PATH_IVF=%~dpn2.ivf
@SET PATH_ALPHA_MP4=%~dpn2.alpha.mp4
@SET PATH_ALPHA_SFV=%~dpn2.alpha.sfv
@SET PATH_00_SFA=%~dpn1#00.hca
@SET PATH_SUBTITLE=%~dp1*_sbt_??.txt
@SET PATH_AUDIOTRACK=%~dp2%~n1#??.hca
@SET PATH_CUE=%~dpn2_cue.txt
@SET PATH_MULTIPASS_LOG=%~dpn2.ivf.multipass.log
@SET PATH_LOG=%~dpn2.tty.txt
@REM -----------------------------------------
@REM 下記はこのバッチで作ったであろう処理済みファイルを再処理しないため。
@IF "%PATH_USM_SRC:~-8%"==".vp9.usm" @(
@GOTO LBL_SUB_TRANSCODE_END
)
@IF "%PATH_USM_SRC:~-13%"==".original.usm" @(
@GOTO LBL_SUB_TRANSCODE_END
)

@ECHO -----------------------------------------
@ECHO %PATH_USM_SRC%
@ECHO %DATE% %TIME% > "%PATH_LOG%" 2>&1

@REM -----------------------------------------
@ECHO Transcode to VP9
@ECHO Transcode to VP9 at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
@REM ※出力音声ファイル名を現在指定できません。暗黙の命名規則に従って取り扱います。
@IF "%MULTIPASS_ENABLED%"=="True" @(
@SET CMD_MULTIPATH=-multi_pass=1
)
CALL "%SOFDEC2ENCVP9%" -verbosity=detailed -in="%PATH_USM_SRC%" -output_video="%PATH_IVF%" -outcue="%PATH_CUE%" -acodec=hca -hca_quality=4 -input_audio#00="%PATH_USM_SRC%" -vcodec=vp9 -vpx_speed=4 %CMD_MULTIPATH% %CMD_RESIZE_OPTION% -cr4vbps=%VP9_QUALITY% -vfullrange=off >> "%PATH_LOG%" 2>>&1
@IF NOT "%ERRORLEVEL%"=="0" @(
@ECHO エラー：VP9 IVF ファイルを出力できませんでした（１パス目）
@GOTO LBL_SUB_TRANSCODE_ERROR_END
)

@REM -----------------------------------------
@ECHO Parse Information
@ECHO Parse Information at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
@FOR /F "DELIMS=" %%A IN ('findstr "Resolution" "%PATH_LOG%\"') DO @SET CMD_DISP_SIZE=%%A
@FOR /F "DELIMS=" %%A IN ("%CMD_DISP_SIZE: | - Resolution : =-usm_disp_width=%") DO @SET CMD_DISP_SIZE=%%A
@FOR /F "DELIMS=" %%A IN ("%CMD_DISP_SIZE:x =-usm_disp_height=%") DO @SET CMD_DISP_SIZE=%%A
@FOR /F "TOKENS=1,2 DELIMS=:" %%A IN ('findstr /C:"Alpha Type" "%PATH_LOG%"') DO @SET ALPHA_TYPE=%%B
@FOR /F "TOKENS=1,2 DELIMS=:" %%A IN ('findstr /C:"Alpha Bitrate" "%PATH_LOG%"') DO @SET ALPHA_KBPS=%%B
@SET ALPHA_TYPE=%ALPHA_TYPE:~1%
@SET /A ALPHA_BPS=%ALPHA_KBPS:~0,-6% * 1000

@REM -----------------------------------------
@IF "%MULTIPASS_ENABLED%"=="True" @(
@ECHO Transcode to VP9 [2-pass]
@ECHO Transcode to VP9 [2-pass] at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
CALL "%SOFDEC2ENCVP9%" -in="%PATH_USM_SRC%" -output_video="%PATH_IVF%" -vcodec=vp9 -vpx_speed=1 -multi_pass=2 %CMD_RESIZE_OPTION% -cr4vbps=%VP9_QUALITY% -vfullrange=off >> "%PATH_LOG%" 2>>&1
)
@IF NOT "%ERRORLEVEL%"=="0" @(
@ECHO エラー：VP9 IVF ファイルを出力できませんでした（２パス目）
@GOTO LBL_SUB_TRANSCODE_ERROR_END
)

@REM -----------------------------------------
@IF "%ALPHA_TYPE%"=="Alpha" @(
@ECHO Transcode Alpha
@ECHO Transcode Alpha at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
CALL "%SOFDEC2ENCVP9%" -in="%PATH_USM_SRC%" -out="%PATH_ALPHA_MP4%" %CMD_RESIZE_OPTION% -y_is_alpha=on -vfullrange=on >> "%PATH_LOG%" 2>>&1
CALL "%SOFDEC2ENC%" -video00="%PATH_ALPHA_MP4%" -out="%PATH_ALPHA_SFV%" -bitrate=%ALPHA_BPS% -videoonly -y2alpha >> "%PATH_LOG%" 2>>&1
)
@IF NOT "%ERRORLEVEL%"=="0" @(
@ECHO エラー：Alpha SFV ファイルを出力できませんでした
@GOTO LBL_SUB_TRANSCODE_ERROR_END
)

@REM -----------------------------------------
@ECHO Demultiplex Subtitle at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
CALL "%USF2CHUNK%" -in="%PATH_USM_SRC%" -outputsubtitle >> "%PATH_LOG%" 2>>&1

@REM -----------------------------------------
@ECHO Multiplex
@ECHO Multiplex at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
@SET CMD_INPUT_VIDEO=-input_video="%PATH_IVF%"
@SET CMD_INPUT_ALPHA=
@IF EXIST %PATH_ALPHA_SFV% @SET CMD_INPUT_ALPHA=-input_alpha="%PATH_ALPHA_SFV%"
@SET CMD_INPUT_AUDIOTRACK=
@FOR %%f IN ("%PATH_AUDIOTRACK%") DO @(
  @CALL :LBL_AUDIOTRACK  %%f
)
@SET CMD_INPUT_SUBTITLE=
@FOR %%f IN ("%PATH_SUBTITLE%") DO @(
  @CALL :LBL_SUBTITLE  %%f
)
@SET CMD_INPUT_CUEPOINT=
@IF EXIST %PATH_CUE% @(
@SET CMD_INPUT_CUEPOINT=-icue="%PATH_CUE%"
)
CALL "%SOFDEC2ENCVP9%" -out="%PATH_USM_VP9%" %CMD_INPUT_VIDEO% %CMD_INPUT_ALPHA% %CMD_INPUT_AUDIOTRACK% %CMD_INPUT_SUBTITLE% %CMD_DISP_SIZE% %CMD_INPUT_CUEPOINT% >> "%PATH_LOG%" 2>>&1
@IF NOT "%ERRORLEVEL%"=="0" @(
@ECHO エラー：USM VP9 ファイルを出力できませんでした
@GOTO LBL_SUB_TRANSCODE_ERROR_END
)

@REM -----------------------------------------
@REM Calculate Input/Output Size
@FOR %%i IN (%PATH_USM_SRC%) DO @SET PATH_USM_SRC_SIZE=%%~zi
@FOR %%i IN (%PATH_USM_VP9%) DO @SET PATH_USM_VP9_SIZE=%%~zi

@REM -----------------------------------------
@IF "%OUTPUT_MODE%"=="2" @(
@ECHO Rename Original File and Rename Output File
MOVE /Y "%PATH_USM_SRC%" "%~dpn1.original%~x1"
MOVE /Y "%PATH_USM_VP9%" "%PATH_USM_SRC%"
)

@REM -----------------------------------------
@IF "%REMOVE_TEMPORARY%"=="True" @(
@ECHO Remove Temporary Files
@ECHO Remove Temporary Files at %DATE% %TIME% >> "%PATH_LOG%" 2>>&1
@IF EXIST %PATH_IVF%           DEL %PATH_IVF%
@IF EXIST %PATH_ALPHA_MP4%     DEL %PATH_ALPHA_MP4%
@IF EXIST %PATH_ALPHA_SFV%     DEL %PATH_ALPHA_SFV%
@IF EXIST %PATH_CUE%           DEL %PATH_CUE%
@IF EXIST %PATH_MULTIPASS_LOG% DEL %PATH_MULTIPASS_LOG%
@IF EXIST %PATH_LOG%           DEL %PATH_LOG%
@FOR %%f IN ("%PATH_SUBTITLE%") DO @(
  DEL %%f
)
@FOR %%f IN ("%PATH_AUDIOTRACK%") DO @(
  DEL %%f
)
)

@REM -----------------------------------------
@ECHO Output Statistics
@SET /A SIZE_PERCENTAGE=%PATH_USM_VP9_SIZE%*100/%PATH_USM_SRC_SIZE%
@ECHO %PATH_USM_SRC%^	%PATH_USM_VP9%^	%PATH_USM_SRC_SIZE%^	%PATH_USM_VP9_SIZE%^	%SIZE_PERCENTAGE% >> %RESULT_LOG%

@REM -----------------------------------------
:LBL_SUB_TRANSCODE_END
@ECHO.
@EXIT /B 0

@REM -----------------------------------------
:LBL_SUBTITLE
@REM 字幕ファイル名からチャンネル番号を取得してオプションを設定する
@SET local_subtitle=%1
@SET CMD_INPUT_SUBTITLE=%CMD_INPUT_SUBTITLE% -subtitle#%local_subtitle:~-6,2%="%1"
@EXIT /B 0

@REM -----------------------------------------
:LBL_AUDIOTRACK
@REM オーディオファイルからトラック番号を取得してオプションを設定する
@SET local_audiotrack=%1
@SET CMD_INPUT_AUDIOTRACK=%CMD_INPUT_AUDIOTRACK% -ia#%local_audiotrack:~-6,2%="%1"
@EXIT /B 0


@REM -----------------------------------------
:LBL_SUB_TRANSCODE_ERROR_END
@FOR %%i IN (%PATH_USM_SRC%) DO @SET PATH_USM_SRC_SIZE=%%~zi
@ECHO %PATH_USM_SRC%^	%PATH_USM_VP9%^	%PATH_USM_SRC_SIZE%^	0^	0 >> %RESULT_LOG%
@ECHO.
@EXIT /B 1

@REM =====================================================================
:LBL_HELP
@ECHO -- 使い方 --
@ECHO 変換したい USM ファイルを含んでいるフォルダーをエクスプローラー上で
@ECHO ドラッグして、このプログラムにドロップしてください。
@ECHO.
@ECHO このプログラムは指定されたフォルダー内の USM ファイルを
@ECHO すべて USM.VP9 ファイルに変換してデータサイズを削減します。
@ECHO 変換したファイルはすべて入力したファイル内に出力します。
@ECHO.
@ECHO また変換結果を TSV 形式で出力しますので、内容をコピーして
@ECHO Microsoft Excel などに貼り付けることで削減量を確認することもできます。
@ECHO.
@ECHO エラーが発生した場合は、当該ファイルの出力サイズが 0 で記録されます。
@ECHO.

@REM =====================================================================
:LBL_END
@ECHO.
@PAUSE
