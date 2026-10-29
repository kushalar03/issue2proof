"""Network-disabled disposable repository checks with a separate trusted controller."""

import base64
import hashlib
import json
import time
from pathlib import PurePosixPath

from .sandbox import SandboxConfig, resolve_image

# Root controller owns the immutable files. All repository/model code runs as
# uid/gid 65534 with no-new-privileges, resource limits, and no guest network.
CONTROLLER = r"""
import ctypes, hashlib, importlib.metadata, json, os, pathlib, resource, signal, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
payload = json.load(sys.stdin)
root = pathlib.Path('/work')
root.mkdir(exist_ok=True)
for name, source in payload['files'].items():
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o444)
for path in sorted(root.rglob('*'), reverse=True):
    if path.is_dir(): path.chmod(0o555)
root.chmod(0o555)
def hashes():
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in payload['files']}
before = hashes()
private = pathlib.Path(tempfile.mkdtemp(prefix='i2p-controller-'))
private.chmod(0o700)
output_path = private / 'pytest.log'
# The pytest report is writable by the guest test process, so treat its contents
# as test evidence, never as a security proof against adversarial Python.
report_path = pathlib.Path('/tmp/i2p-results')
report_path.mkdir(mode=0o777, exist_ok=True)
report_path.chmod(0o777)
xml = report_path / 'results.xml'
def restrict():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError('no_new_privs unavailable')
    for kind, limit in [(resource.RLIMIT_AS, 512*1024*1024), (resource.RLIMIT_CPU, 15), (resource.RLIMIT_NPROC, 32), (resource.RLIMIT_FSIZE, 1024*1024), (resource.RLIMIT_NOFILE, 128)]:
        resource.setrlimit(kind, (limit, limit))
build = None
if payload.get('install_project'):
    build_code = "import os,pathlib,shutil,subprocess,sys,tempfile; target=tempfile.mkdtemp()+'/project';shutil.copytree('/work',target); paths=[pathlib.Path(target),*pathlib.Path(target).rglob('*')];[(p.chmod(0o755 if p.is_dir() else 0o644)) for p in paths];raise SystemExit(subprocess.call([sys.executable,'-m','pip','install','--no-deps','--no-build-isolation','--no-index','--disable-pip-version-check','--target','/tmp/i2p-package',target]))"
    with (private/'build.log').open('wb') as log:
        child=subprocess.Popen([sys.executable,'-c',build_code],stdout=log,stderr=subprocess.STDOUT,preexec_fn=restrict,start_new_session=True,
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONPATH':'/opt/i2p-deps','HOME':'/tmp'})
        try: code=child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait();code=124
        finally:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
    build={'exit_code':code,'output':(private/'build.log').read_bytes()[:16000].decode('utf-8',errors='replace'),'network_disabled':True,'uid':65534}
    if code!=0:
        print(json.dumps({'exit_code':code,'output':build['output'],'summary':{'tests':0,'failures':0,'errors':1,'skipped':0},'build':build,'files_intact':before==hashes(),'input_hashes':before}))
        raise SystemExit(0)
command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '-c', '/dev/null', '-p', 'no:cacheprovider', '--junitxml='+str(xml), *payload['tests']]
timed_out = False
python_paths = [pathlib.Path('/tmp/i2p-package'), root, root/'src', root/'tests', root/'test', root/'lib', pathlib.Path('/opt/i2p-deps')]
with output_path.open('wb') as log:
    process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, preexec_fn=restrict,
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONPATH':':'.join(map(str,python_paths)), 'PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','HOME':'/tmp'})
    try: exit_code = process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        exit_code = 124
    finally:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
size = output_path.stat().st_size
output = output_path.read_bytes()[:20000].decode('utf-8',errors='replace')
summary = {'tests':0, 'failures':0, 'errors':0, 'skipped':0}
assertion_failures = 0
failure_nodes = []
if xml.exists() and xml.stat().st_size <= 1000000:
    try:
        tree = ET.parse(xml)
        for suite in tree.getroot().iter('testsuite'):
            for key in summary: summary[key] += int(suite.get(key,'0'))
        for test in tree.getroot().iter('testcase'):
            for failure in test.findall('failure'):
                message=failure.get('message','')
                failure_type=failure.get('type','')
                if (message.startswith('assert ') or 'AssertionError' in message or 'DID NOT RAISE' in message
                    or 'DID NOT WARN' in message or message.startswith('Failed:') or failure_type in {'Failed','AssertionError'}):
                    assertion_failures += 1
                    failure_nodes.append(test.get('classname','')+'::'+test.get('name',''))
    except (ET.ParseError,ValueError): pass
pytest_version=next((item.version for item in importlib.metadata.distributions(path=['/opt/i2p-deps']) if item.metadata['Name'].lower()=='pytest'),None)
if pytest_version is None: pytest_version=importlib.metadata.version('pytest')
print(json.dumps({'exit_code':exit_code,'output':output,'output_truncated':size>20000,'timed_out':timed_out,
    'summary':summary,'assertion_failures':assertion_failures,'failure_nodes':failure_nodes,
    'files_intact':before==hashes(),'input_hashes':before,'python':sys.version,'pytest':pytest_version,
    'build':build,'uid':65534,'no_new_privileges':True,'limits':{'memory_bytes':536870912,'cpu_seconds':15,'processes':32,'file_bytes':1048576,'wall_seconds':20}}))
"""


