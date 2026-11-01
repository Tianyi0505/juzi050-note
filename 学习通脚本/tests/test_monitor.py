import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
MONITOR_PATH = SCRIPT_DIR / "monitor.py"


def make_notice(identity, title, kind="work", isread="0", reminder=False):
    item = {
        "uuid": identity,
        "title": title,
        "insertTime": "1700000000000",
        "isread": isread,
        "attachment": json.dumps(
            [
                {
                    "att_web": {
                        "url": "https://example.invalid/work/view?id={}".format(identity),
                        "examOrWork": kind,
                    }
                }
            ]
        ),
    }
    if reminder:
        item["extendParam"] = {
            "cparams": json.dumps({"funConfig": {"funTag": 1}})
        }
    return item


class MonitorBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="learning-script-verify-")
        cls.addClassCleanup(cls.temp_dir.cleanup)
        isolated_script_dir = Path(cls.temp_dir.name) / "学习通脚本"
        isolated_script_dir.mkdir()
        isolated_monitor = isolated_script_dir / "monitor.py"
        shutil.copyfile(MONITOR_PATH, isolated_monitor)

        spec = importlib.util.spec_from_file_location(
            "learning_monitor_under_test", str(isolated_monitor)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载隔离的 monitor.py 副本")
        monitor = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = monitor
        spec.loader.exec_module(monitor)
        cls.monitor = monitor

    def test_notices_parse_new_accepts_notice_list_and_cursor_shapes(self):
        notices = [{"uuid": "notice-1"}]
        self.assertEqual(
            self.monitor.parse_new({"objs": notices, "lastValue": "cursor-1"}),
            (notices, "cursor-1"),
        )
        self.assertEqual(
            self.monitor.parse_new({"objs": "cursor-2", "notices": notices}),
            (notices, "cursor-2"),
        )

    def test_notices_get_notice_list_accepts_list_wrappers(self):
        notices = [{"uuid": "notice-1"}]
        self.assertEqual(self.monitor.get_notice_list({"notices": notices}), notices)
        self.assertEqual(
            self.monitor.get_notice_list({"notices": {"list": notices}}), notices
        )

    def test_targets_find_target_url_supports_modes_and_fallbacks(self):
        homework = make_notice("homework-mode", "英语作业")
        exam = make_notice("exam-mode", "英语考试", kind="exam")
        homework_url = "https://example.invalid/work/view?id=homework-mode"
        exam_url = "https://example.invalid/work/view?id=exam-mode"
        cases = [
            ("homework", homework, homework_url),
            ("homework", exam, None),
            ("exam", exam, exam_url),
            ("exam", homework, None),
            ("both", homework, homework_url),
            ("any_url", exam, exam_url),
        ]
        for mode, item, expected in cases:
            with self.subTest(mode=mode, identity=item["uuid"]):
                self.assertEqual(
                    self.monitor.find_target_url(item, {"match_mode": mode}),
                    expected,
                )

        homework_list = dict(homework)
        homework_list["attachment"] = json.loads(homework["attachment"])
        self.assertEqual(
            self.monitor.find_target_url(homework_list, {"match_mode": "homework"}),
            homework_url,
        )

        reminder = make_notice("reminder-mode", "作业提醒", reminder=True)
        self.assertIsNone(self.monitor.find_target_url(reminder, {}))
        self.assertEqual(
            self.monitor.find_target_url(reminder, {"exclude_reminders": False}),
            "https://example.invalid/work/view?id=reminder-mode",
        )

        fallback = {
            "attachment": json.dumps(
                [{"att_web": {"url": "https://example.invalid/work/view?id=fallback"}}]
            )
        }
        self.assertEqual(
            self.monitor.find_target_url(fallback, {"match_mode": "homework"}),
            "https://example.invalid/work/view?id=fallback",
        )
        self.assertIsNone(
            self.monitor.find_target_url({"attachment": "not-json"}, {})
        )

    def test_targets_collect_targets_filters_notice_types_and_returns_target(self):
        notices = [
            make_notice("homework-1", "英语作业"),
            make_notice("exam-1", "英语作业", kind="exam"),
            make_notice("reminder-1", "英语作业提醒", reminder=True),
            make_notice("keyword-1", "课程通知"),
            make_notice("read-1", "历史作业", isread="1"),
        ]
        config = {
            "match_mode": "homework",
            "exclude_reminders": True,
            "check_keyword": "作业",
            "only_unread": True,
        }

        self.assertEqual(
            self.monitor.collect_targets(notices, config),
            [
                {
                    "sid": "homework-1",
                    "title": "英语作业",
                    "url": "https://example.invalid/work/view?id=homework-1",
                    "time": 1700000000000.0,
                }
            ],
        )

    def test_keepalive_parser_extracts_form_fields_without_network(self):
        final_url = "https://example.invalid/work/dowork?workId=work-1"
        html = '''
        <form id="submitForm" action="/mooc-ans/work/addStudentWorkNewWeb?workId=work-1">
          <input id="courseId" value="course-1">
          <input id="classId" value="class-1">
          <input id="knowledgeId" value="knowledge-1">
          <input id="cpi" value="cpi-1">
          <input id="workId" value="work-1">
          <input id="answerId" value="answer-1">
          <input id="standardEnc" value="standard-1">
          <input name="answertype3" value="2">
          <textarea name="answer3">A</textarea>
          <h2 class="mark_title">示例作业</h2>
        </form>
        '''

        task, error = self.monitor._ka_parse(
            html, final_url, {"keepalive_carry_answers": True}
        )

        self.assertEqual(error, "")
        self.assertEqual(task["work_id"], "work-1")
        self.assertEqual(task["answer_id"], "answer-1")
        self.assertEqual(task["title"], "示例作业")
        self.assertEqual(task["qids"], ["3"])
        self.assertEqual(task["fields"]["answerwqbid"], "3,")
        self.assertEqual(task["fields"]["answertype3"], "2")
        self.assertEqual(task["fields"]["answer3"], "A")
        self.assertIn("saveStatus=1", task["post_url"])

    def test_keepalive_parser_rejects_non_work_page(self):
        task, error = self.monitor._ka_parse("", "https://example.invalid/home", {})
        self.assertIsNone(task)
        self.assertIn("未跳转到 doWork 页", error)


if __name__ == "__main__":
    unittest.main()
