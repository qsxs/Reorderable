"""Reorderable 3.1.0 的独立 OHOS producer；不部署、不读取凭据。"""
from __future__ import annotations

import argparse
import time
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
from urllib.request import ProxyHandler, build_opener
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOL_REVISION = "d0cff88fd1ea2e4f08bb4409f1c802cca0c7f285"
TOOL_DIR = "toolchains/kotlin-native/2.4.20-0.1.0-08"
GROUP = "io.github.qsxs.cpf.reorderable"
MODULE = "reorderable"
ROOT = HERE.parent
physical = Path
TASKS = {"Tasks": ["tasks", "--all"], "Resolve": ["resolveReorderable"], "Metadata": ["recordReorderableMetadata"],
         "NativeX64": ["recordReorderableX64"], "NativeArm64": ["recordReorderableArm64"], "Publish": ["publishReorderable"]}
COMPILES = (("Metadata", "metadata", None), ("NativeX64", "native-x64", "ohos_x64"),
            ("NativeArm64", "native-arm64", "ohos_arm64"))
REQUIRED = {"resolveReorderable", "compileCommonMainKotlinMetadata", "compileKotlinOhosX64",
            "compileKotlinOhosArm64", "allMetadataJar", "recordReorderableMetadata", "recordReorderableX64", "recordReorderableArm64", "publishReorderable"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def record(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path.resolve()), "size": len(data), "sha256": digest(data)}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as output:
            output.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def safe_environment(work=None):
    env = {key: os.environ[key] for key in ("PATH", "HOME", "JAVA_HOME", "LANG", "LC_ALL", "SSL_CERT_FILE",
                                              "SSL_CERT_DIR", "LD_LIBRARY_PATH") if key in os.environ}
    if work is not None:
        for key, folder in (("GRADLE_USER_HOME", "gradle-home"), ("KONAN_DATA_DIR", "konan"),
                            ("TMPDIR", "temp"), ("TEMP", "temp"), ("TMP", "temp")):
            path = Path(work) / folder
            path.mkdir(parents=True, exist_ok=True)
            env[key] = str(path)
    return env