class SandboxExecutor:
    def __init__(self, config=None, client=None, context=None):
        from contree_client.httpx import ContreeClient
        from contree_client.runtime import RetryPolicy

        self.context = context
        self.config = config or SandboxConfig.from_env()
        if client is None:
            self.config = resolve_image(self.config)
        self.client = client or ContreeClient(
            self.config.key,
            project=self.config.project_id,
            base_url=self.config.base_url,
            timeout=25,
            retry=RetryPolicy(max_attempts=2),
        )

    def close(self):
        self.client.close()

    def run(
        self, code: str, payload=None, timeout=35, *, network=False, disposable=True
    ) -> dict:
        from contree_client.models import (
            ClosableStreamRepr,
            InstanceNetworking,
            InstanceResourcesLimits,
        )

        reservation = None
        if self.context:
            reservation = self.context.reserve("environment" if network else "sandbox")
        started = time.monotonic()
        operation = self.client.spawn_instance(
            command="/usr/local/bin/python",
            image=self.config.image,
            args=["-I", "-c", code],
            shell=False,
            env={},
            preserve_env=False,
            disposable=disposable,
            networking=InstanceNetworking(enabled=network),
            resources_limits=InstanceResourcesLimits(
                max_layer_bytes=(512 if network else 64) * 1024 * 1024
            ),
            stdin=ClosableStreamRepr(
                value=base64.b64encode(json.dumps(payload or {}).encode()).decode(),
                encoding="base64",
            ),
            timeout=timeout,
            truncate_output_at=40000,
        )
        try:
            if self.context:
                self.context.operation(operation.uuid)
            completed = self.client.wait_operation(operation.uuid, timeout=timeout + 15)
        except Exception:
            self.client.cancel_operation(operation.uuid)
            raise
        if self.context:
            self.context.operation(None)
        data = completed.to_dict()
        metadata = data.get("metadata", {})
        result = metadata.get("result", {})

        def decode(stream):
            value = stream.get("value", "")
            return (
                base64.b64decode(value).decode("utf-8", errors="replace")
                if stream.get("encoding") == "base64"
                else value
            )

        report = {
            "operation_id": operation.uuid,
            "status": data.get("status"),
            "exit_code": result.get("state", {}).get("exit_code"),
            "timed_out": result.get("state", {}).get("timed_out"),
            "stdout": decode(result.get("stdout", {})),
            "stderr": decode(result.get("stderr", {})),
            "output_truncated": bool(
                result.get("stdout", {}).get("truncated")
                or result.get("stderr", {}).get("truncated")
            ),
            "cost": result.get("resources", {}).get("cost"),
            "seconds": round(time.monotonic() - started, 3),
            "image": self.config.image,
            "network_disabled": metadata.get("networking", {}).get("enabled") is False,
            "disposable": metadata.get("disposable") is True,
            "result_image": data.get("result", {}).get("image"),
        }
        if self.context:
            self.context.reconcile(reservation, report["cost"])
        return report

    def execute(self, files: dict, tests: list[str], *, install_project=False) -> dict:
        if not tests or len(json.dumps(files)) > 3_000_000:
            raise ValueError("Provide a bounded project and explicit test paths.")
        for name in files:
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or str(path) != name
                or "\\" in name
            ):
                raise ValueError("Unsafe execution path.")
        if any(name not in files for name in tests):
            raise ValueError("Test paths must exist in the execution bundle.")
        expected = {
            name: hashlib.sha256(source.encode()).hexdigest()
            for name, source in files.items()
        }
        remote = self.run(
            CONTROLLER,
            {"files": files, "tests": tests, "install_project": install_project},
            timeout=60 if install_project else 35,
        )
        report = {
            **remote,
            "sandbox_exit_code": remote["exit_code"],
            "command": "python -m pytest " + " ".join(tests),
            "output": remote["stderr"],
            "evidence_valid": False,
        }
        if (
            remote["exit_code"] != 0
            or remote["output_truncated"]
            or not remote["network_disabled"]
            or not remote["disposable"]
        ):
            report["evidence_error"] = "sandbox_controller_failed"
            report["output"] = remote["stderr"] or remote["stdout"][-20000:]
            report.pop("stdout", None)
            return report
        try:
            evidence = json.loads(remote["stdout"])
            report.update(evidence)
            summary = evidence.get("summary", {})
            valid = (
                evidence.get("files_intact") is True
                and evidence.get("input_hashes") == expected
                and evidence.get("uid") == 65534
                and evidence.get("no_new_privileges") is True
                and evidence.get("timed_out") is False
                and evidence.get("output_truncated") is False
                and type(evidence.get("exit_code")) is int
                and evidence.get("exit_code") in {0, 1}
                and all(
                    type(summary.get(k)) is int and summary[k] >= 0
                    for k in ("tests", "failures", "errors", "skipped")
                )
                and summary["tests"] > 0
                and summary["errors"] == 0
                and summary["failures"] + summary["skipped"] <= summary["tests"]
                and summary["failures"] <= summary["tests"]
                and ((summary["failures"] == 0) == (evidence["exit_code"] == 0))
            )
            if valid:
                report["evidence_valid"] = True
            elif (evidence.get("build") or {}).get("exit_code") not in {None, 0}:
                report["evidence_error"] = "project_install_failed"
            elif evidence.get("timed_out") or evidence.get("exit_code") == 124:
                report["evidence_error"] = "test_timeout"
            elif evidence.get("exit_code") not in {0, 1}:
                report["evidence_error"] = "pytest_setup_or_collection_failed"
            elif summary.get("errors", 0):
                report["evidence_error"] = "pytest_errors"
            elif summary.get("tests", 0) == 0:
                report["evidence_error"] = "no_tests_collected"
            else:
                report["evidence_error"] = "integrity_evidence_invalid"
        except (ValueError, KeyError, TypeError):
            report["evidence_error"] = "controller_evidence_invalid_json"
            report["output"] = remote["stderr"] or remote["stdout"][-20000:]
        report.pop("stdout", None)
        return report


