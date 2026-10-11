"""W449: protect native inbox status filtering against PostgreSQL enum-name mismatch."""
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy.dialects import postgresql
from app.repositories.chat import ChatRepository


def compile_status_filters(status: str):
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    for method in ('join','outerjoin','filter','group_by','order_by','offset','limit','having'):
        getattr(query,method).return_value = query
    query.all.return_value = []
    repo = ChatRepository(db)
    with patch.object(repo,'get_last_messages',return_value={}):
        assert repo.get_recent_chats(status=status) == []
    return [str(call.args[0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={'literal_binds':True}
    )) for call in query.filter.call_args_list]


@pytest.mark.parametrize(('status','wanted'),[
    ('open','OPEN'),
    ('transferred','TRANSFERRED'),
    ('closed','CLOSED'),
    ('open,transferred','OPEN'),
    ('OPEN, TRANSFERRED','TRANSFERRED'),
])
def test_recent_chat_status_binds_native_sqlalchemy_enum_name(status,wanted):
    predicates=compile_status_filters(status)
    matching=[p for p in predicates if 'session_to_agents.status' in p]
    assert len(matching)==1, matching
    assert f"'{wanted}'" in matching[0], matching[0]


def test_recent_chat_all_does_not_add_status_constraint():
    predicates=compile_status_filters('all')
    assert not any('session_to_agents.status' in p for p in predicates)


def test_recent_chat_unknown_state_fails_closed_without_database_query():
    with pytest.raises(ValueError):
        compile_status_filters('open,incorrect-state')
