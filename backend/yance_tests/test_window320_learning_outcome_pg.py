"""W320 physical PostgreSQL proof for the ACTUAL response-outcome function body.

Uses W294's real PostgreSQL FK/tenant schema and loads the deployed function
AST unchanged; the complete ChatterMate model HTTP path is tested separately.
"""
from __future__ import annotations
import ast
import uuid
from pathlib import Path
import unittest

from sqlalchemy import inspect

import test_window294_reply_commitment_pg as w294

source = (Path(__file__).resolve().parents[1] /
          "app/services/yance_reply_runtime.py").read_text(encoding="utf-8")
body = next(node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "finalize_response_outcome")
namespace = {
    "ChatHistory": w294.ChatHistory,
    "SessionToAgent": w294.SessionToAgent,
    "SessionStatus": w294.SessionStatus,
}
exec("from __future__ import annotations\n"+ast.unparse(body), namespace)
finalize_actual_source = namespace["finalize_response_outcome"]


class Window320RealPGOutcomeProof(w294.Window294PostgreSQLProof):
    """Existing 16.15 physical FK fixture with genuine transaction/lock checks."""

    def _accepted(self):
        with self.make_session() as db:
            sent = db.get(w294.ChatHistory, self.bot_id)
            sent.message_type = "agent"
            sent.attributes = {
                "yance_learning": {
                    "source_message_id": self.source_id,
                    "candidate_id": f"{self.source_id}:1",
                    "outcome": "provider_accepted",
                }
            }
            source = db.get(w294.ChatHistory, self.source_id)
            source.attributes = {"yance_reply_evidence": [{
                "candidate_id": f"{self.source_id}:1", "decision": "adopt",
                "sent_message_id": self.bot_id, "do_not_learn": False,
                "outcome": "provider_accepted",
            }]}
            db.commit()

    def _new_user(self, *, attributes=None):
        with self.make_session() as db:
            row = w294.ChatHistory(
                organization_id=self.org, agent_id=self.agent_id,
                customer_id=self.customer_id, session_id=self.session_id,
                message_type="user", message="Real inbound", attributes=attributes or {},
            )
            db.add(row)
            db.commit()
            return row.id

    def test_physical_pg_response_and_duplicate(self):
        self._accepted()
        inbound_id = self._new_user()
        with self.make_session() as db:
            self.assertTrue(finalize_actual_source(db, inbound_id))
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, inbound_id))
            sent = db.get(w294.ChatHistory, self.bot_id)
            src = db.get(w294.ChatHistory, self.source_id)
            self.assertEqual(sent.attributes["yance_learning"]["outcome"], "provider_accepted")
            self.assertEqual(sent.attributes["yance_learning"]["response_message_id"], inbound_id)
            self.assertEqual(src.attributes["yance_reply_evidence"][0]["response_message_id"], inbound_id)
            self.assertNotIn("recipient_delivered", sent.attributes["yance_learning"])

    def test_physical_pg_echo_no_reply_then_accepted_first_real(self):
        self._accepted()
        echo_id = self._new_user(attributes={"provider_echo": True})
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, echo_id))
        real_id = self._new_user()
        with self.make_session() as db:
            self.assertTrue(finalize_actual_source(db, real_id))
        later_id = self._new_user()
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, later_id))
            self.assertFalse(finalize_actual_source(db, echo_id))
            self.assertEqual(db.get(w294.ChatHistory, self.bot_id).attributes["yance_learning"]["response_message_id"], real_id)

    def test_physical_pg_permission_scope_denies_and_closed(self):
        self._accepted()
        incoming = self._new_user()
        with self.make_session() as db:
            session = db.get(w294.SessionToAgent, self.session_id)
            session.status = "closed"
            db.commit()
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, incoming))
        with self.make_session() as db:
            session = db.get(w294.SessionToAgent, self.session_id)
            session.status = "open"
            sent = db.get(w294.ChatHistory, self.bot_id)
            sent.organization_id = uuid.uuid4()  # tenant scope conflict; no artificial FK break
            db.commit()
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, incoming))
            self.assertNotIn("response_message_id", db.get(w294.ChatHistory,self.bot_id).attributes["yance_learning"])

    def test_physical_pg_stale_generation_and_no_response(self):
        self._accepted()
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, self.source_id))
            sent = db.get(w294.ChatHistory, self.bot_id)
            self.assertNotIn("response_message_id", sent.attributes["yance_learning"])
        first = self._new_user()
        newer = self._new_user()
        with self.make_session() as db:
            self.assertFalse(finalize_actual_source(db, first))
            self.assertFalse(finalize_actual_source(db, newer))
            self.assertNotIn("response_message_id", db.get(w294.ChatHistory,self.bot_id).attributes["yance_learning"])


if __name__ == "__main__":
    unittest.main()
