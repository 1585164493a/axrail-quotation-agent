"""存储层测试（v3）：内容寻址、实体血缘、stage 可重建。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.identity import resolve_customer  # noqa: E402
from quotation_agent.ingest.email_reader import parse_headers, read_bytes  # noqa: E402
from quotation_agent.store.db import (  # noqa: E402
    INLINE_MAX_BYTES,
    SCHEMA_META,
    SCHEMA_VERSION,
    connect,
    finish_run,
    get_blob,
    init_db,
    put_blob,
    save_blocks,
    save_raw_email,
    sha256_file,
    stage_envelope,
    start_run,
    summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TMP = ROOT / ".testtmp"
STAGING = TMP / "store-artifacts"


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        STAGING.mkdir(parents=True, exist_ok=True)
        self.db_path = TMP / "test_store.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def ingest(self, filename: str) -> dict:
        path = FIXTURES / filename
        data = path.read_bytes()
        headers = parse_headers(data)
        raw_id = save_raw_email(self.conn, data, headers=headers, filename=filename, source_ref="test")
        run_id = start_run(self.conn, "email_reader", "1", raw_email_id=raw_id)
        envelope = read_bytes(data, filename, STAGING)
        stage_id = stage_envelope(self.conn, raw_id, envelope, run_id=run_id, resolution=resolve_customer(envelope))
        finish_run(self.conn, run_id, "ok")
        return {"raw_id": raw_id, "run_id": run_id, "stage_id": stage_id, "envelope": envelope}

    def test_same_email_imported_twice_is_one_row(self) -> None:
        """同一封邮件导入两次：原始记录只有一条，blob 只有一份。"""
        path = FIXTURES / "01_rfq_body_only.eml"
        data = path.read_bytes()
        headers = parse_headers(data)

        first = save_raw_email(self.conn, data, headers=headers, filename="a.eml")
        second = save_raw_email(self.conn, data, headers=headers, filename="a-copy.eml")

        self.assertEqual(first, second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM raw_email").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM blob_store").fetchone()[0], 1)

    def test_two_different_emails_are_two_rows(self) -> None:
        """两份不同的邮件（哪怕主题相同）必须是两条记录。"""
        self.ingest("01_rfq_body_only.eml")
        self.ingest("02_rfq_full_attachments.eml")
        rows = self.conn.execute("SELECT message_id FROM raw_email ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["message_id"], rows[1]["message_id"])

    def test_every_column_has_a_source(self) -> None:
        """元数据表里每个字段都必须写明"值从哪来"，不能有空行。"""
        missing = self.conn.execute(
            "SELECT table_name, column_name FROM schema_meta WHERE source IS NULL OR source = ''"
        ).fetchall()
        self.assertEqual(missing, [], f"缺来源说明：{[(m[0], m[1]) for m in missing]}")
        # 来源要具体，不能只有"未知"
        vague = self.conn.execute(
            "SELECT table_name, column_name, source FROM schema_meta WHERE source IN ('未知', '?', 'unknown')"
        ).fetchall()
        self.assertEqual(vague, [])

    def test_raw_email_carries_envelope_fields(self) -> None:
        """不解析正文也要能回答：谁发的、什么主题、谁收的、什么时候发的。"""
        info = self.ingest("01_rfq_body_only.eml")
        row = self.conn.execute("SELECT * FROM raw_email WHERE id=?", (info["raw_id"],)).fetchone()

        self.assertEqual(row["subject"], "RFQ-2026-118 - CNC parts, delivery in 6 weeks")
        self.assertEqual(row["sender_name"], "Alex Tan")
        self.assertEqual(row["sender_email"], "buyer@example-customer.test")
        self.assertIn("sales@example-cnc-shop.test", row["to_recipients"])
        self.assertTrue(row["sent_at"].startswith("2026-11-02T09:14"))
        self.assertIsNotNone(row["message_id"])
        self.assertIsNotNone(row["received_at"])

    def test_raw_attachment_has_openable_path(self) -> None:
        """附件在原始层就要有落盘路径，拿到能直接打开。"""
        info = self.ingest("02_rfq_full_attachments.eml")
        rows = self.conn.execute(
            "SELECT filename, stored_path, ordinal FROM raw_attachment WHERE raw_email_id=? ORDER BY ordinal",
            (info["raw_id"],),
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["ordinal"] for r in rows], [1, 2, 3])
        for r in rows:
            self.assertTrue(r["stored_path"], f"{r['filename']} 缺落盘路径")
            self.assertTrue(Path(r["stored_path"]).exists(), r["stored_path"])

    def test_layers_and_layers_meta(self) -> None:
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for expected in (
            "blob_store", "raw_email", "raw_attachment", "parse_run",
            "stage_email", "stage_attachment", "stage_block", "mart_rfq",
            "schema_meta", "db_meta",
        ):
            self.assertIn(expected, tables)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0], len(SCHEMA_META))
        layers = {r[0] for r in self.conn.execute("SELECT DISTINCT layer FROM schema_meta")}
        self.assertEqual(layers, {"blob", "raw", "run", "stage", "mart", "meta"})
        self.assertEqual(
            self.conn.execute("SELECT value FROM db_meta WHERE key='schema_version'").fetchone()[0], SCHEMA_VERSION
        )

    def test_blob_is_content_addressed(self) -> None:
        """同一份字节放两次：blob 只有一行；邮件实体也只有一个（幂等）。"""
        data = b"same bytes"
        h1 = put_blob(self.conn, data)
        h2 = put_blob(self.conn, data)
        self.assertEqual(h1, h2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM blob_store").fetchone()[0], 1)
        self.assertEqual(get_blob(self.conn, h1), data)

        e1 = save_raw_email(self.conn, data, filename="a.eml")
        e2 = save_raw_email(self.conn, data, filename="b.eml")
        self.assertEqual(e1, e2, "同一封邮件重复导入只留一条原始记录")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM raw_email").fetchone()[0], 1)

    def test_attachment_entities_are_per_email(self) -> None:
        """同一份附件出现在两封邮件里：blob 一份，raw_attachment 两条。"""
        from quotation_agent.store.db import save_raw_attachment

        payload = b"PK\x03\x04shared-attachment"
        e1 = save_raw_email(self.conn, b"email one", filename="one.eml")
        e2 = save_raw_email(self.conn, b"email two", filename="two.eml")

        a1 = save_raw_attachment(self.conn, e1, payload, "part_list.xlsx")
        a2 = save_raw_attachment(self.conn, e2, payload, "part_list.xlsx")
        self.assertNotEqual(a1, a2, "附件实体按所属邮件分别记账")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM raw_attachment").fetchone()[0], 2
        )
        blobs = self.conn.execute(
            "SELECT COUNT(*) FROM blob_store WHERE sha256 = ?", (put_blob(self.conn, payload),)
        ).fetchone()[0]
        self.assertEqual(blobs, 1, "字节仍然只有一份")

    def test_large_blob_goes_to_file(self) -> None:
        """超过内联阈值必须落文件，库里只留路径。"""
        big = b"x" * (INLINE_MAX_BYTES + 1)
        with self.assertRaises(ValueError):
            put_blob(self.conn, big)

        target = TMP / "big.bin"
        target.write_bytes(big)
        digest = put_blob(self.conn, big, file_path=str(target))
        row = self.conn.execute("SELECT storage, content, file_path FROM blob_store WHERE sha256=?", (digest,)).fetchone()
        self.assertEqual(row["storage"], "file")
        self.assertIsNone(row["content"])
        self.assertEqual(get_blob(self.conn, digest), big)

    def test_attachment_has_explicit_parent(self) -> None:
        info = self.ingest("02_rfq_full_attachments.eml")

        atts = self.conn.execute(
            "SELECT a.*, b.sha256 AS blob FROM raw_attachment a JOIN blob_store b ON b.sha256 = a.blob_sha256 "
            "WHERE a.raw_email_id = ? ORDER BY a.filename",
            (info["raw_id"],),
        ).fetchall()
        self.assertEqual(len(atts), 3)
        self.assertEqual(
            [a["filename"] for a in atts],
            ["drawing_CVR-310_RevB.pdf", "part_list.xlsx", "part_spec.pptx"],
        )
        for att in atts:
            self.assertEqual(att["raw_email_id"], info["raw_id"], "附件必须挂在邮件下")
            self.assertGreater(att["size_bytes"], 0)

    def test_stage_points_back_to_raw(self) -> None:
        info = self.ingest("02_rfq_full_attachments.eml")
        row = self.conn.execute("SELECT * FROM stage_email WHERE id=?", (info["stage_id"],)).fetchone()
        self.assertEqual(row["raw_email_id"], info["raw_id"])
        self.assertEqual(row["run_id"], info["run_id"])
        self.assertEqual(row["customer_name"], "Example Customer Sdn Bhd")

        stage_atts = self.conn.execute(
            "SELECT * FROM stage_attachment WHERE stage_email_id=?", (info["stage_id"],)
        ).fetchall()
        self.assertEqual(len(stage_atts), 3)
        for sa in stage_atts:
            self.assertIsNotNone(sa["raw_attachment_id"], "stage 附件要指回 raw 附件")

    def test_reparse_creates_second_stage_but_not_second_raw(self) -> None:
        info = self.ingest("01_rfq_body_only.eml")
        before = summary(self.conn)

        run2 = start_run(self.conn, "email_reader", "2", raw_email_id=info["raw_id"])
        stage2 = stage_envelope(
            self.conn, info["raw_id"], info["envelope"], run_id=run2, resolution=resolve_customer(info["envelope"])
        )
        finish_run(self.conn, run2, "ok")

        after = summary(self.conn)
        self.assertEqual(after["raw_email"], before["raw_email"], "原件不重复")
        self.assertEqual(after["stage_email"], before["stage_email"] + 1)
        self.assertEqual(after["parse_run"], before["parse_run"] + 1)
        self.assertNotEqual(stage2, info["stage_id"])

    def test_blocks_link_attachment(self) -> None:
        info = self.ingest("02_rfq_full_attachments.eml")
        att = self.conn.execute(
            "SELECT id FROM stage_attachment WHERE stage_email_id=? AND filename='part_list.xlsx'", (info["stage_id"],)
        ).fetchone()

        n = save_blocks(
            self.conn, info["stage_id"], att["id"],
            [
                {"block_type": "table_row", "locator": "Part list!A5", "ordinal": 1,
                 "row": {"Line": 1, "Part no": "BRK-100", "Qty": 500}},
                {"block_type": "text", "locator": "Part list!A9", "ordinal": 2,
                 "value": "Lines 4-5: see the part-spec slides."},
            ],
            run_id=info["run_id"],
        )
        self.assertEqual(n, 2)
        rows = self.conn.execute(
            "SELECT * FROM stage_block WHERE stage_attachment_id=? ORDER BY ordinal", (att["id"],)
        ).fetchall()
        self.assertIn("BRK-100", rows[0]["row_json"])

    def test_mart_empty_until_step3(self) -> None:
        self.ingest("01_rfq_body_only.eml")
        self.assertEqual(summary(self.conn)["mart_rfq"], 0)


if __name__ == "__main__":
    unittest.main()
