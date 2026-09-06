"""将 pytest JUnit XML 与中文案例说明合并，不预设通过数量。"""

import hashlib
import json
import xml.etree.ElementTree as ET


def test_results(xml_path, catalog_path):
    catalog = json.loads(catalog_path.read_text("utf-8"))
    variants = json.loads(catalog_path.with_name("variant_inputs.json").read_text("utf-8"))
    rows = []
    for number, case in enumerate(ET.parse(xml_path).getroot().iter("testcase"), 1):
        name = case.attrib["name"]
        base = name.split("[")[0]
        details = catalog.get(
            base,
            {"module": "入口", "title": base, "input": "详见测试源码", "expected": "测试断言通过"},
        )
        if "[" in name:
            details = {
                **details,
                "input": variants.get(name, details["input"] + " 参数 " + name.split("[", 1)[1]),
            }
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        problem = failure if failure is not None else error
        status = "失败" if problem is not None else "跳过" if skipped is not None else "通过"
        rows.append(
            {
                "id": f"UT-{number:03}",
                **details,
                "status": status,
                "seconds": float(case.attrib.get("time", 0)),
                "node": case.attrib.get("classname", "") + "::" + name,
                "actual": "测试断言全部通过"
                if status == "通过"
                else (problem.text or "")
                if problem is not None
                else "未执行",
            }
        )
    return rows


def source_manifest(project):
    files = [
        *project.glob("*.py"),
        *project.glob("*.cmd"),
        project / "pyproject.toml",
        project / "requirements-lock.txt",
    ]
    for directory in ["src", "tests", "scripts", "examples"]:
        files.extend(
            path
            for path in (project / directory).rglob("*")
            if path.suffix in {".py", ".json", ".css"}
        )
    return {
        str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }
