import unittest

from app import pipeline


class TestPipelineImports(unittest.TestCase):
    def test_stage_ids(self):
        self.assertEqual(len(pipeline.STAGE_IDS), 6)
        self.assertEqual(pipeline.STAGE_IDS[0], "1-ingest")
        self.assertEqual(pipeline.STAGE_IDS[1], "2-transcribe")
        self.assertEqual(pipeline.STAGE_IDS[2], "3-select")

    def test_validate_target(self):
        with self.assertRaises(ValueError):
            pipeline.validate_target("")

        url = "https://www.youtube.com/watch?v=12345"
        self.assertEqual(pipeline.validate_target(url), url)

    def test_slug(self):
        self.assertEqual(pipeline.slug("Test Video! 123"), "Test-Video-123")


if __name__ == "__main__":
    unittest.main()
