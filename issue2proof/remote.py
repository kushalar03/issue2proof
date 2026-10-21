"""Remote execution for the reviewed pricing fixture and restricted repairs only."""

import ast
import hashlib
import json

from .sandbox import SandboxConfig


def validate_source(source: str) -> None:
    """Accept only a bounded, pure arithmetic total function, never arbitrary Python."""
    if not isinstance(source, str) or len(source) > 2000:
        raise ValueError("Repair exceeds the restricted pricing source limit.")
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError):
        raise ValueError("Repair is not valid restricted Python.") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Repair must contain only the total function.")
    function = tree.body[0]
    args = function.args
    if (
        function.name != "total"
        or function.decorator_list
        or function.returns
        or getattr(function, "type_params", [])
        or args.posonlyargs
        or args.kwonlyargs
        or args.vararg
        or args.kwarg
        or args.defaults
        or args.kw_defaults
        or len(args.args) != 2
        or any(arg.annotation for arg in args.args)
        or len({arg.arg for arg in args.args}) != 2
        or {arg.arg for arg in args.args} & {"min", "max"}
    ):
        raise ValueError("Repair must define total with two plain arguments.")
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        raise ValueError("Repair must contain a single arithmetic return expression.")
    expression = body[0].value
    if expression is None:
        raise ValueError("Repair must return an arithmetic expression.")
    allowed = (
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.USub,
        ast.UAdd,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Call,
    )
    nodes = list(ast.walk(expression))
    if len(nodes) > 64:
        raise ValueError("Repair expression is too complex.")
    names = {arg.arg for arg in args.args}
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError("Only addition, subtraction, min and max are allowed.")  # noqa: TRY004 - source contract violation
        if isinstance(node, ast.Name) and node.id not in names | {"min", "max"}:
            raise ValueError("Repair references an unsupported name.")
        if isinstance(node, ast.Constant) and (
            type(node.value) is not int or abs(node.value) > 1000000
        ):
            raise ValueError("Repair constants must be bounded integers.")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name)
            or node.func.id not in {"min", "max"}
            or node.keywords
            or not 2 <= len(node.args) <= 4
        ):
            raise ValueError("Only bounded min and max calls are allowed.")


# Reviewed harness; candidate code cannot access files, imports or subprocesses.
HARNESS = """import hashlib, json, pathlib, subprocess, sys, importlib.metadata
import xml.etree.ElementTree as ET
root = pathlib.Path('/tmp/issue2proof')
manifest = json.loads((root / 'manifest.json').read_text())
def hashes():
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in manifest}
before = hashes()
command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '--junitxml=/tmp/results.xml', sys.argv[1]]
result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20,
    env={'PATH': '/usr/bin:/bin', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
summary = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
path = pathlib.Path('/tmp/results.xml')
if path.exists():
    for suite in ET.parse(path).getroot().iter('testsuite'):
        for key in summary: summary[key] += int(suite.get(key, '0'))
print(json.dumps({'exit_code': result.returncode, 'output': (result.stdout + result.stderr)[-12000:],
    'test_summary': summary, 'protected_tests_intact': before == manifest == hashes(),
    'python': sys.version, 'pytest': importlib.metadata.version('pytest')}))
"""


class RemoteRunner:
    def __init__(self, config: SandboxConfig, client=None):
        self.config = config
        if client is None:
            from contree_sdk import ContreeSync
            from contree_sdk.auth import IAMAuth
            from contree_sdk.config import ContreeConfig

            client = ContreeSync(
                config=ContreeConfig(
                    auth=IAMAuth(
                        token=config.key,
                        project_id=config.project_id,
                        base_url=config.base_url,
                    ),
                    transport_timeout=20,
                    operation_timeout=40,
                    default_truncate_output_at=20000,
                )
            )
        self.client = client

    def execute(self, source: str, test_name: str, test_source: str) -> dict:
        from .fixtures import EXISTING, INDEPENDENT, REGRESSION

        validate_source(source)
        reviewed = {
            "test_existing.py": EXISTING,
            "test_regression.py": REGRESSION,
            "test_independent.py": INDEPENDENT,
        }
        if reviewed.get(test_name) != test_source:
            raise ValueError("Only reviewed test files may execute.")
        digest = hashlib.sha256(test_source.encode()).hexdigest()
        files = {
            "/tmp/issue2proof/pricing.py": source.encode(),
            f"/tmp/issue2proof/{test_name}": test_source.encode(),
            "/tmp/issue2proof/manifest.json": json.dumps({test_name: digest}).encode(),
            "/tmp/issue2proof-harness.py": HARNESS.encode(),
        }
        result = (
            self.client.images.use(self.config.image)
            .run(
                command="/usr/bin/env",
                args=["python3", "-I", "/tmp/issue2proof-harness.py", test_name],
                files=files,
                env={},
                preserve_env=False,
                timeout=30,
                disposable=True,
                truncate_output_at=20000,
            )
            .wait()
            .result
        )
        report = {
            "command": f"python -m pytest -q --tb=short {test_name}",
            "exit_code": result.exit_code,
            "output": "Remote execution evidence unavailable.",
            "seconds": result.elapsed_time.total_seconds(),
            "cost": result.cost,
            "output_truncated": result.truncated,
            "evidence_valid": False,
            "protected_tests_intact": False,
            "image": self.config.image,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "test_sha256": digest,
        }
        if result.exit_code != 0 or result.truncated:
            return report
        try:
            evidence = json.loads(result.stdout)
            summary = evidence["test_summary"]
            valid = (
                type(evidence["exit_code"]) is int
                and evidence["exit_code"] in {0, 1}
                and evidence["protected_tests_intact"] is True
                and all(
                    type(summary[k]) is int and summary[k] >= 0
                    for k in ("tests", "failures", "errors", "skipped")
                )
                and summary["tests"] == 1
                and summary["errors"] == 0
                and summary["skipped"] == 0
                and summary["failures"] == evidence["exit_code"]
                and isinstance(evidence["output"], str)
                and isinstance(evidence["python"], str)
                and isinstance(evidence["pytest"], str)
            )
        except (ValueError, KeyError, TypeError):
            return report
        if valid:
            report.update(evidence, evidence_valid=True)
        return report
