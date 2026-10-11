"""Regression tests for inactive attribute cleanup, without parser startup.

Load the production function from its source AST so these synthetic unit tests
do not initialize DB/Lua dependencies or alter the harness's imported modules.
World/regional fixtures and performance measurements belong to the main runner.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def _load_parse_clean():
    path = Path(__file__).resolve().parents[1] / "attributes.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "parse_clean"
    )
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["parse_clean"]


def _attribute(attribute_id, name, jobs=None, skills=None, level=1):
    return {
        "$ID": attribute_id,
        "$ID_NAME": name,
        "Link_Jobs": [] if jobs is None else list(jobs),
        "Link_Skills": [] if skills is None else list(skills),
        "LevelMax": level,
    }


def _constants(attributes):
    return SimpleNamespace(data={
        "attributes": {str(a["$ID"]): a for a in attributes},
        "attributes_by_name": {str(a["$ID_NAME"]): a for a in attributes},
        "jobs": {},
        "jobs_by_name": {},
        "skills": {},
        "skills_by_name": {},
    })


def _add_entity(constants, kind, entity_id, name, links, alias=True, named_links=None):
    primary = {"$ID": entity_id, "$ID_NAME": name, "Link_Attributes": list(links)}
    named = primary if alias else {
        "$ID": entity_id,
        "$ID_NAME": name,
        "Link_Attributes": list(links if named_links is None else named_links),
    }
    constants.data[kind][str(entity_id)] = primary
    constants.data[kind + "_by_name"][str(name)] = named
    return primary, named


class _NoEntityAccess(dict):
    def __getitem__(self, key):
        if key in ("jobs", "jobs_by_name", "skills", "skills_by_name"):
            raise AssertionError("cleanup accessed an entity index without any removals")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in ("jobs", "jobs_by_name", "skills", "skills_by_name"):
            raise AssertionError("cleanup accessed an entity index without any removals")
        return super().get(key, default)


class _CountingLinks(list):
    def __init__(self, links):
        super().__init__(links)
        self.iterations = 0
        self.visited_links = 0

    def __iter__(self):
        self.iterations += 1
        for link in super().__iter__():
            self.visited_links += 1
            yield link


class _CountingEntity(dict):
    def __init__(self, entity_id, name, links):
        super().__init__({"$ID": entity_id, "$ID_NAME": name, "Link_Attributes": links})
        self.link_reads = 0
        self.link_writes = 0

    def __getitem__(self, key):
        if key == "Link_Attributes":
            self.link_reads += 1
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key == "Link_Attributes":
            self.link_writes += 1
        return super().__setitem__(key, value)

    def get(self, key, default=None):
        if key == "Link_Attributes":
            self.link_reads += 1
        return super().get(key, default)


class _CountingIndex(dict):
    def __init__(self):
        super().__init__()
        self.values_calls = 0
        self.visited_entities = 0
        self.lookups = 0

    def __getitem__(self, key):
        self.lookups += 1
        return super().__getitem__(key)

    def values(self):
        self.values_calls += 1
        for entity in super().values():
            self.visited_entities += 1
            yield entity


class AttributeCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parse_clean = staticmethod(_load_parse_clean())

    def test_each_inactive_condition_removes_both_attribute_indexes(self):
        cases = [
            ("no_links", [], [], 1),
            ("disabled_level", ["Job"], ["Skill"], -1),
            ("all_without_jobs", [], ["All"], 1),
        ]
        for name, jobs, skills, level in cases:
            with self.subTest(condition=name):
                inactive = _attribute("removed", name, jobs, skills, level)
                active = _attribute("kept", "Kept", skills=["Skill"])
                constants = _constants([active, inactive])
                job, _ = _add_entity(constants, "jobs", 1, "Job", ["removed", "kept"])
                skill, _ = _add_entity(constants, "skills", 2, "Skill", ["kept", "removed"])

                self.parse_clean(constants)

                self.assertEqual(list(constants.data["attributes"]), ["kept"])
                self.assertEqual(list(constants.data["attributes_by_name"]), ["Kept"])
                self.assertIs(constants.data["attributes"]["kept"], active)
                self.assertIs(constants.data["attributes_by_name"]["Kept"], active)
                self.assertEqual(job["Link_Attributes"], ["kept"])
                self.assertEqual(skill["Link_Attributes"], ["kept"])

    def test_active_conditions_and_both_survivor_orders_are_preserved(self):
        active = [
            _attribute("job", "JobOnly", jobs=[1]),
            _attribute("skill", "SkillOnly", skills=["Skill"]),
            _attribute("all_job", "AllWithJob", jobs=[1], skills=["All"]),
            _attribute("mixed", "AllAndSkill", skills=["All", "Skill"]),
            _attribute("zero", "ZeroLevel", jobs=[1], level=0),
            _attribute("text", "TextLevel", skills=["Skill"], level="-1"),
        ]
        inactive = [
            _attribute("empty", "Empty"),
            _attribute("disabled", "Disabled", jobs=[1], level=-1),
            _attribute("all", "All", skills=["All"]),
        ]
        constants = _constants([inactive[0], active[0], active[1], inactive[1],
                                active[2], active[3], inactive[2], active[4], active[5]])
        # Each index keeps its own insertion order, even when those orders differ.
        constants.data["attributes_by_name"] = {
            str(a["$ID_NAME"]): a for a in reversed(list(constants.data["attributes"].values()))
        }
        id_index = constants.data["attributes"]
        name_index = constants.data["attributes_by_name"]
        original_fields = [(a, {k: list(v) if isinstance(v, list) else v
                                for k, v in a.items()}) for a in active]

        self.parse_clean(constants)

        self.assertIs(constants.data["attributes"], id_index)
        self.assertIs(constants.data["attributes_by_name"], name_index)
        self.assertEqual(list(id_index), [a["$ID"] for a in active])
        self.assertEqual(list(name_index), [a["$ID_NAME"] for a in reversed(active)])
        for attribute, original in original_fields:
            self.assertIs(id_index[attribute["$ID"]], attribute)
            self.assertIs(name_index[attribute["$ID_NAME"]], attribute)
            self.assertEqual(attribute, original)

    def test_alias_and_separate_entity_indexes_keep_order_duplicates_and_old_lists(self):
        for job_alias in (True, False):
            for skill_alias in (True, False):
                with self.subTest(job_alias=job_alias, skill_alias=skill_alias):
                    constants = _constants([
                        _attribute("gone_a", "GoneA"),
                        _attribute("stay", "Stay", skills=["Skill"]),
                        _attribute("gone_b", "GoneB", skills=["Skill"], level=-1),
                    ])
                    primary_links = ["gone_b", "stay", "unknown", "stay", "gone_a", "stay"]
                    named_links = ["stay", "gone_a", "stay", "other", "gone_b", "stay"]
                    records = []
                    for kind, alias in (("jobs", job_alias), ("skills", skill_alias)):
                        primary, named = _add_entity(
                            constants, kind, 1, kind, primary_links, alias, named_links,
                        )
                        records.append((primary, primary["Link_Attributes"], list(primary_links),
                                        ["stay", "unknown", "stay", "stay"]))
                        if not alias:
                            records.append((named, named["Link_Attributes"], list(named_links),
                                            ["stay", "stay", "other", "stay"]))

                    self.parse_clean(constants)

                    for entity, external_list, original, expected in records:
                        self.assertEqual(entity["Link_Attributes"], expected)
                        self.assertIsNot(entity["Link_Attributes"], external_list)
                        self.assertEqual(external_list, original)

    def test_original_id_types_and_stringified_index_keys(self):
        for removed_id, similar_id in ((7, "7"), ("7", 7)):
            with self.subTest(removed_id=removed_id):
                # Numeric names also exercise str($ID_NAME) for attribute/entity lookups.
                constants = _constants([
                    _attribute(removed_id, 900),
                    _attribute(8, 901, skills=["Skill"]),
                ])
                original = [similar_id, removed_id, 8, "8", similar_id, removed_id]
                records = []
                for kind in ("jobs", "skills"):
                    primary, named = _add_entity(constants, kind, 10, 100, original, alias=False)
                    records.extend([primary, named])

                self.parse_clean(constants)

                self.assertEqual(list(constants.data["attributes"]), ["8"])
                self.assertEqual(list(constants.data["attributes_by_name"]), ["901"])
                for entity in records:
                    actual = entity["Link_Attributes"]
                    self.assertEqual(actual, [similar_id, 8, "8", similar_id])
                    self.assertEqual([type(link) for link in actual],
                                     [type(similar_id), int, str, type(similar_id)])

    def test_no_removals_preserve_list_identity_and_do_not_access_entity_indexes(self):
        for empty in (False, True):
            with self.subTest(empty_attributes=empty):
                constants = _constants([] if empty else [
                    _attribute("stay", "Stay", skills=["Skill"]),
                ])
                references = []
                for kind in ("jobs", "skills"):
                    primary, named = _add_entity(
                        constants, kind, 1, kind, ["stay", "stay"],
                        alias=False, named_links=["unknown", "stay"],
                    )
                    references.extend((entity, entity["Link_Attributes"], list(entity["Link_Attributes"]))
                                      for entity in (primary, named))
                constants.data = _NoEntityAccess(constants.data)

                self.parse_clean(constants)

                for entity, external_list, original in references:
                    self.assertIs(entity["Link_Attributes"], external_list)
                    self.assertEqual(external_list, original)

    def test_no_removals_do_not_require_entity_fields_or_indexes(self):
        constants = _constants([_attribute("stay", "Stay", jobs=[1])])
        for kind in ("jobs", "skills"):
            constants.data[kind] = {"1": {}}
            constants.data[kind + "_by_name"] = {"Name": {}}
        self.parse_clean(constants)
        for key in ("jobs", "jobs_by_name", "skills", "skills_by_name"):
            del constants.data[key]
        self.parse_clean(constants)
        self.assertEqual(list(constants.data["attributes"]), ["stay"])

    def test_repeated_calls_recompute_removals_from_current_state(self):
        first = _attribute("first", "First")
        second = _attribute("second", "Second", jobs=[1])
        survivor = _attribute("stay", "Stay", skills=["Skill"])
        constants = _constants([first, second, survivor])
        records = []
        for kind in ("jobs", "skills"):
            records.extend(_add_entity(constants, kind, 1, kind,
                                       ["first", "second", "stay", "second"], alias=False))

        self.parse_clean(constants)
        after_first = [entity["Link_Attributes"] for entity in records]
        self.parse_clean(constants)
        for entity, links in zip(records, after_first):
            self.assertIs(entity["Link_Attributes"], links)
            self.assertEqual(links, ["second", "stay", "second"])

        second["LevelMax"] = -1
        restored = _attribute("first", "FirstAgain", skills=["Skill"])
        constants.data["attributes"]["first"] = restored
        constants.data["attributes_by_name"]["FirstAgain"] = restored
        for entity in records:
            entity["Link_Attributes"].extend(["first", "first"])
        before_second = [list(entity["Link_Attributes"]) for entity in records]

        self.parse_clean(constants)

        self.assertEqual(list(constants.data["attributes"]), ["stay", "first"])
        self.assertEqual(list(constants.data["attributes_by_name"]), ["Stay", "FirstAgain"])
        for entity, old_list, old_contents in zip(records, after_first, before_second):
            self.assertEqual(entity["Link_Attributes"], ["stay", "first", "first"])
            self.assertEqual(old_list, old_contents)

    def test_independent_instances_do_not_share_removed_ids(self):
        inactive_instance = _constants([_attribute("shared", "Shared")])
        active_instance = _constants([
            _attribute("shared", "Shared", skills=["Skill"]),
            _attribute("other", "Other"),
        ])
        first_records = []
        second_records = []
        for kind in ("jobs", "skills"):
            first_records.extend(_add_entity(inactive_instance, kind, 1, kind,
                                             ["shared"], alias=False))
            second_records.extend(_add_entity(active_instance, kind, 1, kind,
                                              ["shared", "other", "shared"], alias=False))
        second_lists = [entity["Link_Attributes"] for entity in second_records]

        self.parse_clean(inactive_instance)
        for entity, links in zip(second_records, second_lists):
            self.assertIs(entity["Link_Attributes"], links)
            self.assertEqual(links, ["shared", "other", "shared"])
        self.parse_clean(active_instance)

        self.assertEqual(list(active_instance.data["attributes"]), ["shared"])
        for entity in first_records:
            self.assertEqual(entity["Link_Attributes"], [])
        for entity, old_list in zip(second_records, second_lists):
            self.assertEqual(entity["Link_Attributes"], ["shared", "shared"])
            self.assertEqual(old_list, ["shared", "other", "shared"])

    def test_missing_required_attribute_fields_propagate(self):
        cases = [
            ("Link_Jobs", _attribute("gone", "Gone")),
            ("Link_Skills", _attribute("gone", "Gone")),
            ("LevelMax", _attribute("gone", "Gone", skills=["Skill"])),
            ("$ID", _attribute("gone", "Gone")),
            ("$ID_NAME", _attribute("gone", "Gone")),
        ]
        for field, attribute in cases:
            with self.subTest(field=field):
                constants = _constants([attribute])
                del attribute[field]
                with self.assertRaises(KeyError) as raised:
                    self.parse_clean(constants)
                self.assertEqual(raised.exception.args, (field,))

    def test_missing_required_index_entries_propagate(self):
        for index, key in (("attributes", "gone"), ("attributes_by_name", "Gone")):
            with self.subTest(index=index):
                constants = _constants([_attribute("gone", "Gone")])
                if index == "attributes":
                    del constants.data[index][key]
                else:
                    # Keep a discoverable entry whose name points to the missing required key.
                    constants.data[index]["wrong-key"] = constants.data[index].pop(key)
                with self.assertRaises(KeyError) as raised:
                    self.parse_clean(constants)
                self.assertEqual(raised.exception.args, (key,))

    def test_missing_required_collections_propagate_when_removing(self):
        for missing in ("attributes", "attributes_by_name", "jobs", "jobs_by_name",
                        "skills", "skills_by_name"):
            with self.subTest(collection=missing):
                constants = _constants([_attribute("gone", "Gone")])
                for kind in ("jobs", "skills"):
                    _add_entity(constants, kind, 1, "Entity", ["gone"], alias=False)
                del constants.data[missing]
                with self.assertRaises(KeyError) as raised:
                    self.parse_clean(constants)
                self.assertEqual(raised.exception.args, (missing,))

    def test_missing_required_entity_fields_and_named_entries_propagate(self):
        for kind in ("jobs", "skills"):
            for missing in ("$ID_NAME", "primary_links", "named_links", "named_entry"):
                with self.subTest(kind=kind, missing=missing):
                    constants = _constants([_attribute("gone", "Gone")])
                    primary, named = _add_entity(constants, kind, 1, "Entity", ["gone"], alias=False)
                    if missing == "$ID_NAME":
                        del primary["$ID_NAME"]
                        expected_key = "$ID_NAME"
                    elif missing == "named_entry":
                        del constants.data[kind + "_by_name"]["Entity"]
                        expected_key = "Entity"
                    else:
                        del (primary if missing == "primary_links" else named)["Link_Attributes"]
                        expected_key = "Link_Attributes"
                    with self.assertRaises(KeyError) as raised:
                        self.parse_clean(constants)
                    self.assertEqual(raised.exception.args, (expected_key,))

    def test_noniterable_required_links_propagate(self):
        for kind in ("jobs", "skills"):
            for named_only in (False, True):
                with self.subTest(kind=kind, named_only=named_only):
                    constants = _constants([_attribute("gone", "Gone")])
                    primary, named = _add_entity(constants, kind, 1, "Entity", ["gone"], alias=False)
                    (named if named_only else primary)["Link_Attributes"] = None
                    with self.assertRaises(TypeError):
                        self.parse_clean(constants)

    def test_cleanup_pass_counts_do_not_grow_with_removed_attribute_count(self):
        # Fixed entity/link counts, varying removals: assert work, not elapsed time.
        # Entity reads/writes also catch rescans after the counting list is replaced.
        for job_alias in (True, False):
            for skill_alias in (True, False):
                observations = []
                for removal_count in (1, 64):
                    with self.subTest(job_alias=job_alias, skill_alias=skill_alias,
                                      removals=removal_count):
                        removed = ["gone_{}".format(i) for i in range(removal_count)]
                        constants = _constants([
                            _attribute(attribute_id, "Name_" + attribute_id)
                            for attribute_id in removed
                        ] + [_attribute("stay", "Stay", skills=["Skill"])])
                        records = []
                        indexes = []
                        for kind, alias in (("jobs", job_alias), ("skills", skill_alias)):
                            primary_index = _CountingIndex()
                            named_index = _CountingIndex()
                            constants.data[kind] = primary_index
                            constants.data[kind + "_by_name"] = named_index
                            indexes.append((primary_index, named_index))
                            for entity_id in range(6):
                                name = kind + str(entity_id)
                                links = _CountingLinks([removed[0], "stay", "stay", removed[-1]])
                                primary = _CountingEntity(entity_id, name, links)
                                # Filtering the same alias twice is permitted, but must
                                # remain constant regardless of the removal count.
                                records.append((primary, links, 2 if alias else 1))
                                named = primary
                                if not alias:
                                    named_links = _CountingLinks(["stay", removed[-1], "stay", removed[0]])
                                    named = _CountingEntity(entity_id, name, named_links)
                                    records.append((named, named_links, 1))
                                primary_index[str(entity_id)] = primary
                                named_index[name] = named

                        self.parse_clean(constants)

                        self.assertEqual(list(constants.data["attributes"]), ["stay"])
                        self.assertEqual(list(constants.data["attributes_by_name"]), ["Stay"])
                        counts = []
                        for primary_index, named_index in indexes:
                            self.assertEqual(primary_index.values_calls, 1)
                            self.assertEqual(primary_index.visited_entities, 6)
                            self.assertLessEqual(named_index.values_calls, 1)
                            self.assertLessEqual(named_index.visited_entities, 6)
                            self.assertLessEqual(named_index.lookups, 6)
                            counts.append((primary_index.values_calls, primary_index.visited_entities,
                                           named_index.values_calls, named_index.visited_entities,
                                           named_index.lookups))
                        for entity, original_links, maximum_passes in records:
                            self.assertGreaterEqual(entity.link_reads, 1)
                            self.assertLessEqual(entity.link_reads, maximum_passes)
                            self.assertGreaterEqual(entity.link_writes, 1)
                            self.assertLessEqual(entity.link_writes, maximum_passes)
                            self.assertEqual(original_links.iterations, 1)
                            self.assertEqual(original_links.visited_links, 4)
                            counts.append((entity.link_reads, entity.link_writes,
                                           original_links.iterations, original_links.visited_links))
                            self.assertEqual(dict.__getitem__(entity, "Link_Attributes"), ["stay", "stay"])
                        observations.append(counts)
                self.assertEqual(observations[0], observations[1])


if __name__ == "__main__":
    unittest.main()
