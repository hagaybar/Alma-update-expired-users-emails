# tests/test_smoke_imports.py
"""Smoke tests: imports + no legacy paths."""
import re
import unittest
from pathlib import Path


class TestImports(unittest.TestCase):
    def test_almaapitk_public_api_imports(self):
        """Test almaapitk public API imports."""
        from almaapitk import (
            AlmaAPIClient,
            AlmaAPIError,
            AlmaValidationError,
            Admin,
            Users,
        )

        # "callable" works for classes and functions
        self.assertTrue(callable(AlmaAPIClient))
        self.assertTrue(issubclass(AlmaAPIError, Exception))
        self.assertTrue(issubclass(AlmaValidationError, Exception))
        self.assertTrue(callable(Admin))
        self.assertTrue(callable(Users))

    def test_project_entry_import(self):
        """Test project entry-point imports."""
        # Adjust ONE of these to match your actual package/module name
        # Option A: package import
        # from update_expired_users_emails import main
        # Option B: class import
        from update_expired_user_emails import EmailUpdateScript  # <- ensure this path is correct

        self.assertTrue(callable(EmailUpdateScript))

    def test_no_legacy_imports_in_repo(self):
        """Verify no legacy imports anywhere in the project code (not only one file)."""
        project_root = Path(__file__).resolve().parents[1]

        # Scan typical source locations; adjust if your repo uses src/ layout
        candidate_dirs = [project_root / "src", project_root]
        py_files = []
        for d in candidate_dirs:
            if d.exists():
                py_files.extend([p for p in d.rglob("*.py") if "site-packages" not in str(p)])

        forbidden_patterns = [
            r"from\s+src\.",          # old layout
            r"import\s+src\.",
            r"from\s+client\.",       # almaapitk legacy internal
            r"from\s+domains\.",
            r"from\s+utils\.",
            r"from\s+almaapitk\._internal\.",  # forbid private internal usage (optional but recommended)
        ]

        offenders = []
        for p in py_files:
            text = p.read_text(encoding="utf-8", errors="ignore")
            for pat in forbidden_patterns:
                if re.search(pat, text):
                    offenders.append((str(p.relative_to(project_root)), pat))

        self.assertEqual(offenders, [], f"Forbidden imports found: {offenders}")


if __name__ == "__main__":
    unittest.main()