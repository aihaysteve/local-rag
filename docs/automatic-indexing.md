# Automatic Indexing with launchd

Keep your index current automatically. Unlike cron, launchd catches up on missed runs after your Mac wakes from sleep.

## Setup

**1. Create the plist file** (run from the ragling repo directory):

```bash
cat > ~/Library/LaunchAgents/com.ragling.index.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ragling.index</string>

    <key>ProgramArguments</key>
    <array>
        <string>$(which uv)</string>
        <string>run</string>
        <string>--directory</string>
        <string>$PWD</string>
        <string>ragling</string>
        <string>index</string>
        <string>all</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(dirname $(which uv)):/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>StartInterval</key>
    <integer>7200</integer>

    <key>StandardOutPath</key>
    <string>$HOME/.ragling/index.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.ragling/index.log</string>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
```

**2. Load the agent:**

```bash
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

**3. Verify:**

```bash
launchctl list | grep ragling
tail -f ~/.ragling/index.log
```

## Managing

```bash
# Stop and unload
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

See [Indexing Sources](indexing.md) for what gets indexed, and [Configuration](configuration.md) to control which sources are included.
