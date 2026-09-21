"""Hold the INI Master metadata up against the code that reads the ini.

mod/data/MasterLooter.inimeta is compiled into the plugin as the INIMETA
resource, and INI Master shows people what it says: the type of each key, its
default, its range and its help. None of that is read from the code, so every
new key, changed default or new clamp has to be copied across by hand, and a
copy that is wrong does not fail anywhere. This is the check that it was
copied.

The code is the authority. For every key in [MasterLooter]:

  - Serialize() in settings.cpp writes it, so it must be in the metadata,
    and every key in the metadata must be one ApplyGeneral() reads.
  - The type follows the reader: Flag is bool, Key is key, Clamp is int,
    Range is float, strtoul is int, a plain string is string or enum.
  - The default is the member's initialiser in settings.h. ConfigVersion is
    the one exception: a fresh file is stamped with the value Migrate() sets
    when there is no file, which is the number that matters to a reader.
  - min and max are the bounds ApplyGeneral() clamps to, since those are what
    the plugin accepts. The menu sliders are narrower in places; the ini is
    allowed to say more than the menu does.

With --wording it also lists, without failing, every label and help text
that is not in menu.cpp word for word. Most of the text started as a menu
tooltip and was edited for a reader outside the game (there is no General
tab in INI Master), so this list is long by design. Read it when menu
tooltips have been reworded, to see which ones the metadata should follow.

Exits non-zero on any mismatch, so it can gate a build.

    py -3 scripts/check_inimeta.py
    py -3 scripts/check_inimeta.py --wording
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
META = os.path.join(ROOT, "mod", "data", "MasterLooter.inimeta")
SETTINGS_CPP = os.path.join(ROOT, "mod", "src", "core", "settings.cpp")
SETTINGS_H = os.path.join(ROOT, "mod", "src", "core", "settings.h")
MENU_CPP = os.path.join(ROOT, "mod", "src", "gui", "menu.cpp")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def body(src, head):
    """The brace-balanced body of the first function whose signature starts with head."""
    i = src.index(head)
    i = src.index("{", i)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise ValueError(head)


def parse_reader(cpp):
    """key -> (member, kind, lo, hi) from ApplyGeneral."""
    out = {}
    src = body(cpp, "static void ApplyGeneral(")
    for m in re.finditer(r'k == "(\w+)"\)\s*(.*)', src):
        key, rest = m.group(1), m.group(2)
        mm = re.search(r"c\.(\w+)\s*=\s*(.*?);", rest)
        if not mm:
            continue                     # a retired key that sets no member
        if "pre-" in rest and "key" in rest:
            continue                     # a legacy alias, e.g. CatchCreatures
        member, expr = mm.group(1), mm.group(2)
        lo = hi = None
        if expr.startswith("Flag("):
            kind = "bool"
        elif expr.startswith("Key("):
            kind = "key"
        elif expr.startswith("Clamp("):
            kind = "int"
            a = re.match(r"Clamp\(v,\s*(-?\d+),\s*(-?\d+)\)", expr)
            lo, hi = int(a.group(1)), int(a.group(2))
        elif expr.startswith("Range("):
            kind = "float"
            a = re.match(r"Range\(v,\s*([\d.]+)f?,\s*([\d.]+)f?", expr)
            lo, hi = float(a.group(1)), float(a.group(2))
        elif "strtoul" in expr:
            kind = "int"
        elif "std::max(0" in expr:
            kind = "int"
            lo = 0
        elif "atoi" in expr:
            kind = "int"
        elif expr == "v":
            kind = "string"
        else:
            raise ValueError("unrecognised reader for %s: %s" % (key, expr))
        out[key] = (member, kind, lo, hi)
    return out


def parse_written(cpp):
    src = body(cpp, "static std::string Serialize(const Config& c)\n")
    src = src.split("[Classes]")[0]
    return set(re.findall(r"(?:\"|\\n)(\w+)=%", src))


def parse_defaults(h):
    """member -> default as the ini would write it."""
    out = {}
    for m in re.finditer(r"^\s*(bool|int|unsigned|float|std::string)\s+(\w+)\s*(?:=\s*([^;]+))?;", h, re.M):
        typ, name, val = m.group(1), m.group(2), (m.group(3) or "").strip()
        if typ == "bool":
            out[name] = "1" if val == "true" else "0"
        elif typ in ("int", "unsigned"):
            out[name] = str(int(val, 0)) if val else "0"
        elif typ == "float":
            out[name] = float(val.rstrip("f")) if val else 0.0
        else:
            out[name] = val.strip('"') if val else ""
    return out


def fresh_version(cpp):
    m = re.search(r"if \(!fromFile\) c\.configVersion = (\d+);", cpp)
    return m.group(1) if m else None


def menu_text(src):
    """menu.cpp with adjacent string literals joined and escapes undone, so a
    tooltip written across six lines of source reads as the one string it is."""
    src = re.sub(r'"\s+"', "", src)
    return src.replace('\\"', '"').replace("\\n", "\n")


def load_meta():
    text = read(META)
    text = re.sub(r"^\s*//.*\n", "", text, flags=re.M)
    return json.loads(text)


def main():
    cpp, h, menu = read(SETTINGS_CPP), read(SETTINGS_H), menu_text(read(MENU_CPP))
    reader = parse_reader(cpp)
    written = parse_written(cpp)
    defaults = parse_defaults(h)
    meta = load_meta()
    keys = meta["sections"]["MasterLooter"]["keys"]
    errors, notes = [], []

    if defaults.get("configVersion") != fresh_version(cpp):
        errors.append("ConfigVersion: settings.h starts a Config at %s and Migrate() stamps a fresh file %s"
                      % (defaults.get("configVersion"), fresh_version(cpp)))
    for k in sorted(written - set(keys)):
        errors.append("%s: the plugin writes it and the metadata does not describe it" % k)
    for k in sorted(set(keys) - set(reader)):
        errors.append("%s: in the metadata but ApplyGeneral never reads it" % k)

    for k, spec in keys.items():
        if k not in reader:
            continue
        member, kind, lo, hi = reader[k]
        t = spec.get("type")
        want_types = {"string": ("string", "enum")}.get(kind, (kind,))
        if t not in want_types:
            errors.append("%s: type %s, but the plugin reads it as %s" % (k, t, kind))

        if k == "ConfigVersion":
            want = fresh_version(cpp)
        else:
            want = defaults.get(member)
        got = spec.get("default")
        if want is None:
            errors.append("%s: no default found for c.%s in settings.h" % (k, member))
        elif kind == "float":
            if got is None or abs(float(got) - float(want)) > 1e-6:
                errors.append("%s: default %s, settings.h says %g" % (k, got, want))
        elif str(got) != str(want):
            errors.append("%s: default %s, settings.h says %s" % (k, got, want))

        if lo is not None and spec.get("min") != lo and not (
                isinstance(spec.get("min"), (int, float)) and float(spec["min"]) == float(lo)):
            errors.append("%s: min %s, the plugin clamps to %s" % (k, spec.get("min"), lo))
        if hi is not None and spec.get("max") != hi and not (
                isinstance(spec.get("max"), (int, float)) and float(spec["max"]) == float(hi)):
            errors.append("%s: max %s, the plugin clamps to %s" % (k, spec.get("max"), hi))

        for field in ("label", "help"):
            s = spec.get(field)
            if s and s not in menu:
                notes.append("%s: %s is not in menu.cpp word for word" % (k, field))

    for line in errors:
        print("error  " + line)
    if "--wording" in sys.argv[1:]:
        for line in notes:
            print("note   " + line)
    print("%d keys in the metadata, %d written by the plugin, %d errors, %d wording notes"
          % (len(keys), len(written), len(errors), len(notes)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
