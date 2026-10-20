import ast
import sys

from lab import common as c

WANT = {
    "common.py": ["VARIANT_ROLE", "VARIANT_TOKENS", "is_variant", "parse_skills", "salary_net"],
    "mapreduce.py": ["record_boundary", "map_task", "reduce_task", "Master.recover"],
    "duck.py": ["VARIANT_SQL", "SKILLS_SQL", "COUNT_SQL"],
    "salary.py": ["pick_base"],
}


def find(tree, name):
    parts = name.split(".")
    nodes = tree.body
    found = None
    for part in parts:
        found = None
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == part:
                found = node
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == part for t in node.targets):
                found = node
        if found is None:
            return None
        nodes = getattr(found, "body", [])
    return found


def main():
    lab = c.ROOT / "lab"
    for fname, names in WANT.items():
        src = (lab / fname).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for name in names:
            node = find(tree, name)
            if node is None:
                print(f"не нашёл {name} в {fname}")
                continue
            seg = ast.get_source_segment(src, node, padded=True)
            out = f"code_{fname[:-3]}_{name.replace('.', '_')}.txt"
            c.write_out(out, seg.rstrip() + "\n")
            print(f"фрагмент {fname}:{name} -> report/out/{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
