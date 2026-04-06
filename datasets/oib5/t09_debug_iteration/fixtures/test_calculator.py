"""测试计算器"""
import unittest
import sys
from calculator import Calculator


class TestCalculator(unittest.TestCase):
    def setUp(self):
        self.calc = Calculator()

    # --- 基础运算 ---
    def test_add(self):
        self.assertEqual(self.calc.add(2, 3), 5)

    def test_subtract(self):
        self.assertEqual(self.calc.subtract(10, 3), 7)

    def test_subtract_negative_result(self):
        self.assertEqual(self.calc.subtract(3, 10), -7)

    def test_multiply(self):
        self.assertEqual(self.calc.multiply(4, 5), 20)

    def test_divide(self):
        self.assertAlmostEqual(self.calc.divide(10, 3), 3.3333333, places=5)

    def test_divide_exact_returns_float(self):
        result = self.calc.divide(4, 2)
        self.assertEqual(result, 2.0)
        self.assertIsInstance(result, float)

    def test_divide_negative(self):
        self.assertAlmostEqual(self.calc.divide(-9, 2), -4.5, places=5)

    def test_divide_by_zero(self):
        with self.assertRaises(ValueError):
            self.calc.divide(10, 0)

    def test_divide_by_zero_does_not_pollute_history(self):
        self.calc.add(1, 2)
        with self.assertRaises(ValueError):
            self.calc.divide(10, 0)
        self.assertEqual(len(self.calc.get_history()), 1)

    def test_power(self):
        self.assertEqual(self.calc.power(2, 10), 1024)

    # --- average ---
    def test_average(self):
        self.assertAlmostEqual(self.calc.average([1, 2, 3, 4, 5]), 3.0)

    def test_average_single(self):
        self.assertEqual(self.calc.average([42]), 42.0)

    def test_average_floats(self):
        self.assertAlmostEqual(self.calc.average([1.5, 2.5, 3.0]), 7.0 / 3.0)

    def test_average_empty(self):
        with self.assertRaises(ValueError):
            self.calc.average([])

    # --- factorial ---
    def test_factorial(self):
        self.assertEqual(self.calc.factorial(5), 120)

    def test_factorial_zero(self):
        self.assertEqual(self.calc.factorial(0), 1)

    def test_factorial_negative(self):
        with self.assertRaises(ValueError):
            self.calc.factorial(-1)

    # --- history ---
    def test_history(self):
        self.calc.add(1, 2)
        self.calc.multiply(3, 4)
        history = self.calc.get_history()
        self.assertEqual(len(history), 2)

    def test_history_records_operation_detail(self):
        result = self.calc.subtract(10, 3)
        self.assertEqual(self.calc.get_history()[-1], ("subtract", 10, 3, result))

    def test_get_history_returns_copy(self):
        self.calc.add(1, 2)
        history = self.calc.get_history()
        history.append(("tamper", 0, 0, 0))
        self.assertEqual(self.calc.get_history(), [("add", 1, 2, 3)])

    def test_get_history_returns_fresh_snapshot(self):
        self.calc.add(2, 3)
        first = self.calc.get_history()
        second = self.calc.get_history()
        self.assertIsNot(first, second)
        first.clear()
        self.assertEqual(self.calc.get_history(), [("add", 2, 3, 5)])

    def test_clear_history(self):
        self.calc.add(1, 2)
        self.calc.clear_history()
        self.assertEqual(len(self.calc.get_history()), 0)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestCalculator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
