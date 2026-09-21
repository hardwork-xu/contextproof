"""Behavioral probes adapted from independently authored upstream regression tests.

No task selection depends on ContextProof outcomes or generated model answers.
The output of each trusted snippet is its RESULT, normalized by oracle_worker.py.
Related probes share a family; families never cross development/holdout splits.
"""

from __future__ import annotations

from textwrap import dedent


def task(identifier, repository, family, split, code, anchors, test_path, test_name,
         issue=None, category="change"):
    return {
        "id": identifier, "repository": repository, "family": family, "split": split,
        "code": dedent(code).strip() + "\n",
        "anchors": [{"path": path, "symbol": symbol} for path, symbol in anchors],
        "upstream_test": {"path": test_path, "symbol": test_name},
        "upstream_issue": issue, "selection_category": category,
    }


TASKS = [
    task("dev-packaging-prerelease", "packaging", "packaging-794", "development", '''
        from packaging.specifiers import Specifier
        RESULT = Specifier(">1.0.dev1").prereleases
    ''', [("src/packaging/specifiers.py", "Specifier.prereleases")],
         "tests/test_specifiers.py", "TestSpecifier.test_specifier_prereleases_detection", 794),
    task("dev-httpx-json", "httpx", "httpx-3363", "development", '''
        import httpx
        request = httpx.Request("POST", "http://example.org", json={"test": 123})
        RESULT = [request.content.decode("utf-8"), request.headers["Content-Length"]]
    ''', [("httpx/_content.py", "encode_json"), ("httpx/_models.py", "Request.__init__")],
         "tests/models/test_requests.py", "test_json_encoded_data", 3363),
    task("dev-pluggy-blocked", "pluggy", "pluggy-481", "development", '''
        import pluggy
        manager = pluggy.PluginManager("example")
        manager.set_blocked("blocked")
        RESULT = [len(manager.get_plugins()), None in manager.get_plugins()]
    ''', [("src/pluggy/_manager.py", "PluginManager.get_plugins"),
          ("src/pluggy/_manager.py", "PluginManager.set_blocked")],
         "testing/test_pluginmanager.py", "test_set_blocked", 481),
    task("dev-attrs-evolve", "attrs", "attrs-1264", "development", '''
        import attrs
        @attrs.define
        class Record:
            value: int
        RESULT = attrs.evolve(inst=Record(1), value=2).value
    ''', [("src/attr/_make.py", "evolve")],
         "tests/test_funcs.py", "TestEvolve", 1264),
    task("dev-packaging-normalize-control", "packaging", "control-canonicalize", "development", '''
        from packaging.utils import canonicalize_name, canonicalize_version
        RESULT = [canonicalize_name("My_Package.Name"), canonicalize_version("1.0.0")]
    ''', [("src/packaging/utils.py", "canonicalize_name"),
          ("src/packaging/utils.py", "canonicalize_version")],
         "tests/test_utils.py", "test_canonicalize_version", category="control"),

    task("packaging-epoch", "packaging", "packaging-683", "holdout", '''
        from packaging.specifiers import Specifier
        RESULT = Specifier("==2!1.0.0.0.*").contains("2!1.0.0")
    ''', [("src/packaging/specifiers.py", "Specifier._compare_equal"),
          ("src/packaging/specifiers.py", "_version_split"),
          ("src/packaging/specifiers.py", "_pad_version")],
         "tests/test_specifiers.py", "TestSpecifier.test_specifiers", 683),
    task("packaging-iterable-specifiers", "packaging", "packaging-775", "holdout", '''
        from packaging.specifiers import Specifier, SpecifierSet
        spec = SpecifierSet(iter([Specifier(">=1.0"), Specifier("<2.0")]))
        RESULT = sorted(map(str, spec))
    ''', [("src/packaging/specifiers.py", "SpecifierSet.__init__")],
         "tests/test_specifiers.py", "TestSpecifierSet.test_create_from_specifiers", 775),
    task("packaging-missing-metadata", "packaging", "packaging-733", "holdout", '''
        from packaging.metadata import Metadata
        meta = Metadata.from_raw({}, validate=False)
        RESULT = meta.keywords
    ''', [("src/packaging/metadata.py", "_Validator.__get__"),
          ("src/packaging/metadata.py", "_Validator._process_keywords"),
          ("src/packaging/metadata.py", "Metadata.from_raw")],
         "tests/test_metadata.py", "TestMetadata.test_optional_defaults_to_none", 733),
    task("packaging-marker-untagged", "packaging", "packaging-825", "holdout", '''
        from packaging.markers import Marker
        RESULT = Marker("python_full_version < '3.12'").evaluate(
            {"python_full_version": "3.11.1+"})
    ''', [("src/packaging/markers.py", "Marker.evaluate"),
          ("src/packaging/markers.py", "_repair_python_full_version"),
          ("src/packaging/markers.py", "_eval_op")],
         "tests/test_markers.py", "TestEvaluation.test_python_full_version_untagged_user_provided", 825),
    task("packaging-license-expression", "packaging", "packaging-828", "holdout", '''
        from packaging.metadata import Metadata
        meta = Metadata.from_raw({"license_expression": "mit"}, validate=False)
        RESULT = meta.license_expression
    ''', [("src/packaging/metadata.py", "_Validator._process_license_expression"),
          ("src/packaging/metadata.py", "Metadata")],
         "tests/test_metadata.py", "TestMetadata.test_valid_license_expression", 828),

    task("httpx-form-encoding", "httpx", "httpx-form-query-encoding", "holdout", '''
        import httpx
        RESULT = [str(httpx.QueryParams({"u": "with spaces"})),
                  str(httpx.QueryParams({"u": "with%20spaces"}))]
    ''', [("httpx/_urls.py", "QueryParams.__str__"),
          ("httpx/_urlparse.py", "percent_encoded")],
         "tests/models/test_url.py", "test_param_with_percent_encoded"),
    task("httpx-empty-params", "httpx", "httpx-3364", "holdout", '''
        import httpx
        request = httpx.Request("GET", "http://example.com?a=1", params={})
        RESULT = str(request.url)
    ''', [("httpx/_models.py", "Request.__init__"), ("httpx/_urls.py", "URL.__init__")],
         "tests/models/test_requests.py", "test_request_params", 3364),
    task("httpx-userinfo-encoding", "httpx", "httpx-3371-3373", "holdout", '''
        import httpx
        url = httpx.URL("https://example.org").copy_with(
            username="tom@example.org", password="abc123@ %")
        RESULT = str(url)
    ''', [("httpx/_urlparse.py", "urlparse"), ("httpx/_urlparse.py", "quote"),
          ("httpx/_urls.py", "URL.copy_with")],
         "tests/models/test_url.py", "test_url_copywith_userinfo_subcomponents", 3371),
    task("httpx-client-app", "httpx", "httpx-client-app-removal", "holdout", '''
        import httpx
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        client = httpx.Client(app=object(), transport=transport, trust_env=False)
        RESULT = client.is_closed
    ''', [("httpx/_client.py", "Client.__init__"),
          ("httpx/_client.py", "Client._init_transport")],
         "CHANGELOG.md", "0.28.0 removed app argument"),
    task("httpx-socks5h", "httpx", "httpx-3178", "holdout", '''
        import httpx
        proxy = httpx.Proxy("socks5h://localhost:1080")
        RESULT = [proxy.url.scheme, proxy.url.port]
    ''', [("httpx/_config.py", "Proxy.__init__")],
         "CHANGELOG.md", "0.28.0 socks5h support", 3178),

    task("pluggy-unblock", "pluggy", "pluggy-471", "holdout", '''
        import pluggy
        manager = pluggy.PluginManager("example")
        manager.set_blocked("plugin")
        first = manager.unblock("plugin")
        second = manager.unblock("plugin")
        RESULT = [first, second, manager.is_blocked("plugin")]
    ''', [("src/pluggy/_manager.py", "PluginManager.unblock"),
          ("src/pluggy/_manager.py", "PluginManager.set_blocked")],
         "testing/test_pluginmanager.py", "test_set_blocked", 471),
    task("pluggy-parameter-warning", "pluggy", "pluggy-178", "holdout", '''
        import pluggy
        import warnings
        hookspec = pluggy.HookspecMarker("example")
        hookimpl = pluggy.HookimplMarker("example")
        class Specification:
            @hookspec(warn_on_impl_args={"old": DeprecationWarning("deprecated old")})
            def run(self, old, new):
                pass
        class Plugin:
            @hookimpl
            def run(self, old):
                return old
        manager = pluggy.PluginManager("example")
        manager.add_hookspecs(Specification)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manager.register(Plugin())
        RESULT = [type(item.message).__name__ for item in caught]
    ''', [("src/pluggy/_hooks.py", "HookspecMarker.__call__"),
          ("src/pluggy/_manager.py", "PluginManager._verify_hook")],
         "testing/test_details.py", "test_warn_when_deprecated_args_specified", 178),
    task("pluggy-teardown-warning", "pluggy", "pluggy-463", "holdout", '''
        import pluggy
        import warnings
        hookspec = pluggy.HookspecMarker("example")
        hookimpl = pluggy.HookimplMarker("example")
        class Specification:
            @hookspec
            def run(self):
                pass
        class Plugin:
            @hookimpl(hookwrapper=True)
            def run(self):
                yield
                raise ValueError("teardown")
        manager = pluggy.PluginManager("example")
        manager.add_hookspecs(Specification)
        manager.register(Plugin(), "plugin")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                manager.hook.run()
            except ValueError:
                pass
        RESULT = [type(item.message).__name__ for item in caught]
    ''', [("src/pluggy/_callers.py", "_multicall"),
          ("src/pluggy/_callers.py", "_warn_teardown_exception")],
         "testing/test_warnings.py", "test_teardown_raised_warning", 463),
    task("pluggy-extra-order", "pluggy", "pluggy-441", "holdout", '''
        import pluggy
        hookspec = pluggy.HookspecMarker("example")
        hookimpl = pluggy.HookimplMarker("example")
        class Specification:
            @hookspec
            def run(self):
                pass
        class First:
            @hookimpl(tryfirst=True)
            def run(self):
                return "first"
        class Last:
            @hookimpl(trylast=True)
            def run(self):
                return "last"
        manager = pluggy.PluginManager("example")
        manager.add_hookspecs(Specification)
        manager.register(First())
        manager.register(Last())
        RESULT = manager.hook.run.call_extra([lambda: "extra"], {})
    ''', [("src/pluggy/_hooks.py", "HookCaller.call_extra"),
          ("src/pluggy/_callers.py", "_multicall")],
         "testing/test_hookcaller.py", "test_call_extra_hook_order", 441),

    task("attrs-nan-equality", "attrs", "attrs-1310", "holdout", '''
        import attrs
        @attrs.define
        class Record:
            value: float
        value = float("nan")
        RESULT = Record(value) == Record(value)
    ''', [("src/attr/_make.py", "_make_eq"),
          ("src/attr/_make.py", "_ClassBuilder.add_eq")],
         "CHANGELOG.md", "24.1.0 attribute equality behavior", 1310),
    task("attrs-makeclass-annotations", "attrs", "attrs-1285", "holdout", '''
        import attrs
        Record = attrs.make_class("Record", {"flag": attrs.field(type=bool)})
        RESULT = {name: value.__name__ for name, value in Record.__annotations__.items()}
    ''', [("src/attr/_make.py", "make_class")],
         "tests/test_make.py", "TestMakeClass.test_annotations", 1285),
    task("attrs-preinit-default", "attrs", "attrs-1319", "holdout", '''
        import attrs
        observed = []
        @attrs.define
        class Record:
            value: int = attrs.field(kw_only=True, default=3)
            def __attrs_pre_init__(self, *, value):
                observed.append(value)
        record = Record()
        RESULT = [observed, record.value]
    ''', [("src/attr/_make.py", "_attrs_to_init_script"),
          ("src/attr/_make.py", "_make_init_script")],
         "tests/test_make.py", "TestAttrs.test_pre_init_kw_only_work_with_defaults", 1319),
    task("attrs-frozen-exception", "attrs", "attrs-1365", "holdout", '''
        import attrs
        @attrs.frozen
        class Failure(Exception):
            pass
        error = Failure()
        error.__suppress_context__ = True
        error.__notes__ = ["note"]
        RESULT = [error.__suppress_context__, error.__notes__]
    ''', [("src/attr/_make.py", "_frozen_setattrs")],
         "tests/test_next_gen.py", "TestNextGen.test_setting_exception_mutable_attributes", 1365),
    task("attrs-subclass-hook", "attrs", "attrs-1321", "holdout", '''
        import attrs
        registry = []
        @attrs.define
        class Base:
            @classmethod
            def __attrs_init_subclass__(cls):
                registry.append(cls.__name__)
        @attrs.define
        class Child(Base):
            pass
        RESULT = registry
    ''', [("src/attr/_make.py", "_ClassBuilder.build_class")],
         "tests/test_functional.py", "TestAttrs.test_init_subclass", 1321),
    task("attrs-validator-hash", "attrs", "attrs-1320", "holdout", '''
        import attrs
        @attrs.define
        class Record:
            value: str = attrs.field(validator=attrs.validators.in_(["a", "b"]))
        field = attrs.fields(Record).value
        include = attrs.filters.include(field)
        RESULT = include(field, "a")
    ''', [("src/attr/validators.py", "in_"),
          ("src/attr/validators.py", "_InValidator"),
          ("src/attr/filters.py", "_split_what")],
         "tests/test_validators.py", "TestIn_.test_is_hashable", 1320),

    task("httpx-query-control", "httpx", "control-httpx-raw-query", "holdout", '''
        import httpx
        RESULT = str(httpx.URL("http://webservice?u=phrase%20with%20spaces"))
    ''', [("httpx/_urls.py", "URL.__init__"), ("httpx/_urlparse.py", "urlparse")],
         "tests/models/test_url.py", "test_query_with_existing_percent_encoding", category="control"),
    task("httpx-headers-control", "httpx", "control-httpx-headers", "holdout", '''
        import httpx
        headers = httpx.Headers({"Content-Type": "text/plain"})
        RESULT = [headers["content-type"], "CONTENT-TYPE" in headers]
    ''', [("httpx/_models.py", "Headers.__getitem__"),
          ("httpx/_models.py", "Headers.__contains__")],
         "tests/models/test_headers.py", "test_headers", category="control"),
    task("packaging-version-control", "packaging", "control-packaging-version", "holdout", '''
        from packaging.version import Version
        version = Version("2!1.4rc2.post3.dev1+linux.4")
        RESULT = [version.epoch, list(version.release), list(version.pre),
                  version.post, version.dev, version.local]
    ''', [("src/packaging/version.py", "Version.__init__"),
          ("src/packaging/version.py", "_parse_letter_version")],
         "tests/test_version.py", "TestVersion", category="control"),
    task("pluggy-unregistered-control", "pluggy", "control-pluggy-registration", "holdout", '''
        import pluggy
        manager = pluggy.PluginManager("example")
        plugin = object()
        manager.register(plugin, "plugin")
        RESULT = [manager.has_plugin("plugin"), manager.get_name(plugin),
                  manager.is_blocked("plugin")]
    ''', [("src/pluggy/_manager.py", "PluginManager.register"),
          ("src/pluggy/_manager.py", "PluginManager.has_plugin"),
          ("src/pluggy/_manager.py", "PluginManager.get_name")],
         "testing/test_pluginmanager.py", "test_pm_name", category="control"),
    task("attrs-converter-control", "attrs", "control-attrs-converter", "holdout", '''
        import attrs
        @attrs.define
        class Record:
            value: int = attrs.field(converter=int)
        record = Record("3")
        record.value = "4"
        RESULT = [record.value, type(record.value).__name__]
    ''', [("src/attr/setters.py", "convert"), ("src/attr/_next_gen.py", "define")],
         "tests/test_next_gen.py", "TestDefine.test_converts_and_validates_by_default", category="control"),
]


def validate_tasks() -> None:
    assert len(TASKS) == 30
    assert len({task["id"] for task in TASKS}) == len(TASKS)
    families = {}
    for entry in TASKS:
        previous = families.setdefault(entry["family"], entry["split"])
        assert previous == entry["split"], "a change family crosses the split"
        compile(entry["code"], entry["id"], "exec")
    assert sum(entry["split"] == "development" for entry in TASKS) == 5


validate_tasks()
