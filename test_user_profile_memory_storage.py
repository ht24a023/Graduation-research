import os
import tempfile
import unittest
from unittest.mock import patch

import models.user_profile_memory as user_profile_memory


class UserProfileMemoryStorageTests(unittest.TestCase):
    def test_ensure_memory_stores_creates_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_profile_memory, "_PROFILE_PATH", os.path.join(tmpdir, "user_profile.json")), \
                patch.object(user_profile_memory, "_NOTES_PATH", os.path.join(tmpdir, "user_notes.json")), \
                patch.object(user_profile_memory, "_KEEP_REQUESTS_PATH", os.path.join(tmpdir, "user_keep_requests.json")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DIR", os.path.join(tmpdir, "documents")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DB_PATH", os.path.join(tmpdir, "documents_db.txt")), \
                patch.object(user_profile_memory, "_DOC_SESSION_PATH", os.path.join(tmpdir, "document_session.json")), \
                patch.object(user_profile_memory, "_VIEW_PATH", os.path.join(tmpdir, "user_memory_view.json")):

                status = user_profile_memory.ensure_memory_stores()

                self.assertTrue(status["exists"]["documents_db"])
                self.assertTrue(status["exists"]["documents_dir"])
                self.assertEqual(status["counts"]["documents_db_rows"], 0)

    def test_ensure_memory_stores_repairs_missing_db_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_profile_memory, "_PROFILE_PATH", os.path.join(tmpdir, "user_profile.json")), \
                patch.object(user_profile_memory, "_NOTES_PATH", os.path.join(tmpdir, "user_notes.json")), \
                patch.object(user_profile_memory, "_KEEP_REQUESTS_PATH", os.path.join(tmpdir, "user_keep_requests.json")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DIR", os.path.join(tmpdir, "documents")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DB_PATH", os.path.join(tmpdir, "documents_db.txt")), \
                patch.object(user_profile_memory, "_DOC_SESSION_PATH", os.path.join(tmpdir, "document_session.json")), \
                patch.object(user_profile_memory, "_VIEW_PATH", os.path.join(tmpdir, "user_memory_view.json")):

                created = user_profile_memory.create_document_item("自己PR", "本文テスト")
                self.assertTrue(created["ok"])

                os.remove(user_profile_memory._TEXT_DOCS_DB_PATH)
                status = user_profile_memory.ensure_memory_stores()

                self.assertGreaterEqual(status.get("db_repaired_rows", 0), 1)
                self.assertEqual(status["counts"]["documents_db_rows"], 1)


if __name__ == "__main__":
    unittest.main()
