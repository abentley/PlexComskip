import contextlib
from io import BytesIO
import errno
import os
import shutil
import tempfile
from unittest import TestCase
from unittest.mock import Mock

from PlexComskip import (
    Action,
    extend_end,
    Segment,
    sizeof_fmt,
)
import PlexComskip


class TestSizeofFMT(TestCase):

    def test_sizeof_fmt(self):
        self.assertEqual(sizeof_fmt(0), '0.0B')
        self.assertEqual(sizeof_fmt(1024), '1.0KB')
        self.assertEqual(sizeof_fmt(1024 * 1.5), '1.5KB')
        self.assertEqual(sizeof_fmt(1024 ** 2 * 1.5), '1.5MB')
        self.assertEqual(sizeof_fmt(1024 ** 3 * 1.5), '1.5GB')
        self.assertEqual(sizeof_fmt(1024 ** 4 * 1.5), '1.5TB')
        self.assertEqual(sizeof_fmt(1024 ** 5 * 1.5), '1.5PB')
        self.assertEqual(sizeof_fmt(1024 ** 6 * 1.5), '1.5EB')
        self.assertEqual(sizeof_fmt(1024 ** 7 * 1.5), '1.5ZB')
        self.assertEqual(sizeof_fmt(1024 ** 8 * 1.5), '1.5YB')
        self.assertEqual(sizeof_fmt(1024 ** 9 * 1.5), '1536.0YB')


@contextlib.contextmanager
def temp_dir():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise


@contextlib.contextmanager
def check_config_post(test_case, keep):
    work_dirs = []
    with test_case.assertRaises(SystemExit):
        yield work_dirs
    work_dir, = work_dirs
    if keep:
        test_case.assertEqual(os.getcwd(), work_dir)
        test_case.assertIs(os.path.isdir(work_dir), True)
    else:
        test_case.assertNotEqual(os.getcwd(), work_dir)
        test_case.assertIs(os.path.exists(work_dir), False)


@contextlib.contextmanager
def check_cleanup(test_case, work_dir, keep):
    test_case.assertIs(os.path.isdir(work_dir), True)
    os.chdir(work_dir)
    with check_config_post(test_case, keep) as work_dirs:
        work_dirs.append(work_dir)
        yield


class TestCleanupAndExit(TestCase):

    def test_no_keep(self):
        with temp_dir() as work_dir:
            with check_cleanup(self, work_dir, keep=False):
                PlexComskip.cleanup_and_exit(work_dir, keep_temp=False)

    def test_keep(self):
        with temp_dir() as work_dir:
            with check_cleanup(self, work_dir, keep=True):
                PlexComskip.cleanup_and_exit(work_dir, keep_temp=True)


class TestWorkDir(TestCase):

    @contextlib.contextmanager
    def wd_cxt(self, keep, save_always, save_forensics):
        with temp_dir() as temp_root:
            with check_config_post(self, keep) as work_dirs:
                with PlexComskip.work_dir(temp_root, 'session', save_always,
                                          save_forensics) as work_dir:
                    work_dirs.append(work_dir)
                    os.chdir(work_dir)
                    yield

    def test_clean_no_keep(self):
        with self.wd_cxt(keep=False, save_always=False, save_forensics=False):
            pass

    def test_clean_no_keep_forensics(self):
        with self.wd_cxt(keep=False, save_always=False, save_forensics=True):
            pass

    def test_clean_keep_always(self):
        with self.wd_cxt(keep=True, save_always=True, save_forensics=False):
            pass

    def test_clean_keep_always_forensics(self):
        with self.wd_cxt(keep=True, save_always=True, save_forensics=True):
            pass

    def test_error_no_keep(self):
        with self.wd_cxt(keep=False, save_always=False, save_forensics=False):
            raise ValueError('foo')

    def test_error_keep_forensics(self):
        with self.wd_cxt(keep=True, save_always=False, save_forensics=True):
            raise ValueError('foo')

    def test_error_keep_always(self):
        with self.wd_cxt(keep=True, save_always=True, save_forensics=False):
            raise ValueError('foo')

    def test_error_keep_always_forensics(self):
        with self.wd_cxt(keep=True, save_always=True, save_forensics=True):
            raise ValueError('foo')


EG_EDL = b"""\
510.28	738.74	0
1348.81	1569.70	0
2072.24	2284.25	0
2644.64	2876.21	0
3257.89	3487.92	0
3992.09	4220.68	0
4725.95	4953.15	0
5260.72	5508.74	0
5796.59	6028.66	0
6374.28	6809.52	0
7189.32	7198.22	0
"""

EG_PARSED_EDL = [
    (510.28, 738.74, Action.SKIP),
    (1348.81, 1569.70, Action.SKIP),
    (2072.24, 2284.25, Action.SKIP),
    (2644.64, 2876.21, Action.SKIP),
    (3257.89, 3487.92, Action.SKIP),
    (3992.09, 4220.68, Action.SKIP),
    (4725.95, 4953.15, Action.SKIP),
    (5260.72, 5508.74, Action.SKIP),
    (5796.59, 6028.66, Action.SKIP),
    (6374.28, 6809.52, Action.SKIP),
    (7189.32, 7198.22, Action.SKIP),
]


class TestParseEDL(TestCase):

    def test_parse_edl(self):
        edl = list(PlexComskip.parse_edl(EG_EDL.splitlines()))
        self.assertEqual(EG_PARSED_EDL, edl)


EG_SEGMENTS = [
    (0.0, 510.28),
    (738.74, 1348.81),
    (1569.7, 2072.24),
    (2284.25, 2644.64),
    (2876.21, 3257.89),
    (3487.92, 3992.09),
    (4220.68, 4725.95),
    (4953.15, 5260.72),
    (5508.74, 5796.59),
    (6028.66, 6374.28),
    (6809.52, 7189.32),
    (7198.22, -1),
]


class TestListSegments(TestCase):

    def test_list_segments(self):
        mock_path = Mock()
        mock_path.open.return_value = BytesIO(EG_EDL)
        segments = PlexComskip.list_segments(mock_path)
        self.assertEqual(EG_SEGMENTS, segments)


class TestEDLToSegments(TestCase):

    def test_edl_to_segments(self):
        self.assertEqual(list(PlexComskip.edl_to_segments(EG_PARSED_EDL)),
                         EG_SEGMENTS)

    def test_zero_start(self):
        self.assertEqual(list(PlexComskip.edl_to_segments(
            [[0.0, 5.0, Action.SKIP]] + EG_PARSED_EDL)),
            [(5.0, 510.28)] + EG_SEGMENTS[1:])

    def test_empty(self):
        self.assertEqual(list(PlexComskip.edl_to_segments([])), [(0.0, -1)])


class TestExtendEnd(TestCase):

    def test_extend_end(self):
        self.assertEqual(extend_end([
            Segment(5.0, 6.0), Segment(100.0, 120.0), Segment(130.0, -1)

        ]), [
            Segment(5.0, 11.0), Segment(100, 125.0), Segment(130.0, -1)
        ])

    def test_overlap(self):
        self.assertEqual(extend_end([
            Segment(5.0, 96.0), Segment(100.0, 120.0), Segment(130.0, -1),
        ]), [
            Segment(5.0, 125.0), Segment(130.0, -1),
        ])
