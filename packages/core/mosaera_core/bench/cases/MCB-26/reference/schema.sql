-- Reference solution for MCB-26 (proves the grader is winnable; never shown to Mosaera).
CREATE TABLE authors (
  id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL
);

CREATE TABLE books (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title          text NOT NULL,
  isbn           text NOT NULL UNIQUE,
  price          numeric(10, 2) NOT NULL CHECK (price > 0),
  published_year integer
);

CREATE TABLE book_authors (
  book_id   bigint NOT NULL REFERENCES books (id) ON DELETE CASCADE,
  author_id bigint NOT NULL REFERENCES authors (id) ON DELETE CASCADE,
  PRIMARY KEY (book_id, author_id)
);
