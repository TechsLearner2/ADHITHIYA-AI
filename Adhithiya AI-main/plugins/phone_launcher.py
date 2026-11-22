import subprocess

PLUGIN = {
    "name": "phone_launcher",
    "description": "Executes full system commands and launches apps on the connected Infinix phone.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "target": {
                "type": "STRING",
                "enum": ["youtube", "whatsapp", "camera", "settings", 
"chrome", "lock_screen", "home_screen"],
                "description": "The target app or system command to execute on the phone."
            }
        },
        "required": ["target"]
    }
}

COMMAND_INDEX = {
    "youtube": 0,
    "whatsapp": 1,
    "camera": 2,
    "settings": 3,
    "chrome": 4,
    "lock_screen": 5,
    "home_screen": 6
}

def run(target):
    try:
        # Unpack target if the assistant passes a dictionary
        if isinstance(target, dict):
            target = target.get("target", "")

        if target not in COMMAND_INDEX:
            return f"Target '{target}' is not configured."

        down_presses = COMMAND_INDEX[target]
        down_keys = "\n".join(["key code 125\ndelay 0.05" for _ in 
range(down_presses)])

        applescript = f"""
        tell application "System Events"
            tell process "Soduto"
                perform action "AXPress" of menu bar item 1 of menu bar 1
                delay 0.2
                key code 125
                delay 0.1
                key code 124
                delay 0.1
                repeat 5 times
                    key code 125
                    delay 0.05
                end repeat
                key code 124
                delay 0.1
                {down_keys}
                key code 36
            end tell
        end tell
        """
        subprocess.run(["osascript", "-e", applescript], check=True)
        return f"Successfully executed '{target}' on Infinix HOT 50 5G."

    except Exception as e:
        return f"Failed to run phone command: {str(e)}"
