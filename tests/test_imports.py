"""Test that all imports work correctly."""
import unittest


class TestImports(unittest.TestCase):
    def test_almaapitk_imports(self):
        """Test almaapitk public API imports."""
        from almaapitk import (
            AlmaAPIClient,
            AlmaAPIError,
            AlmaValidationError,
            Admin,
            Users,
        )
        self.assertTrue(callable(AlmaAPIClient))
        self.assertTrue(callable(Admin))
        self.assertTrue(callable(Users))

    def test_project_module_import(self):
        """Test project main module imports."""
        from update_expired_user_emails import EmailUpdateScript
        self.assertTrue(callable(EmailUpdateScript))

    def test_no_legacy_imports(self):
        """Verify no legacy imports in main module."""
        import re
        from pathlib import Path

        # Find the module file
        module_path = Path(__file__).parent.parent / "update_expired_user_emails.py"
        content = module_path.read_text()

        # Check for forbidden imports (internal modules, not public API)
        forbidden = [
            r"from\s+src\.",
            r"import\s+src\.",
            r"from\s+client\.",
            r"from\s+domains\.",
            r"from\s+utils\.",
        ]
        for pattern in forbidden:
            matches = re.findall(pattern, content)
            self.assertEqual(len(matches), 0, f"Found forbidden import: {pattern}")


if __name__ == "__main__":
    unittest.main()
