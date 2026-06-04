; Sentinel AI NSIS hooks — register uninstall, mark first-run wizard
!macro customInstall
  CreateDirectory "$APPDATA\SentinelAI"
  FileOpen $0 "$APPDATA\SentinelAI\install.flag" w
  FileWrite $0 "installed"
  FileClose $0
!macroend

!macro customUnInstall
  Delete "$APPDATA\SentinelAI\install.flag"
!macroend
