"""
Unit tests for the Feature 2 interface methods — M-02-37 to M-02-39.

These three live in app.py, which is a Streamlit script: importing it runs the
whole page. They are reached by executing that source into a namespace of this
module's own, with Streamlit and the third-party libraries Feature 3 pulls in
replaced by stubs. The functions under test are the real ones; only what they
draw onto is stubbed.

The Streamlit stub records every call, so a test can assert what the function
put on the page rather than merely that it did not raise. That distinction
matters: a render function that silently draws nothing passes a smoke test and
fails the requirement.

Test identifiers follow UT-2-mm-nnn, where mm is the method number.
"""

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_match                      # installs the shared fake database
from f2_helpers import cv_record, write_cv_registry
from test_match import _DB

import cv_data_adapter


class _Stop(Exception):
    """Raised in place of st.stop(), which halts a Streamlit script."""


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StreamlitStub(types.ModuleType):
    """
    Stands in for streamlit and records what was drawn.

    Every unknown attribute becomes a recorder, so the stub does not need
    updating each time app.py uses another Streamlit call.
    """

    def __init__(self):
        super().__init__("streamlit")
        self.calls = []
        # Streamlit exposes these as data, not callables; leaving them to
        # __getattr__ hands app.py a function where it expects a mapping.
        self.session_state = {}
        self.query_params = {}
        self.secrets = {}
        self.sidebar = _Ctx()

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "stop":
                raise _Stop()
            if name in ("spinner", "container", "expander", "form", "status"):
                return _Ctx()
            if name == "columns":
                count = args[0] if args else 1
                return [_Ctx() for _ in
                        range(count if isinstance(count, int) else len(count))]
            if name in ("cache_resource", "cache_data"):
                return lambda fn: fn
            if name == "file_uploader":
                return None
            return None
        return record

    # helpers for the assertions ------------------------------------
    def reset(self):
        self.calls = []

    def text(self, *names):
        """Everything drawn by the named calls, joined."""
        wanted = names or ("markdown", "write", "caption", "error", "warning",
                           "info", "success", "subheader", "title")
        out = []
        for name, args, kwargs in self.calls:
            if name in wanted:
                out.extend(str(a) for a in args)
                out.extend(str(v) for v in kwargs.values())
        return "\n".join(out)

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


_ST = StreamlitStub()
sys.modules["streamlit"] = _ST

for _name, _attrs in [
        ("openai", {"OpenAI": lambda **k: None, "AsyncOpenAI": lambda **k: None}),
        ("pikepdf", {"open": lambda *a, **k: None, "PdfError": Exception}),
        ("PyPDF2", {"PdfReader": object}),
        ("tqdm", {"tqdm": lambda x, **k: x}),
        ("sentence_transformers", {"SentenceTransformer": object}),
        ("admin", {"show_admin_page": lambda *a, **k: None})]:
    _module = types.ModuleType(_name)
    for _k, _v in _attrs.items():
        setattr(_module, _k, _v)
    sys.modules[_name] = _module


# Imported only now: cv_upload pulls in PyPDF2 and pikepdf, which the stubs
# above supply. Importing it with the other modules at the top of the file
# would run before those stubs are registered.
import cv_upload


def _app_path():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "app.py")
    return path if os.path.isfile(path) else os.path.join(here, "..", "app.py")


