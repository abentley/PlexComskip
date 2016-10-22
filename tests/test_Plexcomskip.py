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
def check_cleanup(test_case, work_dir, keep):
    test_case.assertIs(os.path.isdir(work_dir), True)
    os.chdir(work_dir)
    with test_case.assertRaises(SystemExit):
        yield
    if keep:
        test_case.assertEqual(os.getcwd(), work_dir)
        test_case.assertIs(os.path.isdir(work_dir), True)
    else:
        test_case.assertNotEqual(os.getcwd(), work_dir)
        test_case.assertIs(os.path.exists(work_dir), False)


class TestCleanupAndExit(TestCase):

    def test_no_keep(self):
        with temp_dir() as work_dir:
            with check_cleanup(self, work_dir, keep=False):
                PlexComskip.cleanup_and_exit(work_dir, keep_temp=False)

    def test_keep(self):
        with temp_dir() as work_dir:
            with check_cleanup(self, work_dir, keep=True):
                PlexComskip.cleanup_and_exit(work_dir, keep_temp=True)
