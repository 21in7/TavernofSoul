from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from html.parser import HTMLParser

from django.http import HttpResponse
from django.template.loader import render_to_string

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from Items.models import Items, Item_Type, Equipments
from Items import views


class DetailDocument(HTMLParser):
    """Inspect the server document without executing calculator JavaScript."""
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))

    def handle_data(self, text):
        self.text.append(text)


class ItemDetailDocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from Items.models import Recipes, Item_Recipe_Material, Item_Recipe_Target

        cls.long_name = '긴이름日本語LongUnbrokenEquipmentName' * 5
        cls.description = '설명 日本語 <details> & material information'
        cls.equipment = Items.objects.create(
            ids='mobile-equipment', id_name='LongClassName' * 7,
            name=cls.long_name, descriptions=cls.description, icon='fixture',
            tradability='TTTTT', grade=4, type='Weapon')
        Equipments.objects.create(
            item=cls.equipment, level=400, type_equipment='Staff',
            requiredClass='TTTTT', unidentified=False, unidentifiedRandom=False,
            durability=40, potential=8, sockets_limit=3, matk=350,
            anvil_atk=[7 * n for n in range(1, 41)],
            anvil_def=[], anvil_price=[100 * n for n in range(1, 41)],
            transcend_price=list(range(1, 11)))
        cls.recipe_item = Items.objects.create(
            ids='mobile-recipe', id_name='Recipe_Mobile', name='Recipe ' + cls.long_name,
            tradability='TTTTT', type='Recipe', icon='fixture')
        cls.material = Items.objects.create(
            ids='mobile-material', id_name='Material_Mobile', name='材料 & <ore> ' + cls.long_name,
            tradability='TTTTT', type='Material', icon='fixture')
        recipe = Recipes.objects.create(item=cls.recipe_item)
        Item_Recipe_Target.objects.create(recipe=recipe, target=cls.equipment)
        Item_Recipe_Material.objects.create(recipe=recipe, material=cls.material, qty=123456)

    def document(self, item):
        response = self.client.get(item.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        return response, DetailDocument(response.content.decode())

    def test_server_document_keeps_stats_and_labelled_calculator_controls(self):
        response, document = self.document(self.equipment)
        self.assertIn(self.long_name, ''.join(document.text))
        self.assertIn(self.description, ''.join(document.text))
        ids = [attrs['id'] for _, attrs in document.elements if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        controls = {attrs['id']: attrs for tag, attrs in document.elements
                    if tag == 'input' and attrs.get('id') in ('anvil', 'tc')}
        labels = {attrs.get('for') for tag, attrs in document.elements if tag == 'label'}
        self.assertEqual(set(controls), {'anvil', 'tc'})
        for ident, attrs in controls.items():
            self.assertIn(ident, labels)
            self.assertEqual((attrs['type'], attrs['inputmode'], attrs['min'],
                              attrs['step'], attrs['value']),
                             ('number', 'numeric', '0', '1', '0'))
        self.assertEqual(controls['tc']['max'], '10')
        self.assertEqual(response.context['enhancement']['base']['matk'], 350)
        self.assertEqual(response.context['enhancement']['attack'][5], 42)
        self.assertEqual(response.context['enhancement']['prices'][5], 600)
        self.assertContains(response, 'id = "matk" >350</td>')
        regions = [attrs for _, attrs in document.elements if attrs.get('role') == 'region']
        self.assertTrue(regions)
        for attrs in regions:
            self.assertTrue(attrs.get('aria-label'))
            self.assertEqual(attrs['tabindex'], '0')
            self.assertIn(attrs['aria-describedby'], ids)
        headers = [attrs for tag, attrs in document.elements if tag == 'th']
        self.assertTrue(headers)
        self.assertTrue(all(attrs.get('scope') in ('row', 'col') for attrs in headers))

    def test_recipe_and_reference_links_are_present_in_basic_html(self):
        _, recipe = self.document(self.recipe_item)
        links = [attrs.get('href') for tag, attrs in recipe.elements if tag == 'a']
        self.assertIn(self.material.get_absolute_url(), links)
        self.assertIn(self.equipment.get_absolute_url(), links)
        self.assertIn(self.material.name, ''.join(recipe.text))
        self.assertIn('x123456', ''.join(recipe.text))
        _, equipment = self.document(self.equipment)
        self.assertIn(self.recipe_item.get_absolute_url(),
                      [attrs.get('href') for tag, attrs in equipment.elements if tag == 'a'])


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
        Items.objects.all().update(grade=4)
        material = Item_Type.objects.create(name='Material', is_equipment=False)
        params = {'q': 'Matching', 'page': '2', 'order': 'ids-asc',
                  'grade': '4', 'type': str(material.pk)}
        document = self.client.get('/items/', params)
        fragment = self.client.get('/items/', params, HTTP_X_ITEM_SEARCH='results-v1')
        self.assertEqual(document.status_code, 200)
        self.assertEqual(fragment.status_code, 200)
        self.assertEqual(document['X-Item-Search'], 'document')
        self.assertEqual(fragment['X-Item-Search'], 'results-v1')
        for response in (document, fragment):
            self.assertEqual(response['Content-Type'].split(';')[0].strip(), 'text/html')
            self.assertIn('x-item-search',
                          [token.strip().lower() for token in response['Vary'].split(',')])
            for key, value in (('query', 'Matching'), ('order', 'ids-asc'),
                               ('grade', '4'), ('type', str(material.pk))):
                self.assertEqual(response.context[key], value)
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
        self.assertContains(document, '<!doctype html>')
        self.assertContains(document, '<html lang="en">')
        self.assertContains(document, '</html>')
        self.assertContains(document, '<form id="item-search-form" action="/items/" method="get">')
        self.assertContains(document, 'css/item-search.css')
        self.assertContains(document, 'js/item-search.js')
        for response in (document, fragment):
            self.assertContains(response, 'id="item-search-results"', count=1)
            self.assertContains(response, 'data-item-search-fragment="results-v1"', count=1)
            self.assertContains(response, '25 Results')
            self.assertContains(response, 'Page 2 / 3')
            self.assertContains(response, '>Matching item</a>', count=10)
        self.assertNotContains(fragment, '<!doctype')
        self.assertNotContains(fragment, '<html')
        self.assertNotContains(fragment, '<form')
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
