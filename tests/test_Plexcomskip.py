from unittest import TestCase

from PlexComskip import sizeof_fmt


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

