@echo off
rem Master Looter build: MSVC Build Tools 2022 + the CMake and Ninja they bundle.
rem   build.bat             configure and build Release into build\, stage dist\
rem   build.bat clean       wipe build\ first
rem   build.bat tag NAME    the same, but the plugin reports itself as
rem                         v1.6.16-NAME in its log and in the menu, so a build
rem                         handed to one reporter cannot be read as the release.
rem                         Building again without "tag" clears it.
rem                         "clean" may come first: build.bat clean tag NAME.
rem
rem   Anything else is refused. This used to take the first word as the tag,
rem   which turned a mistyped argument into a mislabelled binary with no error.
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
set "NINJA=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
set "HERE=%~dp0"

set "WANT=%~1"
set "NAME=%~2"
set "EXTRA=%~3"
if /i not "%WANT%"=="clean" goto :parsetag
if exist "%HERE%build" rmdir /s /q "%HERE%build"
set "WANT=%~2"
set "NAME=%~3"
set "EXTRA=%~4"

:parsetag
set "TAG="
if "%WANT%"=="" goto :ready
if /i "%WANT%"=="tag" goto :havetag
echo Unknown argument "%WANT%".
echo   build.bat             release build
echo   build.bat clean       wipe build\ first
echo   build.bat tag NAME    build that reports itself as v^<version^>-NAME
exit /b 2

:havetag
if not "%NAME%"=="" goto :havename
echo build.bat tag needs a name, for example: build.bat tag equipcheck
exit /b 2

:havename
if "%EXTRA%"=="" goto :settag
echo Unexpected argument "%EXTRA%" after the tag name.
echo   build.bat tag NAME    one name, nothing after it
exit /b 2

:settag
set "TAG=-%NAME%"

:ready

call "%VCVARS%" >nul 2>&1
if errorlevel 1 (
  echo vcvars64.bat not found at "%VCVARS%"
  exit /b 1
)

"%CMAKE%" -S "%HERE%." -B "%HERE%build" -G Ninja -DCMAKE_MAKE_PROGRAM="%NINJA%" -DCMAKE_BUILD_TYPE=Release -DML_BUILD_TAG="%TAG%"
if errorlevel 1 exit /b 1
"%CMAKE%" --build "%HERE%build"
if errorlevel 1 exit /b 1
echo.
echo staged in "%HERE%dist"
endlocal
