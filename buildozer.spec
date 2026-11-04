[app]
title = Dhan OI Scanner
package.name = dhanoiscanner
package.domain = org.oiscanner
source.dir = .
source.include_exts = py
version = 1.0.0
requirements = python3,kivy==2.3.0,requests,urllib3,chardet,idna,certifi,charset-normalizer,websocket-client,plyer,pyjnius,android
orientation = all
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,POST_NOTIFICATIONS,VIBRATE,WAKE_LOCK
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 1
warn_on_root = 1
