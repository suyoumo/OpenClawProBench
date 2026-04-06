import unittest
from models import User, Product
from validators import validate_email, validate_age

class TestUser(unittest.TestCase):
    def test_greet(self):
        u = User('Alice', 30)
        self.assertEqual(u.greet(), 'Hi, Alice')

class TestValidators(unittest.TestCase):
    def test_email(self):
        self.assertTrue(validate_email('a@b.com'))
        self.assertFalse(validate_email('invalid'))

    def test_age(self):
        self.assertTrue(validate_age(25))
        self.assertFalse(validate_age(-1))

if __name__ == '__main__':
    unittest.main()