def checked_tools(work, explicit):
    lock = load(HERE / "tooling-lock.json")
    if lock["revision"] != TOOL_REVISION or lock["repository"] != "https://github.com/qsxs/cpf-port-tooling":
        raise RuntimeError("Immutable shared tooling revision differs")
    if lock["archiveUrl"] != lock["repository"] + "/archive/" + TOOL_REVISION + ".tar.gz":
        raise RuntimeError("Shared tooling archive URL differs")
    if len(lock["files"]) != 20 or len({row["path"] for row in lock["files"]}) != 20:
        raise RuntimeError("Shared tooling file lock differs")
    directory = Path(explicit).resolve() if explicit else (work / "tooling" / TOOL_REVISION).resolve()
    for row in lock["files"]:
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in row["path"] or not row["path"].startswith(TOOL_DIR + "/"):
            raise RuntimeError("Unsafe shared tooling file path")
    if not explicit and not all((directory / row["path"]).is_file() for row in lock["files"]):
        # 仅读取锁定文件；归档压缩容器本身不作为内容身份。
        with build_opener(ProxyHandler({})).open(lock["archiveUrl"], timeout=60) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise RuntimeError("Shared tooling archive is too large")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            for row in lock["files"]:
                matches = [member for member in members if "/" in member.name and member.name.split("/", 1)[1] == row["path"]]
                if len(matches) != 1 or not matches[0].isfile():
                    raise RuntimeError("Shared tooling archive member differs: " + row["path"])
                stream = archive.extractfile(matches[0])
                if stream is None:
                    raise RuntimeError("Shared tooling archive member is unreadable")
                content = stream.read(row["size"] + 1)
                if len(content) != row["size"] or digest(content) != row["sha256"]:
                    raise RuntimeError("Shared tooling archive bytes differ: " + row["path"])
                target = directory / row["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.read_bytes() != content:
                        raise RuntimeError("Existing shared tooling bytes differ")
                else:
                    with target.open("xb") as out:
                        out.write(content)
    for row in lock["files"]:
        actual = record(directory / row["path"])
        if (actual["size"], actual["sha256"]) != (row["size"], row["sha256"]):
            raise RuntimeError("Shared tooling identity differs: " + row["path"])
    return directory


def source_facts():
    model = load(HERE / "source-inputs.json")
    config = load(HERE / "port-config.json")
    source_root = (HERE / config["sourceRoot"]).resolve()
    expected = {row["member"]: row for row in model["sourceMembers"]}
    actual = {"commonMain/" + path.relative_to(source_root).as_posix() for path in source_root.rglob("*.kt")}
    if len(expected) != 9 or actual != set(expected) or model["upstream"]["commit"] != "66de5751227c440bcdbd63acc94999231ed67487":
        raise RuntimeError("Reorderable original Kotlin source inventory differs")
    for key in ("sources", "pom", "gmm", "upstreamBuild", "license"):
        item = model[key]
        found = record(HERE / item["path"])
        if (found["size"], found["sha256"]) != (item["size"], item["sha256"]):
            raise RuntimeError("Official upstream input differs: " + key)
    wrapper = {"gradle/wrapper/gradle-wrapper.jar": "7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172",
               "gradle/wrapper/gradle-wrapper.properties": "93b4f2c5ddcfc9e6f630fc7e004b31b389695cd0228be6da42e196e5d4af7acb"}
    for path, expected_hash in wrapper.items():
        if record(HERE / path)["sha256"] != expected_hash:
            raise RuntimeError("Approved Gradle wrapper differs: " + path)
    plugin_tools = load(HERE / "compiler-plugin-toolchain.json")
    for key in ("sourcePom",):
        plugin_pom = plugin_tools[key]
        actual_pom = record(HERE / plugin_pom["path"])
        if (actual_pom["size"], actual_pom["sha256"]) != (plugin_pom["size"], plugin_pom["sha256"]):
            raise RuntimeError("Compiler plugin provenance differs: " + key)
    rows = []
    with zipfile.ZipFile(HERE / model["sources"]["path"]) as archive:
        names = archive.namelist()
        if len(names) != model["archiveEntryCount"] or len(set(names)) != len(names) or {name for name in names if name.endswith(".kt")} != set(expected):
            raise RuntimeError("Official source archive inventory differs")
        for member, item in sorted(expected.items()):
            path = source_root / member.removeprefix("commonMain/")
            data = path.read_bytes()
            if len(data) != item["size"] or digest(data) != item["sha256"] or archive.read(member) != data:
                raise RuntimeError("Original Reorderable source bytes differ: " + member)
            rows.append({"member": member, **record(path)})
    compact = [{key: row[key] for key in ("member", "size", "sha256")} for row in rows]
    if digest(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()) != model["sourceSetSha256"]:
        raise RuntimeError("Reorderable source set hash differs")
    return model, rows


def output_roots(args):
    root = HERE.resolve()
    work, repository = Path(args.work).resolve(), Path(args.repository).resolve()
    outputs = (work, repository)
    if any(root.is_relative_to(output) for output in outputs):
        raise RuntimeError("Work and repository must not be or contain the recipe root")
    prepared = work / "prepared.json"
    if prepared.is_file():
        previous = load(prepared)
        if (previous["work"], previous["repository"]) != (str(work), str(repository)):
            raise RuntimeError("Prepared output paths differ")
        for item in previous["recipe"]:
            path = (root / item["path"]).resolve()
            if any(path.is_relative_to(output) for output in outputs):
                raise RuntimeError("Output path contains a recorded recipe file")
    else:
        for output in outputs:
            if output.is_relative_to(root) and output.exists():
                if output.is_file() or any(path.is_file() for path in output.rglob("*")):
                    raise RuntimeError("New output directories inside the recipe must be empty")
    return outputs


def recipe_inputs(outputs):
    root = HERE.resolve()
    recipe = []
    for current, directories, files in os.walk(root):
        parent = Path(current)
        directories[:] = [name for name in directories
                          if name not in (".gradle", ".kotlin", "build", "__pycache__")
                          and not any((parent / name).resolve().is_relative_to(output) for output in outputs)]
        for name in files:
            path = parent / name
            if path.is_file() and not any(path.resolve().is_relative_to(output) for output in outputs):
                data = path.read_bytes()
                recipe.append({"path": path.relative_to(root).as_posix(), "size": len(data), "sha256": digest(data)})
    return sorted(recipe, key=lambda item: item["path"])


def identity(args, tools, outputs):
    config = load(HERE / "port-config.json")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha) or not re.fullmatch(r"[1-9][0-9]*", args.run_id) or not re.fullmatch(r"[1-9][0-9]*", args.run_attempt):
        raise RuntimeError("Immutable source SHA and positive run identifiers are required")
    actual = subprocess.run(["git", "-C", str(HERE.parent), "rev-parse", "HEAD"], env=safe_environment(), check=True, capture_output=True, text=True).stdout.strip()
    if actual != args.source_sha:
        raise RuntimeError("Reorderable checkout differs from requested source SHA")
    if config["modules"][MODULE]["group"] != GROUP or config["kotlin"] != "2.4.20-0.1.0-08" or config["metadataPolicy"] != "STANDARD_LOCKED_KGP_METADATA_NO_FALLBACK":
        raise RuntimeError("Reorderable port identity differs")
    model, rows = source_facts()
    recipe = recipe_inputs(outputs)
    value = {"sourceCommit": args.source_sha, "sourceTagCommit": model["upstream"]["commit"], "sources": rows,
             "recipe": recipe, "toolingCommit": TOOL_REVISION, "toolingFiles": load(HERE / "tooling-lock.json")["files"],
             "group": GROUP, "version": "3.1.0-cpf11-preview-" + args.source_sha[:12] + "-" + args.run_id + "-" + args.run_attempt}
    # 指纹不含机器路径；源码使用稳定的成员名、大小和哈希。
    fingerprint_value = {**value, "sources": [{key: row[key] for key in ("member", "size", "sha256")} for row in rows]}
    value["fingerprint"] = digest(json.dumps(fingerprint_value, sort_keys=True, separators=(",", ":")).encode())
    value["toolingHome"] = str(tools)
    value["work"] = str(outputs[0])
    value["repository"] = str(outputs[1])
    return value


