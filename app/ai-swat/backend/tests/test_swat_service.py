"""Tests for SWAT service and path validation."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["DATA_ROOT"] = tempfile.mkdtemp()

from services import pyswat_facade
from services.swat_service import SWATService


class TestTxtInOutValidation(unittest.TestCase):
    def test_missing_dir(self):
        result = pyswat_facade.validate_txtinout("/nonexistent/path")
        self.assertFalse(result["valid"])

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = pyswat_facade.validate_txtinout(tmp)
            self.assertFalse(result["valid"])
            self.assertTrue(len(result["missing_files"]) > 0)

    def test_minimal_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "file.cio"), "w").close()
            open(os.path.join(tmp, "hru-data.hru"), "w").close()
            open(os.path.join(tmp, "time.sim"), "w").close()
            result = pyswat_facade.validate_txtinout(tmp)
            self.assertTrue(result["valid"])
            self.assertEqual(result["format"], "modern")


class TestSWATServiceMock(unittest.TestCase):
    def setUp(self):
        from db import init_db
        init_db()
        self.service = SWATService()

    def test_engine_status(self):
        status = self.service.engine_status()
        self.assertIn("pyswatplus_installed", status)
        self.assertIn("data_root", status)


if __name__ == "__main__":
    unittest.main()
