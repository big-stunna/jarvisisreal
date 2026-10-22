# J.A.R.V.I.S. on macOS

```bash
git clone https://github.com/big-stunna/jarvisisreal.git ~/jarvis
cd ~/jarvis && bash mac/install.sh
```

Needs [Homebrew](https://brew.sh) and a free Groq key from console.groq.com
(use your own account: limits are shared per account).

| Action | How |
|---|---|
| Voice popup | say **"Hey Jarvis"**, or `Cmd+Shift+V` |
| Chat window | `Cmd+Shift+J` |
| Wake word on/off | `Cmd+Alt+J` |
| Close popup | Esc, or say "thanks" / "close" |

Local commands (no AI, instant): "lock", "volume 50", "mute", "brightness 30",
"open safari", "take a screenshot".

## Permissions (System Settings → Privacy & Security)

- **Microphone**: Terminal and python3.12
- **Accessibility**: skhd (hotkeys)
- **Automation**: python3.12 → Music/Spotify (pauses media when locking)

"Lock" turns the display off; for it to actually lock, set
Lock Screen → *Require password after screen saver begins or display is turned off* → **Immediately**.

## Troubleshooting

- Logs: `~/Library/Logs/jarvis.log`, popup steps in `~/.local/share/jarvis/popup.log`
- Restart the service: `launchctl kickstart -k gui/$(id -u)/com.jarvis.daemon`
- Wake word never fires: the background service may lack mic permission —
  run `jarvis start --no-hud` once from Terminal and accept the prompt.
- Uninstall: `launchctl bootout gui/$(id -u)/com.jarvis.daemon; rm ~/Library/LaunchAgents/com.jarvis.daemon.plist`