def check_native(home):
    if not home:
        raise RuntimeError("Explicit Kotlin/Native home is required")
    props = dict(line.split("=", 1) for line in (Path(home) / "konan/konan.properties").read_text(encoding="utf-8").splitlines() if "=" in line)
    if props.get("compilerVersion", "").strip() != "2.4.20-0.1.0-08":
        raise RuntimeError("Kotlin/Native compilerVersion differs")


def verify_stage(value, evidence):
    work = Path(value["work"])
    model = load(HERE / "source-inputs.json")
    row = load(work / "evidence" / (evidence + ".json"))
    if (row["fingerprint"] != value["fingerprint"] or row["stage"] != evidence or row["sourceCount"] != 9 or
            row["sourceSetSha256"] != model["sourceSetSha256"] or row["sourceManifest"] != record(work / "source-manifest.json")):
        raise RuntimeError("Reorderable compile source identity differs: " + evidence)
    expected_sources = {}
    for source in model["sourceMembers"]:
        path = (HERE / load(HERE / "port-config.json")["sourceRoot"]).resolve() / source["member"].removeprefix("commonMain/")
        actual = record(path)
        if actual["size"] != source["size"] or actual["sha256"] != source["sha256"]:
            raise RuntimeError("Reorderable original compile source bytes differ: " + source["member"])
        expected_sources[path.resolve()] = (source["size"], source["sha256"])
    if {Path(source["path"]).resolve(): (source["size"], source["sha256"]) for source in row["sources"]} != expected_sources:
        raise RuntimeError("Reorderable recorded compiler sources differ from the complete official source set")
    compiler = {"metadata": ":compileCommonMainKotlinMetadata", "native-x64": ":compileKotlinOhosX64",
                "native-arm64": ":compileKotlinOhosArm64"}[evidence]
    expected_tasks = {compiler, ":allMetadataJar"} if evidence == "metadata" else {compiler}
    if {item["task"] for item in row["producers"]} != expected_tasks or row["explicitApi"] not in (None, "Disabled"):
        raise RuntimeError("Standard KGP producer or upstream explicit API mode differs")
    if row["sourceDependencies"] != {"implementation": ["org.jetbrains.compose.runtime:runtime",
            "org.jetbrains.compose.animation:animation", "org.jetbrains.compose.foundation:foundation"], "api": []}:
        raise RuntimeError("Upstream implementation dependency model differs")
    plugins = row["compilerPlugins"]
    plugin_tools = load(HERE / "compiler-plugin-toolchain.json")
    plugin_ids = ("org.jetbrains.kotlin:kotlin-compose-compiler-plugin-embeddable",)
    expected_plugins = {(plugin_tools["artifacts"][key]["size"], plugin_tools["artifacts"][key]["sha256"])
                        for key in plugin_ids}
    if (any(plugin_tools["pins"][key] != "2.4.20-0.1.0-08" for key in plugin_ids) or
            len(expected_plugins) != 1 or len(plugins) != 1 or
            {(item["size"], item["sha256"]) for item in plugins} != expected_plugins or
            any(record(item["path"]) != item for item in plugins)):
        raise RuntimeError("Reorderable compiler plugin set or bytes differ")
    native_targets, has_metadata, has_ir = [], False, False
    for producer in row["producers"]:
        if not producer["outputs"] or not any(item["size"] > 0 for item in producer["outputs"]):
            raise RuntimeError("Reorderable producer outputs are empty")
        for item in producer["outputs"]:
            if record(item["path"]) != item:
                raise RuntimeError("Reorderable stage output bytes changed")
            path = physical(item["path"])
            props = None
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    has_metadata |= any(("/linkdata/" in name or name.endswith(".kotlin_metadata")) and archive.getinfo(name).file_size > 0 for name in names)
                    has_ir |= any("/ir/" in name and archive.getinfo(name).file_size > 0 for name in names)
                    if "default/manifest" in names:
                        props = archive.read("default/manifest").decode()
            elif path.as_posix().endswith("/default/manifest"):
                props = path.read_text(encoding="utf-8")
            if "/linkdata/" in path.as_posix() and item["size"] > 0:
                has_metadata = True
            if "/ir/" in path.as_posix() and item["size"] > 0:
                has_ir = True
            if props is not None:
                properties = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
                native_targets.extend(properties.get("native_targets", "").split())
    if not has_metadata:
        raise RuntimeError("Reorderable metadata payload is absent")
    if evidence != "metadata":
        expected = "ohos_x64" if evidence == "native-x64" else "ohos_arm64"
        if not native_targets or set(native_targets) != {expected} or not has_ir:
            raise RuntimeError("Reorderable Native target or IR payload differs: " + evidence)
    return row


def api_symbols(model):
    return model["publicApi"]["metadataSymbols"]


def native_klib(outputs):
    manifests = [item for item in outputs if item["path"].replace("\\", "/").endswith("/default/manifest")]
    packed = [item for item in outputs if item["path"].endswith(".klib")]
    if len(manifests) == 1:
        return Path(manifests[0]["path"]).parent.parent
    elif len(packed) == 1:
        return Path(packed[0]["path"])
    raise RuntimeError("Native Klib root is not uniquely identified")


def signature_stage(value, evidence, attempt, native_home):
    """同一完整 Native 产物输出 metadata 与 IR 签名；不推断消费调用或运行结果。"""
    row = verify_stage(value, evidence)
    work = Path(value["work"])
    config = load(HERE / "port-config.json")
    outputs = [item for producer in row["producers"] for item in producer["outputs"]]
    klib = native_klib(outputs)
    launcher = Path(native_home).resolve() / "bin/klib"
    env = safe_environment(work)
    (work / "invocations").mkdir(parents=True, exist_ok=True)
    dumps = {}
    for channel, command, infix in (("metadata", "dump-metadata-signatures", "-signatures-"),
                                    ("ir", "dump-ir-signatures", "-ir-signatures-")):
        argv = [str(launcher), command, str(klib)]
        receipt = physical(work / "invocations" / (evidence + infix + str(attempt) + ".json"))
        if receipt.exists():
            raise RuntimeError("Existing signature invocation; select a new Attempt")
        invocation = {"fingerprint": value["fingerprint"], "sourceSetSha256": row["sourceSetSha256"],
                      "argv": argv, "cwd": str(ROOT), "launcher": record(launcher),
                      "inputs": outputs, "started": time.time(), "exitCode": None}
        receipt.write_bytes((json.dumps(invocation, indent=2) + "\n").encode())
        with receipt.with_suffix(".stdout.log").open("wb") as out, receipt.with_suffix(".stderr.log").open("wb") as err:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=out, stderr=err)
        output = record(receipt.with_suffix(".stdout.log"))
        invocation.update(exitCode=result.returncode, finished=time.time(), output=output)
        receipt.write_bytes((json.dumps(invocation, indent=2) + "\n").encode())
        if result.returncode:
            raise RuntimeError("Native signature dump failed; see " + str(receipt))
        dumps[channel] = {"invocation": record(receipt), "output": output}
    write(work / "evidence" / (evidence + "-api.json"), {
        "fingerprint": value["fingerprint"], "stage": evidence, "sourceSetSha256": row["sourceSetSha256"],
        "inputs": outputs, **dumps["metadata"], "irInvocation": dumps["ir"]["invocation"], "irOutput": dumps["ir"]["output"],
        "symbols": api_symbols(load(HERE / "source-inputs.json")), "runtime": "NOT_RUN"})
    return verify_api(value, evidence, native_home)


