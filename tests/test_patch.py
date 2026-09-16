"""Day 15: Apply Patch 测试。"""
import pytest
from sandbox.patch import PatchParser, PatchApplier


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    return tmp_path


def test_parse_add():
    parser = PatchParser()
    text = """*** Begin Patch
*** Add File: new.py
+line 1
+line 2
*** End Patch"""
    hunks = parser.parse(text)
    assert len(hunks) == 1
    assert hunks[0].path == "new.py"
    assert "line 1" in hunks[0].new_content


def test_parse_update():
    parser = PatchParser()
    text = """*** Begin Patch
*** Update File: a.py
@@ def foo():
-    return 1
+    return 2
*** End Patch"""
    hunks = parser.parse(text)
    assert len(hunks) == 1
    assert hunks[0].path == "a.py"
    assert len(hunks[0].hunks) == 1


def test_parse_delete():
    parser = PatchParser()
    text = """*** Begin Patch
*** Delete File: gone.py
*** End Patch"""
    hunks = parser.parse(text)
    assert hunks[0].path == "gone.py"


def test_apply_update(ws):
    parser = PatchParser()
    applier = PatchApplier(ws)
    text = """*** Begin Patch
*** Update File: a.py
@@ def foo():
 def foo():
-    return 1
+    return 2
*** End Patch"""
    hunks = parser.parse(text)
    ok, msgs = applier.apply(hunks)
    assert ok
    assert "return 2" in (ws / "a.py").read_text()


def test_apply_precheck_fails_on_missing(ws):
    parser = PatchParser()
    applier = PatchApplier(ws)
    text = """*** Begin Patch
*** Update File: nonexistent.py
@@
-old
+new
*** End Patch"""
    hunks = parser.parse(text)
    ok, msgs = applier.apply(hunks)
    assert not ok


def test_apply_atomic_rollback(ws):
    """第二个文件失败时第一个文件回滚。"""
    parser = PatchParser()
    applier = PatchApplier(ws)
    text = """*** Begin Patch
*** Update File: a.py
@@ def foo():
 def foo():
-    return 1
+    return 2
*** Update File: nonexistent.py
@@
-x
+y
*** End Patch"""
    hunks = parser.parse(text)
    ok, msgs = applier.apply(hunks)
    assert not ok
    # a.py 未被修改
    assert "return 1" in (ws / "a.py").read_text()