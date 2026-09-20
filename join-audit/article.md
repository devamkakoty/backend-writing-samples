# Deterministic CSV joins: account for every row before pairing records

**Devam Kakoty — original AI-assisted technical sample.** Synthetic inputs;
no client or production-deployment claim.

A backend import can appear successful while quietly discarding records. A lookup built as `lookup[row.key] = row` retains one value per key, so another assignment replaces the previous value. That is useful mapping behavior, but an unsafe substitute for checking join cardinality. Python documents dictionary assignment semantics in its [mapping reference][mapping].

This sample implements a stricter contract: an exact, one-to-one join audit. It does not select a duplicate winner, expand every possible pair, or merge payload columns. Instead, it classifies every input record and identifies a partner only when the key appears exactly once on each side. The accompanying files require only the Python standard library and target Python 3.11 or later; this is a compatibility target, not an execution claim.

## 1. Define ambiguity before implementing the join

For a nonblank key, let **own_count** be its frequency in the row's source table and **other_count** its frequency in the opposite table. Each row receives exactly one status, with this precedence:

| Condition | Status | Partner |
| --- | --- | --- |
| Key is empty or whitespace-only | `blank_key` | None |
| Either frequency exceeds one | `ambiguous` | None |
| Both frequencies equal one | `matched` | Opposite record position |
| Own frequency is one; opposite frequency is zero | `unmatched` | None |

Ambiguity is deliberately stricter than “multiple candidates on the other side.” If the left table contains two occurrences and the right contains one, **all three records are ambiguous**. Pairing the unique right record with either left record would make an arbitrary choice.

Likewise, two same-key records without any counterpart are ambiguous, not unmatched. This status means the one-to-one key contract is violated, even when no candidate exists. Identical payloads do not excuse duplicate keys.

Blank keys are excluded from both indexes and receive counts of zero by convention. These zeros mean “not eligible for key counting,” not “this row does not exist.” Two blank keys never match.

Comparison otherwise uses the original string. Leading spaces on a nonblank key, letter case, leading zeros, and distinct Unicode representations remain significant. There is no trimming-based matching, numeric conversion, Unicode normalization, or fuzzy matching.

## 2. Parse records without losing their locations

`read_csv()` uses `csv.reader` rather than immediately constructing dictionaries. It rejects missing headers, blank column names, duplicate column names, absent key columns, and records with the wrong field count. Header names are exact strings; they are not normalized.

This distinction matters because `DictReader` has defined accommodation behavior for extra and missing fields. Here, shape validation is an explicit prerequisite, not an accidental side effect of converting rows to mappings. The [CSV documentation][csv] describes both reader interfaces.

Each immutable `Row` retains its original field tuple, a one-based **data-record position**, and inclusive physical start/end lines. The header does not count as a data record. Physical lines and record positions differ when quoted fields contain newlines; `reader.line_num` measures consumed source lines, not records.

`load_csv()` opens files using `encoding="utf-8-sig"` and `newline=""`. The encoding handles a leading UTF-8 signature when present; the newline setting lets the CSV parser handle line endings without text-layer translation. See the [encoding documentation][encoding] and [CSV newline guidance][csv].

A physically empty record is rejected as a width error rather than skipped. A correctly shaped record containing an empty key is retained and classified. Header-only files are valid empty tables. Malformed input raises an error before any audit is returned; `strict=True` adds parser checks but does not replace schema validation.

## 3. Index groups, not winners

The central implementation is intentionally small:

```python
groups: dict[str, list[Row]] = defaultdict(list)
for row in table.rows:
    if row.key.strip():
        groups[row.key].append(row)
```

The index retains references to every eligible row. `defaultdict(list)` supplies a list for a previously unseen key, as described in the [collections documentation][collections]. Calling `strip()` here only tests blankness; the dictionary key remains unchanged.

After constructing both indexes, `audit_join()` walks each original row sequence. It looks up group sizes, applies the status precedence, and emits one `Decision` per row. Only a unique-to-unique match receives `partner_position`.

The resulting invariant is easy to inspect: left decisions preserve left order, right decisions preserve right order, and every source row occurs exactly once on its own side. Matched partners are reciprocal. Equal inputs produce equal ordered decisions without timestamps, random choices, or dependency on directory enumeration.

Keeping group references and counts also avoids a quadratic diagnostic trap. A large duplicate group does not cause every decision to store every candidate position. This implementation stores the input rows and indexes in memory; under ordinary dictionary lookup assumptions, indexing and classification take linear work in the combined record count, in addition to parsing input characters.

## 4. Run a bounded audit

From this sample's directory, an operator can inspect two authorized, small CSV files with the same key-column name:

```powershell
python -B join_audit.py left.csv right.csv --key id
```

These are illustrative filenames, not bundled datasets. The CLI reads files but does not write a joined dataset. It prints one JSON summary containing per-side status counts and the number of matched pairs, never keys or payload cells.

Exit code `0` means every existing row matched, including the vacuously clean case of two empty tables. Code `1` means the audit completed with at least one blank, ambiguous, or unmatched row. Code `2` means input or argument rejection. Rejected input produces no partial summary. Applications needing row-level inspection can use `audit_join()` directly and keep its returned payloads out of general logs.

## 5. Validate the contract, not just the happy path

Run the accompanying synthetic tests with:

```powershell
python -B -m unittest discover -s . -p test_join_audit.py -v
```

The suite covers duplicates on either side, many-to-many ambiguity, duplicate keys without counterparts, blanks, exact-string distinctions, multiline records, invalid schemas, malformed quoting, empty tables, deterministic ordering, summary counts, and CLI exit behavior. Fixtures are small inline strings; no dataset generation or installation is required. Python's [unittest documentation][unittest] explains discovery, assertions, and subtests.

**Observed validation, September 20, 2026:** all **19 tests passed** on
Windows with **Python 3.13.3**, using
`python -m unittest -v test_join_audit.py`. This includes the in-memory
CLI exit-code and summary checks. The recorded validation did not audit a
customer file or execute the illustrative `left.csv`/`right.csv` command.
Python 3.11 remains the source compatibility target, not an additional tested
runtime.

## Limits worth keeping explicit

This is an in-memory, comma-delimited, single-key audit, not a streaming integration service. It does not enforce cross-file snapshot consistency, infer encodings or dialects, repair malformed records, or decide business-specific deduplication rules. Separate runs can differ if source files change. Row positions describe parsed inputs, not durable entity identifiers.

For large or untrusted inputs, add explicit resource limits and an appropriate storage-backed design. For composite keys or intentional one-to-many relationships, change the contract and tests first. The useful guarantee here is narrower: no structurally valid input row disappears merely because another row shares its key.

## First-party references

- [Python 3.11: CSV reading and writing][csv]
- [Python 3.11: dictionary mappings][mapping]
- [Python 3.11: defaultdict][collections]
- [Python 3.11: UTF-8 signature codec][encoding]
- [Python 3.11: unittest][unittest]

[csv]: https://docs.python.org/3.11/library/csv.html
[mapping]: https://docs.python.org/3.11/library/stdtypes.html#mapping-types-dict
[collections]: https://docs.python.org/3.11/library/collections.html#collections.defaultdict
[encoding]: https://docs.python.org/3.11/library/codecs.html#encodings.utf_8_sig
[unittest]: https://docs.python.org/3.11/library/unittest.html
