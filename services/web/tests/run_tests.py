#!/usr/bin/env python3
"""
Test runner for the reporting pipeline test suite.

This script provides an easy way to run all tests with proper configuration.
"""

import sys
import subprocess
import os
from pathlib import Path

def run_tests(test_type="all", verbose=False):
    """Run the test suite."""

    # Get the project root directory
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    # Base pytest command
    cmd = ["python", "-m", "pytest"]

    # Add test directory
    if test_type == "all":
        cmd.append("tests/")
    elif test_type == "unit":
        cmd.extend([
            "tests/test_business_logic.py",
            "tests/test_generate_report.py",
            "tests/test_backfill_script.py"
        ])
    elif test_type == "integration":
        cmd.append("tests/test_integration.py")
    elif test_type == "parity":
        cmd.append("tests/test_csv_parity.py")
    elif test_type.startswith("tests/"):
        cmd.append(test_type)
    else:
        cmd.append(f"tests/test_{test_type}.py")

    # Add options
    if verbose:
        cmd.extend(["-v", "-s"])
    else:
        cmd.append("-v")

    # Add coverage if available
    try:
        import coverage
        cmd.extend(["--cov=app", "--cov-report=term-missing"])
    except ImportError:
        print("Coverage not available. Install with: pip install pytest-cov")

    # Add other useful options
    cmd.extend([
        "--tb=short",  # Shorter traceback format
        "-x",          # Stop on first failure
        "--disable-warnings"  # Disable warnings for cleaner output
    ])

    print(f"Running: {' '.join(cmd)}")
    print("=" * 60)

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
        return 130
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run reporting pipeline tests")
    parser.add_argument(
        "test_type",
        nargs="?",
        default="all",
        choices=["all", "unit", "integration", "parity", "business_logic", "generate_report", "backfill_script", "csv_parity"],
        help="Type of tests to run (default: all)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    print("Reporting Pipeline Test Suite")
    print("=" * 60)
    print(f"Test type: {args.test_type}")
    print(f"Verbose: {args.verbose}")
    print()

    return_code = run_tests(args.test_type, args.verbose)

    if return_code == 0:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n❌ Tests failed with code {return_code}")

    return return_code

if __name__ == "__main__":
    sys.exit(main())