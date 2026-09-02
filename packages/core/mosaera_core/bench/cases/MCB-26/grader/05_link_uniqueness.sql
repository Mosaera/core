-- Negative: the same (book, author) pair must not be linkable twice (composite PK/UNIQUE).
INSERT INTO authors (name) VALUES ('Alan Turing');
INSERT INTO books (title, isbn, price) VALUES ('On Computable Numbers', 'ISBN-TUR', 20.00);
INSERT INTO book_authors (book_id, author_id)
  SELECT b.id, a.id FROM books b, authors a WHERE b.isbn = 'ISBN-TUR' AND a.name = 'Alan Turing';
DO $$
BEGIN
  INSERT INTO book_authors (book_id, author_id)
    SELECT b.id, a.id FROM books b, authors a WHERE b.isbn = 'ISBN-TUR' AND a.name = 'Alan Turing';
  RAISE EXCEPTION 'a duplicate (book, author) link was accepted (missing composite PK/UNIQUE)';
EXCEPTION WHEN unique_violation THEN
  NULL;  -- expected
END $$;
