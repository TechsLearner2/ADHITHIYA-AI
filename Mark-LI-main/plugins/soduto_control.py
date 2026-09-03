import subprocess
import time

# 1. METADATA SCHEMA FOR JARVIS
PLUGIN = {
    "name": "soduto_control",
    "description": "Controls phone integration features via Soduto status menu on macOS.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["ring_phone", "browse_files", "send_files", "send_sms", "control_device"],
                "description": "The target action to trigger on the paired Infinix phone."
            }
        },
        "required": ["action"]
    }
}

ACTION_DOWN_PRESSES = {
    "browse_files": 0,
    "send_files": 1,
    "send_sms": 2,
    "ring_phone": 3,
    "control_device": 4
}

def _navigate_soduto(down_count):
    down_keys = "\n".join(["key code 125\ndelay 0.1" for _ in range(down_count)])
    
    script = f"""
    tell application "System Events"
        tell process "Soduto"
            perform action "AXPress" of menu bar item 1 of menu bar 1
            delay 0.3
            key code 125
            delay 0.2
            key code 124
            delay 0.2
            {down_keys}
            delay 0.1
            key code 36
        end tell
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=True)

# 2. EXECUTION LOGIC
def run(action):
    try:
        # If Jarvis passes a dictionary e.g. {'action': 'ring_phone'}, unpack it
        if isinstance(action, dict):
            action = action.get("action", "")

        if action in ACTION_DOWN_PRESSES:
            _navigate_soduto(ACTION_DOWN_PRESSES[action])
            return f"Successfully executed '{action}' on Infinix HOT 50 5G."

        return f"Invalid action '{action}'. Supported actions: {list(ACTION_DOWN_PRESSES.keys())}"

    except Exception as e:
        return f"Soduto automation error: {str(e)}"