def verify_signature_texts(model, metadata_text, ir_text):
    # 普通声明和 data 生成项逐 owner 核 metadata；仅本库公开 ScrollMoveMode enum 的生成项另核 Declared IR。
    symbols = model["publicApi"]["metadataSymbols"]
    missing = [name for name in symbols if not re.search(re.escape(name) + r"\|", metadata_text)]
    if not metadata_text.strip() or missing:
        raise RuntimeError("Owned public API absent from Native metadata signatures: " + ", ".join(missing))
    declared = re.search(r"(?ms)^// Declared signatures: \d+\r?\n(.*?)^// Imported signatures: \d+\r?$", ir_text)
    expected = {signature for enum in model["publicApi"]["enumLanguageGeneratedMembers"] for member in enum["members"]
                for signature in member["declaredIrSignatures"]}
    missing_ir = expected - set(declared.group(1).splitlines()) if declared else expected
    if not declared or missing_ir:
        raise RuntimeError("Owned enum generated API absent from Declared IR signatures: " + ", ".join(sorted(missing_ir)))


def verify_api(value, evidence, native_home):
    row = verify_stage(value, evidence)
    api = load(Path(value["work"]) / "evidence" / (evidence + "-api.json"))
    outputs = [item for producer in row["producers"] for item in producer["outputs"]]
    symbols = api_symbols(load(HERE / "source-inputs.json"))
    if (api["fingerprint"] != value["fingerprint"] or api["inputs"] != outputs or api["symbols"] != symbols or
            api["sourceSetSha256"] != row["sourceSetSha256"]):
        raise RuntimeError("Native API signatures do not belong to the exact complete compiler output")
    config = load(HERE / "port-config.json")
    launcher = Path(native_home).resolve() / "bin/klib"
    for invocation_key, output_key, command in (("invocation", "output", "dump-metadata-signatures"),
                                               ("irInvocation", "irOutput", "dump-ir-signatures")):
        receipt, output = api[invocation_key], api[output_key]
        if record(receipt["path"]) != receipt or record(output["path"]) != output:
            raise RuntimeError("Native signature receipt or output bytes differ")
        invocation = load(receipt["path"])
        if (invocation["exitCode"] != 0 or invocation["inputs"] != outputs or invocation["fingerprint"] != value["fingerprint"] or
                invocation["sourceSetSha256"] != row["sourceSetSha256"] or invocation["output"] != output or
                invocation["argv"] != [str(launcher), command, str(native_klib(outputs))] or
                invocation["launcher"] != record(launcher) or
                Path(output["path"]).resolve() != Path(receipt["path"]).with_suffix(".stdout.log").resolve()):
            raise RuntimeError("Native signature command did not succeed for the same complete compiler output")
    verify_signature_texts(load(HERE / "source-inputs.json"), physical(api["output"]["path"]).read_text(encoding="utf-8-sig"),
                           physical(api["irOutput"]["path"]).read_text(encoding="utf-8-sig"))
    return api


