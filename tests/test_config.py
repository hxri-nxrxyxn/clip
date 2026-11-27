import unittest
from app import config


class TestConfig(unittest.TestCase):
    def test_load_default_config(self):
        cfg = config.load_config()
        self.assertIn("targeted", cfg)
        self.assertIn("whisper", cfg)
        self.assertIn("yamnet", cfg)
        self.assertIn("llm", cfg)

    def test_get_value(self):
        val = config.get("whisper", "model")
        self.assertEqual(val, "large-v3-turbo")

    def test_validate_negative_pre_fails(self):
        invalid = {"targeted": {"pre": -1.0}}
        with self.assertRaises(ValueError):
            config._validate(invalid)


if __name__ == "__main__":
    unittest.main()
