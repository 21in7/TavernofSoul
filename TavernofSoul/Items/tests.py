from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.http import HttpResponse
from django.template.loader import render_to_string

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from Items.models import Items, Item_Type, Equipments
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
        captured = {}

        def capture(request, template, data):
            captured.update(data)
            return HttpResponse('')

        with patch.object(views, 'render', side_effect=capture):
            views.index(request)
        return captured

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

    def test_document_and_fragment_share_results_and_cache_boundary(self):
        params = {'q': 'Matching', 'page': '2', 'order': 'ids-asc'}
        document = self.client.get('/items/', params)
        fragment = self.client.get('/items/', params, HTTP_X_ITEM_SEARCH='results-v1')
        self.assertEqual(document.status_code, 200)
        self.assertEqual(fragment.status_code, 200)
        self.assertEqual(document['X-Item-Search'], 'document')
        self.assertEqual(fragment['X-Item-Search'], 'results-v1')
        for response in (document, fragment):
            self.assertIn('x-item-search', response['Vary'].lower())
            self.assertEqual(response.context['curpage'], 2)
            self.assertEqual(response.context['item_len'], 25)
            self.assertEqual([row.ids for row in response.context['item']],
                             ['%03d' % i for i in range(10, 20)])
        result_keys = ('searched', 'item_len', 'curpage', 'pageLen', 'item', 'search_url',
                       'pages', 'previous', 'next', 'pageStart', 'pageEnd')
        shared = render_to_string('Items/search_results.html',
                                  {key: document.context[key] for key in result_keys})
        self.assertEqual(fragment.content.decode(), shared)
        self.assertIn(shared, document.content.decode())
        self.assertContains(document, 'item-search-form')
        self.assertNotContains(fragment, '<html')
        self.assertNotContains(fragment, '<script')
        self.assertContains(fragment, 'aria-current="page">2')
        # An unsupported contract version must receive a full document.
        unknown = self.client.get('/items/', params, HTTP_X_ITEM_SEARCH='results-v2')
        self.assertEqual(unknown['X-Item-Search'], 'document')
        self.assertContains(unknown, 'item-search-form')

    def test_initial_and_empty_search_have_distinct_guidance_and_get_reset(self):
        initial = self.client.get('/items/')
        empty = self.client.get('/items/', {'q': '<no & such "item">', 'grade': '6'})
        self.assertFalse(initial.context['searched'])
        self.assertNotContains(initial, 'No items found')
        self.assertContains(initial, 'Enter a keyword')
        self.assertTrue(empty.context['searched'])
        self.assertEqual(empty.context['query'], '<no & such "item">')
        self.assertEqual(empty.context['grade'], '6')
        self.assertEqual(empty.context['pages'], [])
        self.assertContains(empty, 'No items found')
        self.assertContains(empty, '0 Results')
        self.assertContains(empty, 'href="/items/" data-search-reset')
        self.assertContains(empty, '&lt;no &amp; such &quot;item&quot;&gt;')
        self.assertNotContains(empty, '<no & such')

    def test_pagination_encodes_special_keyword_and_all_conditions(self):
        keyword = 'Sword & shield + #? / "한글"'
        Items.objects.all().update(name=keyword, grade=4)
        material = Item_Type.objects.create(name='Material', is_equipment=False)
        params = {'q': keyword, 'grade': '4', 'class': '', 'type': str(material.pk),
                  'lvmin': '', 'lvmax': '', 'order': 'ids-asc', 'page': '2'}
        data = self.search(**params)
        for page in data['pages']:
            parsed = urlsplit(page['link'])
            self.assertEqual(parsed.path, '/items/')
            values = parse_qs(parsed.query, keep_blank_values=True)
            for key, value in params.items():
                self.assertEqual(values[key], [str(page['page']) if key == 'page' else value])
            self.assertNotIn('fragment', values)
        self.assertEqual(data['item_len'], 25)
        self.assertEqual(data['previous'], data['pageStart'])
        self.assertEqual(data['next'], data['pageEnd'])

    def test_equipment_filters_and_name_link_keep_grade_text(self):
        equipment_type = Item_Type.objects.create(name='Sword', is_equipment=True)
        item = Items.objects.create(ids='sword', id_name='special_sword',
                                    name='Filtered sword', type='Weapon', grade=6)
        Equipments.objects.create(item=item, level=560, type_equipment='Sword',
                                  requiredClass='...T.', unidentified=False,
                                  unidentifiedRandom=False, transcend_price=[])
        params = {'q': 'Filtered', 'grade': '6', 'class': '3',
                  'type': str(equipment_type.pk) + '_eq',
                  'lvmin': '550', 'lvmax': '560', 'order': 'eq-level-dsc'}
        for headers in ({}, {'HTTP_X_ITEM_SEARCH': 'results-v1'}):
            response = self.client.get('/items/', params, **headers)
            self.assertEqual(response.context['item_len'], 1)
            self.assertEqual([row.ids for row in response.context['item']], ['sword'])
            self.assertContains(response, 'href="/items/sword">Filtered sword</a>')
            self.assertContains(response, 'Goddess')
            self.assertContains(response, '560')
        for key, value in (('lvmin', '561'), ('lvmax', '559'), ('class', '0'), ('grade', '1')):
            excluded = dict(params, **{key: value})
            self.assertEqual(self.search(**excluded)['item_len'], 0)

    def test_invalid_inputs_normalize_locally_without_unhandled_errors(self):
        for page, expected in (('bad', 1), ('0', 1), ('-3', 1), ('2.5', 1),
                               ('9999999999999999999999999999999999', 3)):
            with self.subTest(page=page):
                data = self.search(q='Matching', page=page, order='ids-asc')
                self.assertEqual(data['curpage'], expected)
        for headers in ({}, {'HTTP_X_ITEM_SEARCH': 'results-v1'}):
            response = self.client.get('/items/', {
                'q': 'Matching', 'page': 'oops', 'order': 'eq-unknown-asc',
                'grade': 'NaN', 'class': '999', 'type': '999999999999999999_eq',
                'lvmin': 'not a number', 'lvmax': '999999999999999999999999999999'
            }, **headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['curpage'], 1)
            self.assertEqual(response.context['order'], 'updated-dsc')
            self.assertEqual(response.context['item_len'], 25)
            for key in ('grade', 'class', 'type', 'minLV', 'maxLV'):
                self.assertEqual(response.context[key], '')

    def test_fragment_render_keeps_three_batched_database_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/items/', {'q': 'Matching', 'page': '2',
                                                  'order': 'ids-asc'},
                                       HTTP_X_ITEM_SEARCH='results-v1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), 3)
        self.assertIn('LIMIT 10 OFFSET 10', queries[-1]['sql'])
        self.assertContains(response, 'Page 2 / 3')

    def test_blank_keyword_searches_all_and_keeps_native_get_controls(self):
        response = self.client.get('/items/', {'q': '', 'order': 'ids-asc'})
        self.assertEqual(response.context['item_len'], 25)
        self.assertTrue(response.context['searched'])
        self.assertContains(response, 'action="/items/" method="get"')
        self.assertNotContains(response, 'name="page"')
        self.assertContains(response, 'href="/items/000">000</a>')
        self.assertContains(response, 'href="/items/000">Matching item</a>')
        self.assertContains(response, 'for="item-query"')
        self.assertContains(response, '<legend>Search filters</legend>')
