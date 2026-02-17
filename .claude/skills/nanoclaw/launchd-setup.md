# launchd Service for Ragling

Keep ragling running across reboots.

## Create the Plist

Create `~/Library/LaunchAgents/com.ragling.serve.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ragling.serve</string>

    <key>ProgramArguments</key>
    <array>
        <string>UV_PATH</string>
        <string>run</string>
        <string>--directory</string>
        <string>RAGLING_DIR</string>
        <string>ragling</string>
        <string>serve</string>
        <string>--sse</string>
        <string>--no-stdio</string>
        <string>--port</string>
        <string>10001</string>
        <string>--config</string>
        <string>CONFIG_PATH</string>
    </array>

    <key>WorkingDirectory</key>
    <string>RAGLING_DIR</string>

    <key>KeepAlive</key>
    <true/>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>LOG_DIR/ragling.out.log</string>

    <key>StandardErrorPath</key>
    <string>LOG_DIR/ragling.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

## Replace Placeholders

| Placeholder | How to find | Example |
|-------------|------------|---------|
| `UV_PATH` | `which uv` | `/opt/homebrew/bin/uv` |
| `RAGLING_DIR` | Expanded `~/ragling` | `/Users/steve/ragling` |
| `CONFIG_PATH` | Expanded config path | `/Users/steve/.ragling/config.json` |
| `LOG_DIR` | Create a log directory | `/Users/steve/.ragling/logs` |

## Load and Start

```bash
mkdir -p ~/.ragling/logs
launchctl load ~/Library/LaunchAgents/com.ragling.serve.plist
```

## Verify

```bash
launchctl list | grep ragling
curl -s -o /dev/null -w "%{http_code}" http://localhost:10001/sse
```

## Stop and Unload

```bash
launchctl unload ~/Library/LaunchAgents/com.ragling.serve.plist
```
