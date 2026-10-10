"""Read a REAL Playwright trace archive using Python's standard ZIP reader.
Diagnostic validator only; never issues a W327 approval or synthetic product PASS.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

def die(code):
    print(code, file=sys.stderr)
    sys.exit(2)

try:
    path = Path(sys.argv[1])
    test_id = sys.argv[2]
    if not re.fullmatch(r"[A-Za-z0-9-]+", test_id):
        die("TRACE_TEST_ID_INVALID")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        names = [e.filename for e in entries]
        if len(names) != len(set(names)) or not entries:
            die("TRACE_EMPTY_OR_DUPLICATE_ZIP_ENTRIES")
        if any(e.is_dir() or e.file_size > 64*1024*1024 or
               e.filename.startswith("/") or "\\" in e.filename or
               ".." in e.filename.split("/") for e in entries):
            die("TRACE_UNSAFE_ZIP_ENTRIES")
        if "test.trace" not in names:
            die("TRACE_REQUIRED_TEST_TRACE_MISSING")
        browser_trace_names = [x for x in names if re.fullmatch(r"\d+-trace\.trace", x)]
        if not browser_trace_names:
            die("TRACE_REQUIRED_BROWSER_TRACE_MISSING")
        def events(name):
            raw = z.read(name)
            if not raw or len(raw) > 64*1024*1024:
                die("TRACE_EVENT_RECORDS_EMPTY_OR_LARGE")
            out = []
            for line in raw.splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, UnicodeError):
                    die("TRACE_INVALID_JSON_EVENTS")
                if not isinstance(obj, dict):
                    die("TRACE_INVALID_EVENT_OBJECT")
                out.append(obj)
            return out
        test_events = events("test.trace")
        all_browser_events = [ev for name in browser_trace_names for ev in events(name)]
        started = {ev.get("callId") for ev in test_events if ev.get("type") == "before"
                   and isinstance(ev.get("callId"), str)}
        finished = {ev.get("callId") for ev in test_events if ev.get("type") == "after"
                    and isinstance(ev.get("callId"), str)}
        if not started.intersection(finished):
            die("TRACE_NO_MATCHED_TEST_ACTIONS")
        if not any(ev.get("type") == "context-options" and
                   ("[" + test_id + "]") in str(ev.get("title", ""))
                   for ev in all_browser_events):
            die("TRACE_BROWSER_TEST_ID_NOT_BOUND")
        if not any(ev.get("type") in ("context-options", "before", "after", "event")
                   for ev in all_browser_events):
            die("TRACE_NO_BROWSER_ACTION_OR_CONTEXT")
        for e in entries:
            try:
                data = z.read(e.filename)
            except (RuntimeError, zipfile.BadZipFile):
                die("TRACE_ZIP_CRC_OR_DECOMPRESSION_INVALID")
            if len(data) != e.file_size:
                die("TRACE_ZIP_SIZE_MISMATCH")
        print("TRACE_ZIP_CONTENT_VALIDATED id=" + test_id)
except (OSError, zipfile.BadZipFile, IndexError, ValueError, EOFError):
    die("TRACE_ZIP_INVALID")
