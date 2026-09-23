# -*- coding: utf-8 -*-
# SPZ CN localization script - rewritten to fix verify logic
import argparse, json, os, re, sys

def load_translations(p):
    with open(p, 'r', encoding='utf-8') as f:
        d = json.load(f)
    if 'translations' not in d:
        sys.stderr.write("ERROR: no translations key\n")
        sys.exit(1)
    return d['translations']

def find_files(repo):
    ad = os.path.join(repo, 'Assets')
    if not os.path.isdir(ad):
        sys.exit("ERROR: Assets/ not found")
    out = []
    for root, dirs, files in os.walk(ad):
        if '_backup' in root: continue
        for fn in files:
            if fn.endswith('.prefab') or fn.endswith('.unity'):
                out.append(os.path.join(root, fn))
    return out

def extract_val(line):
    m = re.match(r'^\s*m_text:\s*(.*)$', line.rstrip('\n'))
    if not m: return None
    v = m.group(1).strip()
    if v.startswith("'") and len(v) > 1:
        v = v[1:].replace("''", "'")
        if v.endswith("'"): v = v[:-1]
    return v

def apply_file(fp, trans, dry=False):
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except: return (0, 0)
    reps = 0; new = []
    for line in lines:
        m = re.match(r'^(\s*m_text:\s*)(.*)$', line.rstrip('\n'))
        if m:
            prefix = m.group(1); tv = m.group(2).strip(); orig = tv
            if tv.startswith("'") and len(tv) > 1:
                u = tv[1:].replace("''", "'")
                if u.endswith("'"): u = u[:-1]
                tv = u
            if tv in trans:
                cn = trans[tv]
                esc = any(c in cn for c in ['\n','\r','\t','"'])
                if esc or orig.startswith("'"):
                    cn = "'" + cn.replace("'", "''")
                nl = prefix + cn + "\n"
                if nl != line:
                    new.append(nl); reps += 1; continue
        new.append(line)
    if reps > 0 and not dry:
        with open(fp, 'w', encoding='utf-8') as f:
            f.writelines(new)
    return (reps, len(lines))

def verify_file(fp, trans):
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except: return (0, 0)
    ftexts = []
    for line in lines:
        v = extract_val(line)
        if v is not None: ftexts.append(v)
    if not ftexts: return (0, 0)
    cn = 0; en = 0
    for t in ftexts:
        if t in trans:
            if trans[t] in ftexts: cn += 1
            else: en += 1
    return (cn, en)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--translations', required=True)
    ap.add_argument('--repo', required=True)
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    print("=== CN {} ===".format('Verify' if a.verify else 'Apply'))
    trans = load_translations(a.translations)
    print("Loaded {} pairs".format(len(trans)))
    files = find_files(a.repo)
    print("Found {} files".format(len(files)))
    if a.verify:
        tcn = 0; ten = 0; wf = []
        for fp in files:
            c, e = verify_file(fp, trans)
            tcn += c; ten += e
            if e > 0: wf.append((fp, e))
        print("CN found: {} | EN remaining: {}".format(tcn, ten))
        if ten > 0:
            print("WARNING: {} files need translation".format(len(wf)))
            for f, n in wf[:10]: print("  {}: {}".format(f, n))
            sys.exit(1)
        print("All verified.")
        sys.exit(0)
    else:
        tr = 0; fm = 0
        for fp in files:
            r, l = apply_file(fp, trans, a.dry_run)
            if r > 0:
                fm += 1; tr += r
                print("  [{}] {}: {}".format('DRY' if a.dry_run else 'OK', fp, r))
        print("Modified: {} files, {} replacements".format(fm, tr))
        sys.exit(0)

if __name__ == '__main__':
    main()