def verify_repository(report: dict, executor=None) -> dict:
    report = {**report, "events": list(report["events"])}
    if not report.get("draft_changes"):
        raise ValueError("Generate a repair draft before verification.")
    if any(
        name not in report["sources"]
        or hashlib.sha256(source.encode()).hexdigest()
        != report.get("candidate_hashes", {}).get(name)
        for name, source in report["draft_changes"].items()
    ):
        raise ValueError("Candidate paths or source hashes changed after drafting.")
    if any(
        hashlib.sha256(source.encode()).hexdigest() != report["file_hashes"].get(name)
        for name, source in report["sources"].items()
    ):
        raise ValueError("Original implementation changed after inspection.")
    frozen = report.get("test_hashes", {})
    if any(
        hashlib.sha256(source.encode()).hexdigest() != frozen.get(name)
        for name, source in report["existing_tests"].items()
    ):
        raise ValueError("Frozen existing tests changed after drafting.")
    regression = report["generated_regression"]
    if hashlib.sha256(regression["source"].encode()).hexdigest() != frozen.get(
        regression["path"]
    ):
        raise ValueError("Frozen regression changed after drafting.")
    executor_owned = executor is None
    executor = executor or SandboxExecutor()
    checks = {}
    report["verification"] = checks
    report["verdict"] = "verification_failed"
    try:
        independent = {
            name: source
            for name, source in report["existing_tests"].items()
            if name in report.get("independent_test_paths", [])
        }
        existing = {
            name: source
            for name, source in report["existing_tests"].items()
            if name not in independent
        }

        def execute(sources, tests):
            return executor.execute(
                {**sources, **report["existing_tests"], **tests}, list(tests)
            )

        def passed(check):
            return check.get("evidence_valid") is True and check["exit_code"] == 0

        if not existing or not independent:
            report["explanation"] = (
                "Reserve independent tests and retain at least one existing test before live verification."
            )
            return report
        checks["baseline"] = execute(report["sources"], existing)
        checks["independent_baseline"] = execute(report["sources"], independent)
        # Independent baseline may fail for the reported bug. It must be valid evidence.
        if not passed(checks["baseline"]) or not checks["independent_baseline"].get(
            "evidence_valid"
        ):
            report["explanation"] = (
                "Original existing tests or independent setup failed; no repair accepted."
            )
            return report
        checks["reproduction"] = execute(
            report["sources"], {regression["path"]: regression["source"]}
        )
        reproduction = checks["reproduction"]
        if not (
            reproduction.get("evidence_valid")
            and reproduction["exit_code"] == 1
            and reproduction.get("assertion_failures", 0)
            == reproduction["summary"]["failures"]
            and reproduction["summary"]["failures"] > 0
        ):
            report.update(
                verdict="not_reproduced",
                explanation="Generated regression did not produce a clean assertion failure on the original implementation.",
            )
            return report
        sources = {**report["sources"], **report["draft_changes"]}
        for label, tests in [
            ("regression", {regression["path"]: regression["source"]}),
            ("existing", existing),
            ("independent", independent),
        ]:
            checks[label] = execute(sources, tests)
        if all(
            passed(checks[label]) for label in ("regression", "existing", "independent")
        ):
            report.update(
                verdict="checks_passed",
                explanation="Original assertion failure reproduced. Candidate passed frozen regression, existing and reserved independent checks in separate network-disabled sandboxes.",
            )
        else:
            report.update(
                verdict="unresolved",
                explanation="Candidate failed one or more checks; no passing repair accepted.",
            )
        report["events"].append(
            "Remote tests ran as an unprivileged user against root-owned files with no guest network; controller collected bounded evidence."
        )
    except Exception as error:  # noqa: BLE001 - keep credential-bearing errors out of evidence
        report.update(
            error_type=type(error).__name__,
            explanation="Remote verification failed; inspect completed check evidence.",
        )
    finally:
        if executor_owned:
            executor.close()
    report["limitations"] = [
        "Passing checks cover the listed inputs only, not universal correctness.",
        "Arbitrary Python can tamper with its own pytest process; checks_passed is execution evidence, not adversarial proof.",
        "Dependencies must already exist in the selected immutable image. No uploaded setup scripts or package installers run.",
    ]
    return report
