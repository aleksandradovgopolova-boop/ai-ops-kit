import unittest

from greeting import greet


class GreetingTest(unittest.TestCase):
    def test_greets_a_person_by_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")
