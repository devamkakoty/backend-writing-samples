"""Small, deliberately reviewable synthetic fixtures; no disk data generation."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from join_audit import audit_join, main, read_csv


def table(text: str, key: str = "id"):
    return read_csv(io.StringIO(text, newline=""), key)


def audit(left: str, right: str):
    return audit_join(table(left), table(right))


class JoinAuditTests(unittest.TestCase):
    def test_unique_matches_preserve_source_order_and_values(self):
        report = audit("id,note\nb,second\na,first\n", "id,note\na,A\nb,B\n")
        self.assertEqual([d.row.key for d in report.left], ["b", "a"])
        self.assertEqual([d.partner_position for d in report.left], [2, 1])
        self.assertEqual([d.partner_position for d in report.right], [2, 1])
        self.assertEqual(report.left[0].row.values, ("b", "second"))
        self.assertFalse(report.has_issues())
        self.assertEqual(report.summary()["matched_pairs"], 2)

    def test_duplicate_left_makes_unique_right_ambiguous(self):
        report = audit("id\nx\nx\n", "id\nx\n")
        self.assertEqual([d.status for d in report.left], ["ambiguous"] * 2)
        self.assertEqual(report.right[0].status, "ambiguous")
        self.assertEqual((report.right[0].own_count, report.right[0].other_count),
                         (1, 2))
        self.assertTrue(all(d.partner_position is None
                            for d in report.left + report.right))

    def test_duplicate_right_makes_unique_left_ambiguous(self):
        report = audit("id\nx\n", "id\nx\nx\n")
        self.assertEqual(report.left[0].status, "ambiguous")
        self.assertEqual((report.left[0].own_count, report.left[0].other_count),
                         (1, 2))

    def test_many_to_many_keeps_all_rows_without_pair_expansion(self):
        report = audit("id\nx\nx\n", "id\nx\nx\nx\n")
        self.assertEqual((len(report.left), len(report.right)), (2, 3))
        self.assertTrue(all(d.status == "ambiguous"
                            for d in report.left + report.right))
        self.assertEqual(report.summary()["matched_pairs"], 0)

    def test_duplicate_without_counterpart_is_ambiguous_not_unmatched(self):
        report = audit("id\nx\nx\n", "id\n")
        self.assertEqual([d.status for d in report.left], ["ambiguous"] * 2)
        self.assertEqual([(d.own_count, d.other_count) for d in report.left],
                         [(2, 0), (2, 0)])

    def test_blank_keys_never_match_or_form_duplicate_groups(self):
        report = audit('id\n""\n" \t"\n', 'id\n""\n')
        for decision in report.left + report.right:
            self.assertEqual(decision.status, "blank_key")
            self.assertEqual((decision.own_count, decision.other_count), (0, 0))
            self.assertIsNone(decision.partner_position)

    def test_nonblank_keys_are_not_trimmed_casefolded_or_coerced(self):
        report = audit("id\n a \nA\n01\n", "id\na\n1\n")
        self.assertTrue(all(d.status == "unmatched"
                            for d in report.left + report.right))
        self.assertEqual(report.left[0].row.key, " a ")

    def test_unicode_is_not_normalized(self):
        report = audit("id\n\u00e9\n", "id\ne\u0301\n")
        self.assertEqual(report.left[0].status, "unmatched")
        self.assertEqual(report.right[0].status, "unmatched")

    def test_unmatched_rows_on_both_sides_are_retained(self):
        report = audit("id\nleft-only\n", "id\nright-only\n")
        self.assertEqual(report.left[0].status, "unmatched")
        self.assertEqual(report.right[0].status, "unmatched")
        self.assertTrue(report.has_issues())

    def test_multiline_fields_preserve_record_and_physical_positions(self):
        parsed = table('id,note\r\nx,"first\r\nsecond"\r\ny,"comma, quote ""ok"""\r\n')
        self.assertEqual(
            [(r.position, r.line_start, r.line_end) for r in parsed.rows],
            [(1, 2, 3), (2, 4, 4)],
        )
        self.assertEqual(parsed.rows[0].values[1], "first\r\nsecond")
        self.assertEqual(parsed.rows[1].values[1], 'comma, quote "ok"')

    def test_multiline_header_does_not_shift_record_positions(self):
        parsed = table('"long\nheader",id\nnote,x\n')
        self.assertEqual(parsed.rows[0].position, 1)
        self.assertEqual((parsed.rows[0].line_start, parsed.rows[0].line_end), (3, 3))

    def test_header_only_inputs_have_zero_rows_and_no_issues(self):
        report = audit("id\n", "id\n")
        self.assertEqual(report.left, ())
        self.assertEqual(report.right, ())
        self.assertFalse(report.has_issues())
        self.assertEqual(report.summary()["matched_pairs"], 0)

    def test_invalid_headers_are_rejected(self):
        for text in ("", "\n", "id,id\n", "id, \n", "other\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                table(text)

    def test_short_long_and_physically_empty_records_are_rejected(self):
        for text in ("id,note\nx\n", "id\nx,extra\n", "id\n\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "record 1"):
                table(text)

    def test_unclosed_quoted_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid CSV"):
            table('id,note\nx,"unfinished\n')

    def test_custom_key_column_and_no_final_newline(self):
        parsed = table("note,code\nvalue,x", key="code")
        self.assertEqual(parsed.headers, ("note", "code"))
        self.assertEqual(parsed.rows[0].key, "x")

    def test_determinism_partition_and_symmetric_match_counts(self):
        left = table('id\nz\nx\nx\n""\na\n')
        right = table("id\na\nx\nq\n")
        first = audit_join(left, right)
        self.assertEqual(first, audit_join(left, right))
        for decisions, source in ((first.left, left), (first.right, right)):
            self.assertEqual([d.row for d in decisions], list(source.rows))
            self.assertEqual(len({d.row.position for d in decisions}), len(source.rows))
        summary = first.summary()
        self.assertEqual(summary["left"]["matched"], summary["right"]["matched"])
        for side in ("left", "right"):
            counts = summary[side]
            self.assertEqual(counts["rows"], sum(counts[s] for s in
                             ("blank_key", "ambiguous", "matched", "unmatched")))

    def test_cli_status_codes_and_summary_only_output(self):
        for left, right, expected in (
            ("id\nsecret-key\n", "id\nsecret-key\n", 0),
            ("id\nsecret-key\n", "id\n", 1),
        ):
            with self.subTest(expected=expected):
                output = io.StringIO()
                with patch("join_audit.load_csv", side_effect=[table(left), table(right)]):
                    with redirect_stdout(output):
                        result = main(["left.csv", "right.csv"])
                self.assertEqual(result, expected)
                self.assertNotIn("secret-key", output.getvalue())
                self.assertEqual(json.loads(output.getvalue())["left"]["rows"], 1)

    def test_cli_rejected_input_has_no_partial_summary(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("join_audit.load_csv", side_effect=ValueError("private detail")):
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(["left.csv", "right.csv"])
        self.assertEqual(result, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Input rejected", errors.getvalue())
        self.assertNotIn("private detail", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
