from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from Items.models import Items
from Items import views


class SearchQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Items.objects.bulk_create([
            Items(ids=str(i).zfill(3), id_name='item_%s' % i,
                  name='Matching item', type='Material')
            for i in range(25)
        ])

    def search(self, **params):
        request = RequestFactory().get('/items/', params)
        with patch.object(views, 'render', side_effect=lambda request, template, data: data):
            return views.index(request)

    def test_page_is_limited_and_equipment_lookup_is_batched(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.search(q='Matching', page=2, order='ids-asc')
            rows = list(data['item'])
            equipment = [getattr(item, 'equipments', None) for item in rows]
        self.assertEqual(data['item_len'], 25)
        self.assertEqual([item.ids for item in rows], ['%03d' % i for i in range(10, 20)])
        self.assertEqual(equipment, [None] * 10)
        self.assertEqual(len(queries), 3)
        self.assertIn('LIMIT 10 OFFSET 10', queries[-1]['sql'])

    def test_empty_results_keep_count_and_page_empty(self):
        data = self.search(q='no such item', order='ids-asc')
        self.assertEqual(data['item_len'], 0)
        self.assertEqual(list(data['item']), [])
