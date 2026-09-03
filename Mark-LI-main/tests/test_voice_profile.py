import json
import shutil
import unittest
from pathlib import Path

from core.voice_gate import VoiceProfileStore, clear_voice_profile, voice_profile_status


class VoiceProfileSmokeTests(unittest.TestCase):
    def test_profile_contains_embedding_only_and_can_be_cleared(self):
        directory = Path(__file__).resolve().parent / "_voice_profile_workspace"
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        try:
            path = directory / "voice_profile.json"
            VoiceProfileStore(path).save([0.1] * 16)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["note"].startswith("Embedding metadata"), True)
            self.assertNotIn("audio", payload)
            self.assertEqual(voice_profile_status(path), "enrolled")
            clear_voice_profile(path)
            self.assertEqual(voice_profile_status(path), "not_enrolled")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
