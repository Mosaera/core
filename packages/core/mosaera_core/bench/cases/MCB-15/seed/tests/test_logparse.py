from logparse import parse_log_line


def test_representative_line_parses() -> None:
    assert parse_log_line("ERROR 2024-01-01T10:00:00 Disk full path=/var code=5") == {
        "level": "ERROR",
        "timestamp": "2024-01-01T10:00:00",
        "message": "Disk full",
        "fields": {"path": "/var", "code": "5"},
    }
