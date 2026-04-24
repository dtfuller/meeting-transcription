import pytest

from app.folders import (
    MAX_NAME_LEN,
    validate_folder_name,
    validate_folder_path,
)


class TestValidateFolderName:
    def test_trims_whitespace(self):
        assert validate_folder_name("  Clients  ") == "Clients"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_folder_name("   ")

    def test_rejects_reserved_names(self):
        for name in [".", "..", "_inbox"]:
            with pytest.raises(ValueError, match="reserved"):
                validate_folder_name(name)

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="'/' or '"):
            validate_folder_name("a/b")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="'/' or '"):
            validate_folder_name("a\\b")

    def test_rejects_overlong_name(self):
        with pytest.raises(ValueError, match="too long"):
            validate_folder_name("x" * (MAX_NAME_LEN + 1))

    def test_accepts_unicode(self):
        assert validate_folder_name("Español") == "Español"


class TestValidateFolderPath:
    def test_root_is_valid(self):
        assert validate_folder_path("") == ""
        assert validate_folder_path("   ") == ""

    def test_accepts_nested(self):
        assert validate_folder_path("Clients/Acme/Q1") == "Clients/Acme/Q1"

    def test_strips_surrounding_whitespace(self):
        assert validate_folder_path("  Clients/Acme  ") == "Clients/Acme"

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError, match="start or end"):
            validate_folder_path("/Clients")

    def test_rejects_trailing_slash(self):
        with pytest.raises(ValueError, match="start or end"):
            validate_folder_path("Clients/")

    def test_each_segment_runs_through_name_check(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_folder_path("Clients/../secrets")
