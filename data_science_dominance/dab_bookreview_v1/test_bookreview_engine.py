from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

import bookreview_engine as e


class ParsingTests(unittest.TestCase):
    def test_structured_metadata_and_year(self):
        details = "{'Publication date': 'March 17, 1998', 'Publisher': 'Example Press'}"
        self.assertEqual(e.extract_year(details), 1998)
        self.assertEqual(e.extract_publisher(details), 'Example Press')

    def test_categories_from_nested_strings(self):
        value = "['Books > Science > Physics', {'genre': 'Reference'}]"
        categories = e.extract_categories(value)
        keys = {e.phrase_key(item) for item in categories}
        self.assertTrue({'books', 'science', 'physics', 'reference'}.issubset(keys))

    def test_fuzzy_id_resolver(self):
        resolver = e.IdResolver([('Book-ID: ABCD-1234', 'book')])
        self.assertEqual(resolver.resolve('purchase id abcd1234'), 'book')
        self.assertEqual(resolver.resolve('ABCD123X'), 'book')


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.books = [
            e.Book('b1','1','Physics Handbook','','Alice Smith',100,{},'',30.0,'Amazon',('Science','Physics'),{'Publication date':'1998','Publisher':'A Press'},1998,'A Press'),
            e.Book('b2','2','Modern History','','Bob Jones',50,{},'',20.0,'Amazon',('History',),{'Publication date':'2005','Publisher':'B Press'},2005,'B Press'),
        ]

    def test_public_query1_plan(self):
        plan = e.plan_query('Which decade of publication (e.g., 1980s) has the highest average rating among decades with at least 10 distinct books that have been rated? Return the decade with the highest average rating.', self.books)
        self.assertEqual(plan.operation, 'argmax')
        self.assertEqual(plan.target, 'decade')
        self.assertEqual(plan.metric, 'average_rating')
        self.assertEqual(plan.min_distinct_books, 10)

    def test_category_helpful_plan(self):
        plan = e.plan_query('Which category has the highest total helpful votes among categories with at least 5 distinct books?', self.books)
        self.assertEqual(plan.target, 'category')
        self.assertEqual(plan.metric, 'helpful_votes')
        self.assertEqual(plan.min_distinct_books, 5)

    def test_verified_percentage_plan(self):
        plan = e.plan_query('What percentage of reviews are verified purchases?', self.books)
        self.assertEqual(plan.operation, 'percentage')
        self.assertTrue(plan.verified)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.b1 = e.Book('b1','1','Physics Handbook','','Alice Smith',100,{},'',30.0,'Amazon',('Science','Physics'),{},1998,'A Press')
        self.b2 = e.Book('b2','2','Quantum Guide','','Alice Smith',80,{},'',40.0,'Amazon',('Science','Physics'),{},1995,'A Press')
        self.b3 = e.Book('b3','3','Modern History','','Bob Jones',50,{},'',20.0,'Amazon',('History',),{},2005,'B Press')
        rows = [
            (self.b1, 5.0, 10, True, 2020, 'excellent physics'),
            (self.b1, 4.0, 2, True, 2021, 'useful'),
            (self.b2, 4.5, 8, False, 2020, 'quantum'),
            (self.b3, 3.0, 1, True, 2022, 'history'),
        ]
        self.joined = []
        for i, (book, rating, helpful, verified, year, text) in enumerate(rows):
            review = e.Review(f'r{i}', book.book_id, rating, '', text, date(year,1,1), helpful, verified, book.entity_id)
            self.joined.append(e.JoinedReview(review, book))
        self.books = [self.b1, self.b2, self.b3]

    def test_decade_highest_average_rating(self):
        plan = e.plan_query('Which decade of publication has the highest average rating among decades with at least 2 distinct books?', self.books)
        self.assertEqual(e.evaluate(plan, self.joined), '1990s')

    def test_category_total_helpful_votes(self):
        plan = e.plan_query('Which category has the highest total helpful votes among categories with at least 2 distinct books?', self.books)
        answer = e.evaluate(plan, self.joined)
        self.assertIn(answer, {'Science','Physics'})

    def test_count_books_with_rating_filter(self):
        plan = e.plan_query('How many books have review rating greater than 4?', self.books)
        self.assertEqual(e.evaluate(plan, self.joined), 2)

    def test_verified_percentage(self):
        plan = e.plan_query('What percentage of reviews are verified purchases?', self.books)
        self.assertEqual(e.evaluate(plan, self.joined), 75)

    def test_text_filter(self):
        plan = e.plan_query('How many reviews mention "physics"?', self.books)
        self.assertEqual(e.evaluate(plan, self.joined), 1)

    def test_no_fresh_query_leakage(self):
        source = Path(e.__file__).read_text(encoding='utf-8').lower()
        for forbidden in ('query2', 'query3', 'ground_truth', 'validate.py'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
