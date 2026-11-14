-- Tiny fictional dataset for validator tests.
CREATE TABLE nums (n INTEGER, label VARCHAR);
INSERT INTO nums SELECT range AS n, CASE WHEN range % 2 = 0 THEN 'even' ELSE 'odd' END FROM range(20);
