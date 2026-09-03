-- Negative: a non-positive price must be rejected (CHECK price > 0).
DO $$
BEGIN
  INSERT INTO books (title, isbn, price) VALUES ('Freebie', 'ISBN-FREE', 0);
  RAISE EXCEPTION 'zero price was accepted (missing CHECK price > 0)';
EXCEPTION WHEN check_violation THEN
  NULL;  -- expected
END $$;