def _load_app():
    """
    Executes app.py and returns its namespace.

    app.py draws the page at module level, so a plain import would run the
    whole thing and, with no file uploaded, end at st.stop(). That is
    tolerated here: the functions under test are defined well before the page
    body, so they are in the namespace either way.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "app.py")
    if not os.path.isfile(path):
        path = os.path.join(here, "..", "app.py")
    namespace = {"__name__": "app_under_test", "__file__": os.path.abspath(path)}
    try:
        with open(path, encoding="utf-8") as handle:
            exec(compile(handle.read(), path, "exec"), namespace)
    except _Stop:
        pass
    return namespace


APP = _load_app()


class InterfaceTestCase(unittest.TestCase):

    def setUp(self):
        self.st = _ST
        self.st.reset()
        self.st.session_state.clear()
        self.db = _DB
        for table in (self.db.listings, self.db.enrichment,
                      self.db.matches, self.db.ownership):
            table.clear()
        self.db.fail_on = None

        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = os.path.join(self.tmp.name, "cvs.json")
        # Both stores are pointed at the fixture. cv_data_adapter is what
        # Feature 2 reads; cv_upload.CVS_REGISTRY_FILE is what Feature 3's
        # embed.displayExtractedCVInfo reads, and M-02-37 goes through that.
        self._original = cv_data_adapter.CV_REGISTRY_FILE
        self._original_f3 = cv_upload.CVS_REGISTRY_FILE
        cv_data_adapter.CV_REGISTRY_FILE = self.registry
        cv_upload.CVS_REGISTRY_FILE = self.registry
        write_cv_registry(self.registry, [cv_record(
            "cv-test-001",
            skills=[{"skill_name": "Python"}, {"skill_name": "Teamwork"}],
            education=[{"institution": "Chiang Mai University",
                        "degree": "Bachelor of Science in Software Engineering"}],
            work_experience=[{"company": "ACME", "position": "Developer",
                              "start_date": "2022", "end_date": "2025"}])])

    def tearDown(self):
        cv_data_adapter.CV_REGISTRY_FILE = self._original
        cv_upload.CVS_REGISTRY_FILE = self._original_f3
        self.tmp.cleanup()


# ---------------------------------------------------------------------
# UT-2-37 — M-02-37 renderExtractedInfo
# ---------------------------------------------------------------------

class TestRenderExtractedInfo(InterfaceTestCase):

    def test_ut_2_37_001_draws_the_extracted_skills(self):
        APP["render_extracted_info"]("cv-test-001")
        self.assertIn("Python", self.st.text())

    def test_ut_2_37_002_draws_the_education_and_experience(self):
        APP["render_extracted_info"]("cv-test-001")
        drawn = self.st.text()
        self.assertIn("Chiang Mai University", drawn)
        self.assertIn("Developer", drawn)

    def test_ut_2_37_003_something_is_actually_drawn(self):
        # A render function that silently draws nothing would pass a test that
        # only checked it did not raise.
        APP["render_extracted_info"]("cv-test-001")
        self.assertTrue(self.st.calls)

    def test_ut_2_37_004_returns_the_skill_entries_for_reuse(self):
        # Returns the entries as stored, not bare names — the caller reads
        # skill_name off each one.
        skills = APP["render_extracted_info"]("cv-test-001")
        names = [s.get("skill_name") if isinstance(s, dict) else s
                 for s in (skills or [])]
        self.assertIn("Python", names)


# ---------------------------------------------------------------------
# UT-2-38 — M-02-38 renderMatches
# ---------------------------------------------------------------------

class TestRenderMatches(InterfaceTestCase):

    def _match(self):
        self.db.add_listing("L1", title="Backend Developer", company="ACME",
                            location="Chiang Mai", skills=["Python"])
        import match_service
        match_service.match_cv_against_listings("cv-test-001")

    def test_ut_2_38_001_draws_a_card_for_each_match(self):
        self._match()
        self.st.reset()
        APP["render_matches"]("cv-test-001")
        self.assertIn("Backend Developer", self.st.text())

    def test_ut_2_38_002_card_carries_the_fields_srs_058_lists(self):
        self._match()
        self.st.reset()
        APP["render_matches"]("cv-test-001")
        drawn = self.st.text()
        for field in ("Backend Developer", "ACME", "Chiang Mai"):
            self.assertIn(field, drawn)

    def test_ut_2_38_003_draws_the_matched_skill_tags(self):
        self._match()
        self.st.reset()
        APP["render_matches"]("cv-test-001")
        self.assertIn("Python", self.st.text())

    def test_ut_2_38_004_no_listings_reports_it_rather_than_drawing_nothing(self):
        # SRS-062: an empty result is a state to report, not a blank page.
        APP["render_matches"]("cv-test-001")
        self.assertTrue(self.st.calls)

    def test_ut_2_38_005_shows_the_match_score(self):
        self._match()
        self.st.reset()
        APP["render_matches"]("cv-test-001")
        self.assertRegex(self.st.text(), r"\d\.\d{3}")


# ---------------------------------------------------------------------
# UT-2-39 — M-02-39 showMatchingError
# ---------------------------------------------------------------------

class TestShowMatchingError(InterfaceTestCase):

    def test_ut_2_39_001_shows_the_reupload_message_for_corrupted_cv_data(self):
        APP["_show_matching_error"](
            cv_data_adapter.CVDataCorruptedException("unreadable"))
        self.assertIn("re-upload", self.st.text().lower())

    def test_ut_2_39_002_shows_a_message_for_a_calculation_failure(self):
        import match_service
        APP["_show_matching_error"](
            match_service.MatchingCalculationException("boom"))
        self.assertTrue(self.st.text().strip())

    def test_ut_2_39_003_does_not_leak_a_traceback(self):
        import match_service
        APP["_show_matching_error"](
            match_service.MatchingCalculationException(
                "Traceback (most recent call last): File app.py line 1"))
        self.assertNotIn("traceback", self.st.text().lower())

    def test_ut_2_39_004_an_unforeseen_error_still_produces_a_message(self):
        APP["_show_matching_error"](RuntimeError("something unexpected"))
        self.assertTrue(self.st.text().strip())

    def test_ut_2_39_005_drawn_as_an_error_not_as_body_text(self):
        APP["_show_matching_error"](RuntimeError("x"))
        self.assertTrue(self.st.named("error") or self.st.named("warning"))



# ---------------------------------------------------------------------
# UT-2-40 — M-02-40 transmitCVForExtraction
# ---------------------------------------------------------------------

class _StubCompletions:
    """Stands in for client.chat.completions, recording what was sent."""

    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.sent.append(kwargs)
        if isinstance(self.owner.reply, Exception):
            raise self.owner.reply
        message = types.SimpleNamespace(content=self.owner.reply)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)])


class _StubOpenAI:
    """
    Stands in for the OpenAI client.

    The provider is the one thing these tests must not actually reach: a real
    call costs money, needs a key, and would make the result depend on what a
    model happened to return that day. The stub records the request instead,
    so a test can assert what was sent as well as what came back.
    """

    def __init__(self, owner):
        self.owner = owner
        self.chat = types.SimpleNamespace(completions=_StubCompletions(owner))


class TestTransmitCVForExtraction(InterfaceTestCase):

    GOOD = json.dumps({
        "skills": [{"skill_name": "Python", "proficiency_level": None}],
        "education": [{"institution": "CMU", "degree": "BSc Computer Science",
                       "start_year": 2022, "end_year": 2026}],
        "work_experience": [{"company": "ACME", "position": "Developer",
                             "start_year": 2024, "end_year": None}],
    })

    def setUp(self):
        super().setUp()
        self.sent = []
        self.reply = self.GOOD
        self._original = APP["OpenAI"]
        APP["OpenAI"] = lambda **kwargs: _StubOpenAI(self)

    def tearDown(self):
        APP["OpenAI"] = self._original
        super().tearDown()

    def _call(self, text="Panuwat Songkram, Python developer"):
        return APP["_extract_structured_info"]("cv-test-001", text)

    def test_ut_2_40_001_returns_the_three_categories(self):
        result = self._call()
        self.assertEqual(result.skills, [{"skill_name": "Python",
                                          "proficiency_level": None}])
        self.assertEqual(len(result.education), 1)
        self.assertEqual(len(result.workExperience), 1)

    def test_ut_2_40_002_the_cv_text_is_sent_to_the_provider(self):
        self._call("Panuwat Songkram, Python developer")
        prompt = self.sent[0]["messages"][-1]["content"]
        self.assertIn("Panuwat Songkram", prompt)

    def test_ut_2_40_003_only_the_leading_portion_is_sent(self):
        # A long CV must not send an unbounded prompt: cost and latency scale
        # with the text, and the cap is what keeps one CV comparable to another.
        self._call("A" * 9000)
        prompt = self.sent[0]["messages"][-1]["content"]
        self.assertLess(prompt.count("A"), 9000)

    def test_ut_2_40_004_skills_are_requested_as_objects_not_names(self):
        # AIExtractionResult declares list[dict] and M-02-03 reads skill_name;
        # a prompt asking for bare strings would satisfy neither.
        self._call()
        prompt = self.sent[0]["messages"][-1]["content"]
        self.assertIn("skill_name", prompt)

    def test_ut_2_40_005_a_reply_wrapped_in_code_fences_is_accepted(self):
        self.reply = "```json\n" + self.GOOD + "\n```"
        self.assertEqual(len(self._call().skills), 1)

    def test_ut_2_40_006_categories_the_provider_omits_come_back_empty(self):
        self.reply = json.dumps({"skills": []})
        result = self._call()
        self.assertEqual(result.skills, [])
        self.assertEqual(result.education, [])
        self.assertEqual(result.workExperience, [])

    def test_ut_2_40_007_a_reply_that_is_not_json_raises(self):
        self.reply = "the provider was unavailable"
        with self.assertRaises(ValueError):
            self._call()

    def test_ut_2_40_008_a_provider_failure_propagates(self):
        # Not swallowed: M-03-08 must not receive an empty result that looks
        # like a CV with nothing in it when the call never succeeded.
        self.reply = RuntimeError("connection refused")
        with self.assertRaises(RuntimeError):
            self._call()




# ---------------------------------------------------------------------
# UT-2-41 — M-02-41 displayUploadNotification
# ---------------------------------------------------------------------

class TestUploadSuccessNotification(InterfaceTestCase):
    """
    SRS-050 says the notification appears *upon CV information retrieval
    completion*, so the thing to prove is the tie between the two: it shows
    when the chain finished, and does not show when it did not.

    The page body is re-executed with a file waiting in the uploader and the
    Feature 3 chain replaced, so the notification is produced by the real page
    logic rather than asserted against a copy of it.
    """

    class _File:
        name = "CV_Panuwat_Songkram.pdf"

    def _run_page(self, chain_ok=True):
        import cv_upload as cu
        import embed as eb
        saved = {
            "uploadCVFile": cu.uploadCVFile,
            "displayUploadFeedback": cu.displayUploadFeedback,
            "extractTextFromCV": cu.extractTextFromCV,
            "validateExtractionResult": cu.validateExtractionResult,
            "storeExtractedCVInfo": cu.storeExtractedCVInfo,
            "detectSensitiveInfo": eb.detectSensitiveInfo,
            "maskSensitiveInfo": eb.maskSensitiveInfo,
            "verifySensitiveDataProtection": eb.verifySensitiveDataProtection,
        }
        text = "Panuwat Songkram Python developer" * 3
        cu.uploadCVFile = lambda f, j: {"cvFileId": "cv-test-001",
                                        "fileName": f.name}
        cu.displayUploadFeedback = lambda *a, **k: None
        cu.extractTextFromCV = lambda cv: text if chain_ok else ""
        cu.validateExtractionResult = lambda r: None
        cu.storeExtractedCVInfo = lambda cv, r: None
        # The real detector returns an object with named fields; process_cv
        # reads four of them to build the masked-data summary.
        eb.detectSensitiveInfo = lambda t: types.SimpleNamespace(
            emailOriginal=None, phoneOriginal=None,
            addressOriginal=None, identificationOriginal=None)
        eb.maskSensitiveInfo = lambda t, d: types.SimpleNamespace(sanitizedText=t)
        eb.verifySensitiveDataProtection = lambda t, d: None

        # The page reaches the AI provider through M-02-40; give it a stub
        # that replies properly, so this test fails only on the notification.
        self.sent, self.reply = [], json.dumps({
            "skills": [{"skill_name": "Python", "proficiency_level": None}],
            "education": [], "work_experience": []})
        openai_module = sys.modules["openai"]
        saved_openai = openai_module.OpenAI
        openai_module.OpenAI = lambda **kwargs: _StubOpenAI(self)

        self.st.file_uploader = lambda *a, **k: self._File()
        try:
            namespace = {"__name__": "app_upload_test",
                         "__file__": os.path.abspath("app.py")}
            src = open(_app_path(), encoding="utf-8").read()
            try:
                exec(compile(src, "app.py", "exec"), namespace)
            except _Stop:
                pass
            except Exception:
                pass          # a later stage of the page is not under test
        finally:
            for name, fn in saved.items():
                setattr(cu if hasattr(cu, name) else eb, name, fn)
            openai_module.OpenAI = saved_openai
            del self.st.file_uploader

    def test_ut_2_41_001_notification_shown_when_retrieval_completes(self):
        self._run_page(chain_ok=True)
        shown = [a for n, args, _ in self.st.calls if n == "success" for a in args]
        self.assertTrue(any("Upload successful" in str(a) for a in shown))

    def test_ut_2_41_002_no_notification_when_retrieval_fails(self):
        # An unreadable PDF yields no text, so the chain stops before the CV
        # information exists. A notification here would tell the Jobseeker
        # their CV was read when it was not.
        self._run_page(chain_ok=False)
        shown = [a for n, args, _ in self.st.calls if n == "success" for a in args]
        self.assertFalse(any("Upload successful" in str(a) for a in shown))



    def test_ut_2_41_003_the_notification_names_the_file(self):
        """
        M-02-41 draws the message. Calling it directly, rather than through
        the page body, is what having a function makes possible: the other
        two tests prove when it is called, this one proves what it says.
        """
        self.st.reset()
        APP["display_upload_notification"]("CV_Panuwat_Songkram.pdf")
        shown = [a for n, args, _ in self.st.calls if n == "success" for a in args]
        self.assertTrue(any("Upload successful" in str(a) for a in shown))
        self.assertTrue(any("CV_Panuwat_Songkram.pdf" in str(a) for a in shown))


if __name__ == "__main__":
    unittest.main(verbosity=2)
