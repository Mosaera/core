from csvtable import parse_table


def test_well_formed_table_parses() -> None:
    rows = parse_table("name,age\nalice,30\nbob,40")
    assert rows == [
        {"name": "alice", "age": "30"},
        {"name": "bob", "age": "40"},
    ]
