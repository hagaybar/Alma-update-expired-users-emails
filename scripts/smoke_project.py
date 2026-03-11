#!/usr/bin/env python3
"""Smoke test - verifies imports work correctly."""
import sys


def main():
    # Test almaapitk imports
    from almaapitk import (
        AlmaAPIClient,
        AlmaAPIError,
        AlmaValidationError,
        Admin,
        Users,
    )
    print("almaapitk imports: OK")

    # Test project module import
    from update_expired_user_emails import EmailUpdateScript
    print("EmailUpdateScript import: OK")

    print("All smoke tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
