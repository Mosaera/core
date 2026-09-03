-- Negative: a duplicate isbn must be rejected (UNIQUE on books.isbn).
INSERT INTO books (title, isbn, price) VALUES ('First', 'ISBN-DUP', 10.00);
DO $$
BEGIN
  INSERT INTO books (title, isbn, price) VALUES ('Second', 'ISBN-DUP', 12.00);
  RAISE EXCEPTION 'duplicate isbn was accepted (books.isbn is not UNIQUE)';
EXCEPTION WHEN unique_violation THEN
  NULL;  -- expected
END $$;
