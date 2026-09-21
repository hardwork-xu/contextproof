"""Hand-specified controlled dependency cases, independent of the implementation.

These fixtures define expected *static witness* outcomes, not runtime behavior.
The benchmark runner may measure them but must never derive their labels from
the resolver. ``after`` replaces files and uses None for deletion.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyCase:
    name: str
    before: dict[str, str]
    after: dict[str, str | None]
    expected: str
    category: str
    path: str = "app.py"
    symbol: str = "subject"


APP = "def subject():\n    return helper()\n"
HELPER = "def helper():\n    return 1\n"
LOCAL = HELPER + "\n" + APP
IMPORTED = "from helpers import helper\n\n" + APP

CASES = (
    DependencyCase("same_local_helper", {"app.py": LOCAL}, {}, "unchanged", "unchanged"),
    DependencyCase("changed_local_helper", {"app.py": LOCAL},
                   {"app.py": LOCAL.replace("return 1", "return 2")}, "changed", "mutation"),
    DependencyCase("unrelated_file", {"app.py": LOCAL, "other.py": "VALUE = 1\n"},
                   {"other.py": "VALUE = 2\n"}, "unchanged", "negative_control"),
    DependencyCase("unrelated_definition", {"app.py": LOCAL + "\ndef other():\n    return 9\n"},
                   {"app.py": LOCAL + "\ndef other():\n    return 10\n"},
                   "unchanged", "negative_control"),
    DependencyCase("line_insertion", {"app.py": LOCAL},
                   {"app.py": "# inserted\n\n" + LOCAL}, "unchanged", "relocation"),
    DependencyCase("imported_change", {"app.py": IMPORTED, "helpers.py": HELPER},
                   {"helpers.py": HELPER.replace("return 1", "return 2")}, "changed", "import"),
    DependencyCase("from_alias", {"app.py": "from helpers import helper as h\ndef subject():\n    return h()\n",
                                  "helpers.py": HELPER},
                   {"helpers.py": HELPER.replace("return 1", "return 2")}, "changed", "alias"),
    DependencyCase("module_alias", {"app.py": "import helpers as h\ndef subject():\n    return h.helper()\n",
                                    "helpers.py": HELPER}, {}, "unchanged", "alias"),
    DependencyCase("module_attribute", {"app.py": "import helpers\ndef subject():\n    return helpers.helper()\n",
                                        "helpers.py": HELPER},
                   {"helpers.py": HELPER.replace("return 1", "return 2")}, "changed", "import"),
    DependencyCase("alias_retarget_identical_definition",
                   {"app.py": IMPORTED, "helpers.py": HELPER, "alternate.py": HELPER},
                   {"app.py": IMPORTED.replace("from helpers", "from alternate")},
                   "changed", "binding"),
    DependencyCase("deleted_dependency_file", {"app.py": IMPORTED, "helpers.py": HELPER},
                   {"helpers.py": None}, "missing", "deletion"),
    DependencyCase("deleted_definition", {"app.py": IMPORTED, "helpers.py": HELPER},
                   {"helpers.py": "OTHER = 1\n"}, "missing", "deletion"),
    DependencyCase("duplicate_definition", {"app.py": LOCAL + "\n" + HELPER},
                   {}, "unresolved", "ambiguity"),
    DependencyCase("new_duplicate_definition", {"app.py": LOCAL},
                   {"app.py": LOCAL + "\n" + HELPER}, "unresolved", "ambiguity"),
    DependencyCase("external_import", {"app.py": "import math\ndef subject():\n    return math.sqrt(4)\n"},
                   {}, "unresolved", "external"),
    DependencyCase("callable_parameter", {"app.py": "def subject(callback):\n    return callback()\n"},
                   {}, "unresolved", "dynamic"),
    DependencyCase("dynamic_method", {"app.py": "def subject(obj):\n    return obj.run()\n"},
                   {}, "unresolved", "dynamic"),
    DependencyCase("call_returned_callable", {"app.py": HELPER + "\ndef subject():\n    return helper()()\n"},
                   {}, "unresolved", "dynamic"),
    DependencyCase("changed_called_expression", {"app.py": LOCAL + "\ndef other():\n    return 2\n"},
                   {"app.py": LOCAL.replace("return helper()", "return other()")
                    + "\ndef other():\n    return 2\n"}, "changed", "caller"),
    DependencyCase("constant_change", {"app.py": "LIMIT = 1\ndef subject():\n    return LIMIT\n"},
                   {"app.py": "LIMIT = 2\ndef subject():\n    return LIMIT\n"}, "changed", "constant"),
    DependencyCase("imported_constant", {"app.py": "from settings import LIMIT\ndef subject():\n    return LIMIT\n",
                                         "settings.py": "LIMIT = 1\n"},
                   {"settings.py": "LIMIT = 2\n"}, "changed", "constant"),
    DependencyCase("recursive_call", {"app.py": "def subject(n):\n    return subject(n - 1) if n else 0\n"},
                   {}, "unchanged", "cycle"),
    DependencyCase("import_cycle",
                   {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
                    "helpers.py": "from app import subject\ndef helper():\n    return subject()\n"},
                   {}, "unchanged", "cycle"),
    DependencyCase("reexport_cycle",
                   {"app.py": "from a import helper\ndef subject():\n    return helper()\n",
                    "a.py": "from b import helper\n", "b.py": "from a import helper\n"},
                   {}, "unresolved", "cycle"),
    DependencyCase("relative_import",
                   {"pkg/__init__.py": "", "pkg/app.py": "from .helpers import helper\n" + APP,
                    "pkg/helpers.py": HELPER},
                   {"pkg/helpers.py": HELPER.replace("return 1", "return 2")},
                   "changed", "import", path="pkg/app.py"),
    DependencyCase("src_layout",
                   {"app.py": "from pkg.helpers import helper\n" + APP,
                    "src/pkg/__init__.py": "", "src/pkg/helpers.py": HELPER},
                   {}, "unchanged", "import"),
    DependencyCase("ambiguous_module",
                   {"app.py": IMPORTED, "helpers.py": HELPER, "src/helpers.py": HELPER},
                   {}, "unresolved", "ambiguity"),
    DependencyCase("wildcard_import", {"app.py": "from helpers import *\n" + APP,
                                       "helpers.py": HELPER}, {}, "unresolved", "ambiguity"),
    DependencyCase("local_shadow", {"app.py": HELPER + "\ndef subject(helper):\n    return helper()\n"},
                   {}, "unresolved", "dynamic"),
    DependencyCase("one_hop_boundary",
                   {"app.py": LOCAL.replace("return 1", "return leaf()")
                    + "\ndef leaf():\n    return 10\n"},
                   {"app.py": LOCAL.replace("return 1", "return leaf()")
                    + "\ndef leaf():\n    return 11\n"},
                   "unchanged", "scope_limit"),
    DependencyCase("syntax_error_dependency", {"app.py": IMPORTED, "helpers.py": HELPER},
                   {"helpers.py": "def helper(:\n"}, "unresolved", "syntax"),
    DependencyCase("no_dependencies", {"app.py": "def subject(value):\n    return value + 1\n"},
                   {}, "unchanged", "negative_control"),
    DependencyCase("selected_external_import", {"app.py": "import math\n"},
                   {}, "unresolved", "external", symbol="<module>"),
    DependencyCase("selected_from_import", {"app.py": "from helpers import helper\n", "helpers.py": HELPER},
                   {"helpers.py": HELPER.replace("return 1", "return 2")},
                   "changed", "import", symbol="<module>"),
)
