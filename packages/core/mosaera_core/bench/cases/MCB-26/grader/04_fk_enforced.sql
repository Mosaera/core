-- Negative: linking to a non-existent book must be rejected (real FK).
INSERT INTO authors (name) VALUES ('Grace Hopper');
DO $$
DECLARE aid bigint;
BEGIN
  SELECT id INTO aid FROM authors WHERE name = 'Grace Hopper';
  INSERT INTO book_authors (book_id, author_id) VALUES (999999, aid);
  RAISE EXCEPTION 'link to a non-existent book was accepted (FK not enforced)';
EXCEPTION WHEN foreign_key_violation THEN
  NULL;  -- expected
END $$;
