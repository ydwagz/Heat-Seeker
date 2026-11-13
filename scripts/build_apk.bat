@echo off
rem Builds the Android APK of Heat Seeker. Double-click it, or run it from a terminal.
rem The finished APK ends up in Application\build\apk\
rem Extra options are passed to flet, e.g.  build_apk.bat --arch arm64-v8a  (smaller, 64-bit phones only)
rem
rem Flutter, Java, the Android SDK and the build caches take 8-10 GB. They are kept in one folder,
rem E:\FletTools by default; to use another one, set FLET_TOOLS first, e.g.  set FLET_TOOLS=D:\FletTools

if not defined FLET_TOOLS set "FLET_TOOLS=E:\FletTools"
set "PROJECT=%~dp0.."

set "ANDROID_HOME=%FLET_TOOLS%\AndroidSdk"
set "ANDROID_SDK_ROOT=%FLET_TOOLS%\AndroidSdk"
set "GRADLE_USER_HOME=%FLET_TOOLS%\gradle"
set "PUB_CACHE=%FLET_TOOLS%\PubCache"
set "TEMP=%FLET_TOOLS%\tmp"
set "TMP=%FLET_TOOLS%\tmp"
rem Use the Java that Flet installed there, if any (otherwise Flet installs one)
for /d %%J in ("%FLET_TOOLS%\java\*") do set "JAVA_HOME=%%J"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%ANDROID_HOME%" mkdir "%ANDROID_HOME%"
if not exist "%TEMP%" mkdir "%TEMP%"

rem Behind antivirus HTTPS scanning, Java and pip only trust the scanner's certificate if they use
rem the Windows certificate store: Java can do that directly; for pip, export the store to a file.
set "JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStoreType=Windows-ROOT"
set "CERTS=%FLET_TOOLS%\windows-roots.pem"
"%PROJECT%\env\Scripts\python.exe" -c "import ssl,certifi;c=[ssl.DER_cert_to_PEM_cert(d) for s in ('ROOT','CA') for d,e,t in ssl.enum_certificates(s) if e=='x509_asn'];open(r'%CERTS%','w').write(open(certifi.where()).read()+''.join(c))"
set "PIP_CERT=%CERTS%"
set "REQUESTS_CA_BUNDLE=%CERTS%"
set "SSL_CERT_FILE=%CERTS%"

cd /d "%PROJECT%\Application"
"%PROJECT%\env\Scripts\flet.exe" build apk --yes %*
