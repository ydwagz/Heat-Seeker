@echo off
rem Builds the Android APK of Heat Seeker. Run it from anywhere: double-click or "build_apk.bat".
rem All build tools and caches stay on E: in E:\FletTools, so drive C: doesn't fill up.
rem The finished APK ends up in Application\build\apk\
rem Extra options are passed to flet, e.g. "build_apk.bat --verbose".

set "TOOLS=E:\FletTools"
set "ANDROID_HOME=%TOOLS%\AndroidSdk"
set "ANDROID_SDK_ROOT=%TOOLS%\AndroidSdk"
set "JAVA_HOME=%TOOLS%\java\17.0.13+11"
set "GRADLE_USER_HOME=%TOOLS%\gradle"
set "PUB_CACHE=%TOOLS%\PubCache"
set "TEMP=%TOOLS%\tmp"
set "TMP=%TOOLS%\tmp"
rem Java (Android SDK manager, Gradle) trusts the Windows certificate store, like truststore does
rem for Python, so downloads work behind the antivirus's HTTPS scanning.
set "JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStoreType=Windows-ROOT"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%ANDROID_HOME%" mkdir "%ANDROID_HOME%"
if not exist "%TEMP%" mkdir "%TEMP%"

rem pip (which downloads the app's Python packages) doesn't use the Windows certificate store,
rem so export the certificates Windows trusts (antivirus included) to a file and point pip at it.
set "CERTS=%TOOLS%\windows-roots.pem"
"%~dp0env\Scripts\python.exe" -c "import ssl,certifi;c=[ssl.DER_cert_to_PEM_cert(d) for s in ('ROOT','CA') for d,e,t in ssl.enum_certificates(s) if e=='x509_asn'];open(r'%CERTS%','w').write(open(certifi.where()).read()+''.join(c))"
set "PIP_CERT=%CERTS%"
set "REQUESTS_CA_BUNDLE=%CERTS%"
set "SSL_CERT_FILE=%CERTS%"

cd /d "%~dp0Application"
"%~dp0env\Scripts\flet.exe" build apk --yes %*
