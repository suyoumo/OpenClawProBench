"""测试 merge_intervals 函数"""
import unittest
import sys


class TestMergeIntervals(unittest.TestCase):
    def setUp(self):
        from solution import merge_intervals
        self.merge = merge_intervals

    def test_basic(self):
        self.assertEqual(self.merge([[1, 3], [2, 6], [8, 10], [15, 18]]), [[1, 6], [8, 10], [15, 18]])

    def test_overlap_all(self):
        self.assertEqual(self.merge([[1, 4], [2, 5], [3, 6]]), [[1, 6]])

    def test_no_overlap(self):
        self.assertEqual(self.merge([[1, 2], [4, 5], [7, 8]]), [[1, 2], [4, 5], [7, 8]])

    def test_single(self):
        self.assertEqual(self.merge([[1, 5]]), [[1, 5]])

    def test_empty(self):
        self.assertEqual(self.merge([]), [])

    def test_touching(self):
        """相邻区间 [1,2] [2,3] 应合并"""
        self.assertEqual(self.merge([[1, 2], [2, 3]]), [[1, 3]])

    def test_unsorted(self):
        """输入未排序"""
        self.assertEqual(self.merge([[3, 5], [1, 4]]), [[1, 5]])

    def test_contained(self):
        """一个区间完全包含另一个"""
        self.assertEqual(self.merge([[1, 10], [3, 5]]), [[1, 10]])

    def test_negative(self):
        """负数区间"""
        self.assertEqual(self.merge([[-3, -1], [-2, 2], [4, 6]]), [[-3, 2], [4, 6]])

    def test_large(self):
        """较多区间"""
        intervals = [[i, i + 2] for i in range(0, 20, 3)]  # [0,2],[3,5],[6,8],...
        result = self.merge(intervals)
        # 这些区间不重叠（间隔1），所以结果应该和输入一样
        self.assertEqual(len(result), len(intervals))


if __name__ == "__main__":
    # 运行测试并输出结果
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestMergeIntervals)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
