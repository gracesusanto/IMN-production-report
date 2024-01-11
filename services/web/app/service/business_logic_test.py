# docker exec -it app /bin/bash
# python -m unittest app/service/business_logic_test.py
import unittest
from app.service.business_logic import (
    validate_nik,
    validate_name,
)


class TestValidators(unittest.TestCase):
    def test_validate_nik(self):
        # Valid cases
        self.assertTrue(validate_nik("ABC123"))
        self.assertTrue(validate_nik("123-ABC"))
        self.assertTrue(validate_nik("XYZ-9999"))

        # Invalid cases
        self.assertFalse(validate_nik("ABC 123"))  # Contains space
        self.assertFalse(validate_nik("123*abc"))  # Contains special character
        self.assertFalse(validate_nik(""))  # Empty string

    def test_validate_name(self):
        # Valid cases
        self.assertTrue(validate_name("John Doe"))
        self.assertTrue(validate_name("A. Syidik"))

        # Invalid cases
        self.assertFalse(validate_name("John123"))  # Contains numbers
        self.assertFalse(
            validate_name("name@domain.com")
        )  # Contains special characters
        self.assertFalse(validate_name(""))  # Empty string


if __name__ == "__main__":
    unittest.main()
