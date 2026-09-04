import subprocess

# 1. METADATA SCHEMA: Controls when Gemini activates this tool
PLUGIN = {
    "name": "mac_system_control",
    "description": "Controls macOS system settings such as volume level or opening specific system settings panes.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["set_volume", "open_setting_pane"],
                "description": "The type of system command to execute."
            },
            "volume_level": {
                "type": "INTEGER",
                "description": "Volume level from 0 to 100 (used when action is 'set_volume')."
            },
            "setting_pane": {
                "type": "STRING",
                "enum": ["sound", "displays", "network", "bluetooth", "security"],
                "description": "Which preference pane to open (used when action is 'open_setting_pane')."
            }
        },
        "required": ["action"]
    }
}

# 2. EXECUTION LOGIC: Runs when the assistant calls the tool
def run(action, volume_level=None, setting_pane=None):
    """
    Executes native macOS Monterey commands based on Gemini's parsed intent.
    """
    try:
        if action == "set_volume":
            if volume_level is None:
                return "Please specify a volume level between 0 and 100."
            
            # Clamp value between 0 and 100
            volume = max(0, min(100, volume_level))
            applescript = f'set volume output volume {volume}'
            subprocess.run(["osascript", "-e", applescript], check=True)
            return f"System volume set to {volume}%."

        elif action == "open_setting_pane":
            pane_map = {
                "sound": "Sound.prefPane",
                "displays": "Displays.prefPane",
                "network": "Network.prefPane",
                "bluetooth": "Bluetooth.prefPane",
                "security": "Security.prefPane"
            }
            
            pane_file = pane_map.get(setting_pane, "Sound.prefPane")
            pane_path = f"/System/Library/PreferencePanes/{pane_file}"
            
            subprocess.run(["open", pane_path], check=True)
            return f"Opened the {setting_pane or 'requested'} settings pane."

        return "Invalid action provided."

    except Exception as e:
        return f"Failed to execute system command: {str(e)}"