def verify_publication(value, native_home):
    config = load(HERE / "port-config.json")
    model = load(HERE / "source-inputs.json")
    pins = load(HERE / "dependency-pins.json")
    stages = [verify_stage(value, evidence) for _, evidence, _ in COMPILES]
    group, version = config["modules"]["reorderable"]["group"], value["version"]
    repo = physical(value["repository"]) / group.replace(".", "/")
    root_file = repo / "reorderable" / version / ("reorderable-" + version + ".module")
    root, rows, scopes = load(root_file), [], []
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    expected_roots = {"org.jetbrains.kotlin:kotlin-stdlib", "org.jetbrains.compose.runtime:runtime",
                      "org.jetbrains.compose.animation:animation", "org.jetbrains.compose.foundation:foundation"}
    for suffix, target in (("", None), ("-ohosx64", "ohos_x64"), ("-ohosarm64", "ohos_arm64")):
        name = "reorderable" + suffix
        directory = repo / name / version
        gmm_file = directory / (name + "-" + version + ".module")
        gmm = load(gmm_file)
        if any(gmm["component"].get(k) != v for k, v in {"group": group, "module": "reorderable", "version": version}.items()):
            raise RuntimeError("Reorderable publication owner differs")
        if target:
            if (directory / gmm["component"]["url"]).resolve() != root_file.resolve():
                raise RuntimeError("Reorderable Native leaf owner URL differs")
            links = [variant["available-at"] for variant in root["variants"] if
                     variant.get("attributes", {}).get("org.jetbrains.kotlin.native.target") == target and "available-at" in variant]
            if not links or any(link["group"] != group or link["module"] != name or link["version"] != version or
                                (root_file.parent / link["url"]).resolve() != gmm_file.resolve() for link in links):
                raise RuntimeError("Reorderable root Native available-at differs")
        api = []
        for variant in gmm["variants"]:
            attrs = variant.get("attributes", {})
            if ((not target and attrs.get("org.gradle.usage") == "kotlin-metadata" and attrs.get("org.jetbrains.kotlin.platform.type") == "common") or
                    (target and attrs.get("org.gradle.usage") == "kotlin-api" and attrs.get("org.jetbrains.kotlin.native.target") == target)):
                api.append(variant)
            for dep in variant.get("dependencies", []):
                if pins.get(dep["group"] + ":" + dep["module"]) != dep.get("version", {}).get("requires"):
                    raise RuntimeError("Reorderable GMM dependency escaped frozen Native/root pins")
            for artifact in variant.get("files", []):
                path = (directory / artifact["url"]).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise RuntimeError("Reorderable artifact URL escaped its publication")
                item = record(path)
                if item["sha256"] != artifact["sha256"] or item["size"] != artifact["size"] or item["size"] == 0:
                    raise RuntimeError("Reorderable published artifact bytes differ")
        if not api or not all(variant.get("files") for variant in api):
            raise RuntimeError("Reorderable common metadata or Native API artifact is absent")
        if any({dep["group"] + ":" + dep["module"] for dep in variant.get("dependencies", [])} != expected_roots for variant in api):
            raise RuntimeError("Reorderable GMM API dependency set differs from the upstream model")
        pom = ET.fromstring((directory / (name + "-" + version + ".pom")).read_bytes())
        if any(pom.findtext("m:" + key, namespaces=ns) != expected for key, expected in
               (("groupId", group), ("artifactId", name), ("version", version))):
            raise RuntimeError("Reorderable POM coordinates differ")
        dependencies = pom.findall("m:dependencies/m:dependency", ns)
        expected_pom = {ga + (suffix if target and not ga.startswith("org.jetbrains.kotlin:") else "") for ga in expected_roots}
        actual_pom = set()
        for dep in dependencies:
            ga = dep.findtext("m:groupId", namespaces=ns) + ":" + dep.findtext("m:artifactId", namespaces=ns)
            scope = dep.findtext("m:scope", namespaces=ns)
            actual_pom.add(ga)
            if pins.get(ga) != dep.findtext("m:version", namespaces=ns) or scope != ("compile" if target else "runtime"):
                raise RuntimeError("Reorderable POM dependency version or publication-specific scope differs")
        if actual_pom != expected_pom:
            raise RuntimeError("Reorderable POM dependency closure differs")
        scopes.append({"publication": name, "pomScope": "compile" if target else "runtime",
                       "gmmUsage": "kotlin-api" if target else "kotlin-metadata", "dependencies": sorted(actual_pom)})
        if record(directory / (name + "-" + version + "-license.txt"))["sha256"] != model["license"]["sha256"]:
            raise RuntimeError("Reorderable publication license differs")
        # 标准 sources artifact 必须包含全部九份原件，不能只附一份未被编译的上游归档。
        with zipfile.ZipFile(directory / (name + "-" + version + "-sources.jar")) as archive:
            actual_sources = [{"member": member.filename, "size": member.file_size,
                               "sha256": hashlib.sha256(archive.read(member)).hexdigest()}
                              for member in archive.infolist() if member.filename.endswith(".kt")]
            if sorted(actual_sources, key=lambda item: item["member"]) != model["sourceMembers"]:
                raise RuntimeError("Published sources artifact is not the complete original library")
            license_member = "META-INF/licenses/reorderable/LICENSE"
            if hashlib.sha256(archive.read(license_member)).hexdigest() != model["license"]["sha256"]:
                raise RuntimeError("Published sources license differs")
        if target:
            stage = next(row for row in stages if row["stage"] == ("native-x64" if target == "ohos_x64" else "native-arm64"))
            with zipfile.ZipFile(directory / (name + "-" + version + ".klib")) as archive:
                for producer in stage["producers"]:
                    for item in producer["outputs"]:
                        path = Path(item["path"])
                        normalized = path.as_posix()
                        if "/default/" in normalized:
                            member = "default/" + normalized.split("/default/", 1)[1]
                            if hashlib.sha256(archive.read(member)).hexdigest() != item["sha256"]:
                                raise RuntimeError("Published Klib member differs from the real Native compiler output")
                        elif path.suffix == ".klib" and record(path)["sha256"] != record(directory / (name + "-" + version + ".klib"))["sha256"]:
                            raise RuntimeError("Published Klib differs from the real Native compiler output")
        else:
            metadata = next(row for row in stages if row["stage"] == "metadata")
            jar = next(item for producer in metadata["producers"] if producer["task"] == ":allMetadataJar" for item in producer["outputs"] if item["path"].endswith(".jar"))
            if record(directory / (name + "-" + version + ".jar"))["sha256"] != jar["sha256"]:
                raise RuntimeError("Published common metadata differs from the real standard KGP artifact")
        if not suffix:
            for key, classifier in (("sources", "upstream-sources.jar"), ("pom", "upstream-pom.xml"), ("gmm", "upstream-module.json"),
                                    ("upstreamBuild", "upstream-build.gradle.kts")):
                if record(directory / (name + "-" + version + "-" + classifier))["sha256"] != model[key]["sha256"]:
                    raise RuntimeError("Reorderable publication official original differs: " + key)
        if (directory / (name + "-" + version + "-provenance.json")).read_bytes() != (Path(value["work"]) / "provenance.json").read_bytes():
            raise RuntimeError("Published provenance differs")
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix in (".md5", ".sha1", ".sha256", ".sha512"):
                continue
            for algorithm in ("md5", "sha1", "sha256", "sha512"):
                checksum = path.with_name(path.name + "." + algorithm)
                if not checksum.is_file() or checksum.read_text().strip().lower() != hashlib.new(algorithm, path.read_bytes()).hexdigest():
                    raise RuntimeError("Publication checksum differs: " + str(checksum))
            rows.append(record(path))
    api_receipts = [verify_api(value, evidence, native_home) for evidence in ("native-x64", "native-arm64")]
    result = {"status": "VERIFIED_STAGING_NOT_PUBLISHED", **value, "files": rows,
              "compilations": [{key: row[key] for key in ("stage", "sourceCount", "sourceSetSha256", "sourceManifest")} for row in stages],
              "dependencyScopes": scopes, "publicApi": model["publicApi"], "nativeSignatures": api_receipts,
              "runtime": "NOT_RUN", "armRuntime": "NOT_RUN"}
    write(Path(value["work"]) / "publication.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("Prepare", *TASKS, "Verify"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--tooling", type=Path)
    parser.add_argument("--native-home", type=Path)
    args = parser.parse_args()
    outputs = output_roots(args)
    work = outputs[0]
    prepared = work / "prepared.json"
    fresh = args.stage == "Prepare" and not prepared.exists()
    if fresh:
        for path in (work / "source-manifest.json", work / "provenance.json", prepared):
            if path.exists() or path.is_symlink():
                raise RuntimeError("Prepare file already exists: " + str(path))
    work.mkdir(parents=True, exist_ok=True)
    tools = checked_tools(work, args.tooling)
    value = identity(args, tools, outputs)
    model = load(HERE / "source-inputs.json")
    provenance = {"fingerprint": value["fingerprint"], "sourceCommit": value["sourceCommit"],
                  "upstream": model["upstream"], "group": GROUP, "module": MODULE, "version": value["version"],
                  "toolingCommit": TOOL_REVISION, "sourceMembers": model["sourceMembers"], "publicApi": model["publicApi"],
                  "upstreamFiles": {key: model[key] for key in ("sources", "pom", "gmm", "upstreamBuild", "license")}}
    if args.stage == "Prepare":
        if not fresh and load(prepared) != value:
            raise RuntimeError("Existing work identity differs")
        write(work / "source-manifest.json", {"fingerprint": value["fingerprint"], "members": value["sources"],
              "sourceCount": 9, "sourceSetSha256": model["sourceSetSha256"], "publicApi": model["publicApi"]}, exclusive=fresh)
        if fresh:
            write(work / "provenance.json", provenance, exclusive=True)
            write(prepared, value, exclusive=True)
        else:
            write(prepared, value)
            write(work / "provenance.json", provenance)
        print(json.dumps({"work": str(work), "toolingHome": str(tools), "fingerprint": value["fingerprint"], "version": value["version"]}))
        return
    if not prepared.is_file() or load(prepared) != value or load(work / "provenance.json") != provenance:
        raise RuntimeError("Work identity or provenance differs")
    check_native(args.native_home)
    if args.stage == "Verify":
        print(json.dumps(verify_publication(value, args.native_home)))
        return
    if args.stage != "Tasks":
        discovery = load(work / "task-discovery.json")
        if discovery["fingerprint"] != value["fingerprint"] or record(discovery["stdout"]["path"]) != discovery["stdout"]:
            raise RuntimeError("Task discovery differs")
    if args.stage not in ("Tasks", "Resolve"):
        if load(work / "evidence/resolve.json")["fingerprint"] != value["fingerprint"]:
            raise RuntimeError("Resolve belongs to another recipe")
        for label, stage, target in COMPILES:
            if label == args.stage:
                break
            verify_stage(value, stage)
    if args.stage == "Publish":
        for stage in ("native-x64", "native-arm64"):
            verify_api(value, stage, args.native_home)
        root = Path(value["repository"]) / GROUP.replace(".", "/")
        for module in (MODULE, MODULE + "-ohosx64", MODULE + "-ohosarm64"):
            if (root / module / value["version"]).exists():
                raise RuntimeError("Publication version already exists: " + module)
    argv = ["sh", str(HERE / "gradlew"), "-p", str(HERE), "--project-cache-dir", str(work / "project-cache"),
            "-PportWork=" + str(work), "-PportTooling=" + str(tools), "-PportFingerprint=" + value["fingerprint"], "-PportVersion=" + value["version"],
            "-PportRepository=" + value["repository"], "-Pkotlin.project.persistent.dir=" + str(work / "kotlin-cache"),
            "-Pkotlin.native.home=" + str(args.native_home.resolve()), "--console=plain", "--stacktrace", *TASKS[args.stage]]
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout, stderr = logs / (args.stage + ".stdout.log"), logs / (args.stage + ".stderr.log")
    with stdout.open("wb") as out, stderr.open("wb") as err:
        run = subprocess.run(argv, env=safe_environment(work), stdout=out, stderr=err)
    if run.returncode:
        print(stderr.read_text(encoding="utf-8", errors="replace")[-16384:], file=sys.stderr)
        raise RuntimeError("Gradle " + args.stage + " failed with exit " + str(run.returncode))
    if args.stage == "Tasks":
        names = {name.lstrip(":") for name in re.findall(r"^\s*([\w:-]+)(?:\s+-|\s*$)", stdout.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)}
        if not REQUIRED.issubset(names):
            raise RuntimeError("Required tasks absent from actual discovery")
        write(work / "task-discovery.json", {"fingerprint": value["fingerprint"], "required": sorted(REQUIRED), "stdout": record(stdout)})
    for label, stage, target in COMPILES:
        if label == args.stage:
            verify_stage(value, stage)
            if target is not None:
                signature_stage(value, stage, args.run_attempt, args.native_home)
    print(json.dumps({"stage": args.stage, "exitCode": run.returncode, "fingerprint": value["fingerprint"], "stdout": record(stdout)}))


if __name__ == "__main__":
    main()
