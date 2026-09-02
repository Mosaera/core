# Design a bookstore inventory schema (SQL / PostgreSQL)

Design the relational schema for a small bookstore's inventory, targeting
**PostgreSQL**. Start from an empty repository and write the schema as SQL.

## Deliverable

- Put the schema in **`schema.sql`** at the repository root (or, if you prefer
  ordered migrations, one or more files under **`migrations/`** applied in
  filename order). It must apply cleanly to an empty PostgreSQL database with
  `psql` (no errors).

## Requirements

Model three things and the relationship between them:

- **authors** — each has a surrogate primary key and a `name` that is required
  (not null).
- **books** — each has a surrogate primary key, a required `title`, an `isbn`
  that is **unique**, a `price` that must be **greater than 0** (enforced by a
  check constraint), and an optional `published_year` integer.
- **book_authors** — the many-to-many link between books and authors: it
  references a book and an author by foreign key, and the same (book, author)
  pair may not appear twice (a composite primary key or unique constraint).
- The foreign keys in `book_authors` must be **real, enforced** foreign keys
  (an insert referencing a non-existent book or author is rejected).

## Quality

- Use appropriate column types and NOT NULL where the requirement says a value
  is required.
- Include assertion tests under **`tests/`** as `.sql` files that insert sample
  rows and verify the constraints hold (e.g. a duplicate ISBN is rejected). Each
  test file should exit non-zero (via `RAISE` / `ON_ERROR_STOP`) when its
  expectation is violated, so the validator can run them.
