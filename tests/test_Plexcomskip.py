import contextlib
import errno
import os
import shutil
import tempfile
from unittest import TestCase

from PlexComskip import sizeof_fmt
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


class TestListSegments(TestCase):

    def test_list_segments(self):
        segments = PlexComskip.list_segments('/home/abentley/PlexComskip/tests/eg.edl')
        self.assertEqual(
            [[0.0, 510.28],
             [738.74, 1348.81],
             [1569.7, 2072.24],
             [2284.25, 2644.64],
             [2876.21, 3257.89],
             [3487.92, 3992.09],
             [4220.68, 4725.95],
             [4953.15, 5260.72],
             [5508.74, 5796.59],
             [6028.66, 6374.28],
             [6809.52, 7189.32],
             [7198.22, -1]], segments)
