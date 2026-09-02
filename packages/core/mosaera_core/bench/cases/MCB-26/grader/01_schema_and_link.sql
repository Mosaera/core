-- Hidden acceptance grader for MCB-26. NEVER shown to Mosaera; run against the
-- delivered+applied schema (each file its own psql -v ON_ERROR_STOP=1: exit 0 = pass).
-- Positive: the three tables exist and a book<->author link round-trips.
INSERT INTO authors (name) VALUES ('Ada Lovelace');
INSERT INTO books (title, isbn, price) VALUES ('Analytical Engine', 'ISBN-0001', 42.00);
INSERT INTO book_authors (book_id, author_id)
  SELECT b.id, a.id FROM books b, authors a
  WHERE b.isbn = 'ISBN-0001' AND a.name = 'Ada Lovelace';
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n
  FROM book_authors ba
  JOIN books b ON b.id = ba.book_id
  JOIN authors a ON a.id = ba.author_id
  WHERE b.isbn = 'ISBN-0001' AND a.name = 'Ada Lovelace';
  IF n <> 1 THEN RAISE EXCEPTION 'expected exactly one linked row, got %', n; END IF;
END $$;
