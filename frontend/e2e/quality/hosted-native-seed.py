"""Disposable GH-hosted Windows ONLY: create a real native ORM-backed QA identity.
Not production seed, no mocked HTTP, no second schema, no real platform account.
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))
from sqlalchemy.orm import Session
from app.database import engine
from app.models.organization import Organization
from app.models.user import User
from app.models.customer import Customer
from app.models.role import Role
from app.models.permission import Permission
from app.models.session_to_agent import SessionToAgent, SessionStatus
from app.models.chat_history import ChatHistory

def require():
    if not (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "Windows"
            and os.environ.get("YANCE_QA_ISOLATED") == "1"
            and os.environ.get("YANCE_QA_FIXTURE") == "NATIVE_POSTGRES_AUTH"
            and "127.0.0.1" in os.environ.get("DATABASE_URL", "")
            and "yance_hosted_qa" in os.environ.get("DATABASE_URL", "")):
        raise RuntimeError("QA_SEED_REQUIRES_GITHUB_HOSTED_ISOLATED_NATIVE_POSTGRES")
require()
mode = sys.argv[1]
path = Path(os.environ["RUNNER_TEMP"]) / "yance-hosted-fixture.json"
if mode == "seed":
    unique = uuid.uuid4().hex
    org_id, user_id, customer_id, session_id = [uuid.uuid4() for _ in range(4)]
    with Session(engine) as db:
        org = Organization(id=org_id, name="W373 Native QA Disposable", domain="qa-" + unique + ".invalid")
        db.add(org)
        db.flush()
        role = Role(name="Admin", organization_id=org_id)
        db.add(role)
        db.flush()
        permission = db.query(Permission).filter(Permission.name == "super_admin").first()
        if permission is not None:
            role.permissions.append(permission)
        user = User(id=user_id, email="qa-" + unique + "@example.invalid",
                    full_name="Synthetic Native QA User", organization_id=org_id, role_id=role.id,
                    is_active=True, hashed_password=User.get_password_hash(os.environ["YANCE_QA_SYNTHETIC_PASSWORD"]))
        customer = Customer(id=customer_id, email="customer-" + unique + "@example.invalid",
                            full_name="Synthetic QA Customer", organization_id=org_id,
                            meta_data={"person_profile":{"city":"Berlin"}})
        db.add_all([user, customer])
        db.flush()
        db.add(SessionToAgent(session_id=session_id, user_id=user_id, customer_id=customer_id,
                              organization_id=org_id, status=SessionStatus.OPEN, channel="web"))
        db.flush()
        message = ChatHistory(organization_id=org_id, customer_id=customer_id, user_id=user_id,
                              session_id=session_id, message="Synthetic QA history, local only",
                              message_type="user", attributes={})
        db.add(message)
        db.commit()
        db.refresh(message)
        fixture = {"org":str(org_id),"user":str(user_id),"customer":str(customer_id),
                   "session":str(session_id),"message":str(message.id),
                   "email":user.email}
    path.write_text(json.dumps(fixture,indent=2),encoding="utf8")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"],"a",encoding="utf8") as env:
            for k,v in fixture.items():
                if k in ("email",): continue
                env.write("YANCE_QA_" + {"org":"ORG_ID","user":"USER_ID","customer":"CUSTOMER_ID",
                           "session":"SESSION_ID","message":"MESSAGE_ID"}[k] + "=" + v + "\n")
            env.write("YANCE_QA_AUTH_USER=" + fixture["email"] + "\n")
    print("REAL_NATIVE_ORM_QA_FIXTURE_INSERTED: Customer, User, SessionToAgent, ChatHistory")
elif mode == "readback":
    from sqlalchemy import text
    fixture = json.loads(path.read_text(encoding="utf8"))
    with engine.connect() as connection:
        got = connection.execute(text("""
          SELECT count(*) FROM chat_history h JOIN session_to_agents s ON s.session_id=h.session_id
          JOIN customers c ON c.id=s.customer_id AND c.organization_id=s.organization_id
          JOIN users u ON u.id=h.user_id AND u.organization_id=s.organization_id
          WHERE h.id=:m AND h.session_id=:s AND h.customer_id=:c AND h.organization_id=:o
          AND u.id=:u
        """), {"m":int(fixture["message"]),"s":uuid.UUID(fixture["session"]),
               "c":uuid.UUID(fixture["customer"]),"o":uuid.UUID(fixture["org"]),
               "u":uuid.UUID(fixture["user"])}).scalar_one()
        if got != 1:
            raise RuntimeError("NATIVE_PG_RESTART_JOINED_READBACK_FAILED")
    print("REAL_NATIVE_PG_RESTART_JOINED_READBACK_PASS")
else:
    raise SystemExit("USE: hosted-native-seed.py seed|readback")
