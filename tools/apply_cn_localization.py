# -*- coding: utf-8 -*-
"""
SPZ CN localization script - v2
Fixes: unclosed quotes, YAML validity check, detailed report, idempotency, proper verify.
Only modifies m_text fields in .prefab/.unity YAML; never does whole-file string replacement.
"""
import argparse, json, os, re, sys, copy

# --- YAML value parsing ---

def parse_yaml_value(raw):
    v = raw.strip()
    if v == '':
        return ('', 'plain')
    if v.startswith('|') or v.startswith('>'):
        return (None, None)
    if v.startswith("'"):
        if not v.endswith("'") or len(v) < 2:
            return (None, None)
        inner = v[1:-1]
        unescaped = inner.replace("''", "'")
        return (unescaped, 'single')
    if v.startswith('"'):
        if not v.endswith('"') or len(v) < 2:
            return (None, None)
        inner = v[1:-1]
        unescaped = inner.replace('\\\\', '\\').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
        return (unescaped, 'double')
    return (v, 'plain')


def encode_yaml_single(value):
    return "'" + value.replace("'", "''") + "'"


def encode_yaml_value(value, original_style):
    needs_quoting = any(c in value for c in [':', '#', '\n', '\r', '\t', '"', "'", '{', '}', '[', ']', ',', '&', '*', '?', '|', '>', '@', '`', '%'])
    if original_style == 'double':
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r')
        return '"' + escaped + '"'
    elif original_style == 'single' or needs_quoting:
        return encode_yaml_single(value)
    else:
        return value


# --- Line-level operations ---

TEXT_FIELD_RE = re.compile(r'^(\s*m_text:\s*)(.*)$')


def extract_text_fields(lines):
    results = []
    for i, line in enumerate(lines):
        m = TEXT_FIELD_RE.match(line.rstrip('\n'))
        if not m:
            continue
        prefix = m.group(1)
        raw = m.group(2)
        parsed, style = parse_yaml_value(raw)
        results.append((i, prefix, raw, parsed, style))
    return results


def apply_to_file(filepath, translations, dry_run=False):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return {'replacements': 0, 'skipped': 0, 'errors': [f'read error: {e}'], 'details': []}

    result = {'replacements': 0, 'skipped': 0, 'errors': [], 'details': []}
    modified = False

    for entry in extract_text_fields(lines):
        idx, prefix, raw, parsed, style = entry

        if parsed is None:
            msg = f"  L{idx+1}: SKIP (cannot parse YAML value: {raw[:60]})"
            result['errors'].append(msg)
            result['skipped'] += 1
            continue

        if parsed not in translations:
            continue

        cn_text = translations[parsed]

        if parsed == cn_text:
            continue

        new_value = encode_yaml_value(cn_text, style)
        old_value = raw.strip()

        if new_value == old_value:
            continue

        new_line = prefix + new_value + "\n"
        detail = f"  L{idx+1}: '{parsed[:40]}' -> '{cn_text[:40]}'"
        result['details'].append(detail)
        result['replacements'] += 1
        lines[idx] = new_line
        modified = True

    if modified and not dry_run:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        except Exception as e:
            result['errors'].append(f'write error: {e}')
            result['replacements'] = 0

    return result


def verify_file(filepath, translations):
    result = {'cn_found': 0, 'en_remaining': 0, 'yaml_errors': 0, 'details': []}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        result['details'].append(f'read error: {e}')
        return result

    for entry in extract_text_fields(lines):
        idx, prefix, raw, parsed, style = entry

        if parsed is None:
            result['yaml_errors'] += 1
            result['details'].append(f"  L{idx+1}: YAML PARSE ERROR: {raw[:80]}")
            continue

        if parsed in translations:
            result['en_remaining'] += 1
            result['details'].append(f"  L{idx+1}: UNTRANSLATED: '{parsed[:50]}'")
        else:
            for en, cn in translations.items():
                if parsed == cn:
                    result['cn_found'] += 1
                    break

    return result


# --- YAML validity check ---

def check_yaml_valid(filepath):
    try:
        import yaml
        with open(filepath, 'r', encoding='utf-8') as f:
            yaml.safe_load(f)
        return (True, None)
    except ImportError:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    stripped = line.rstrip('\n')
                    m = TEXT_FIELD_RE.match(stripped)
                    if m:
                        raw = m.group(2).strip()
                        if raw.startswith("'"):
                            if not raw.endswith("'") or len(raw) < 2:
                                return (False, f"L{line_num}: unclosed single-quote in m_text")
            return (True, None)
        except Exception as e:
            return (False, str(e))
    except Exception as e:
        return (False, str(e))


# --- File discovery ---

def find_files(repo):
    assets_dir = os.path.join(repo, 'Assets')
    if not os.path.isdir(assets_dir):
        sys.exit("ERROR: Assets/ not found")
    out = []
    for root, dirs, files in os.walk(assets_dir):
        if '_backup' in root:
            continue
        for fn in files:
            if fn.endswith('.prefab') or fn.endswith('.unity'):
                out.append(os.path.join(root, fn))
    return out


def load_translations(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'translations' not in data:
        sys.stderr.write("ERROR: no 'translations' key in JSON\n")
        sys.exit(1)
    return data['translations']


# --- Main modes ---

def do_apply(translations, repo, dry_run=False):
    files = find_files(repo)
    stats = {
        'files_scanned': len(files),
        'files_modified': 0,
        'total_replacements': 0,
        'total_skipped': 0,
        'total_errors': 0,
        'file_details': [],
    }

    for fp in sorted(files):
        r = apply_to_file(fp, translations, dry_run)
        if r['replacements'] > 0:
            stats['files_modified'] += 1
            stats['total_replacements'] += r['replacements']
            tag = 'DRY' if dry_run else 'OK'
            detail = f"[{tag}] {os.path.relpath(fp, repo)}: {r['replacements']} replacements"
            stats['file_details'].append(detail)
            for d in r['details']:
                stats['file_details'].append(d)
        stats['total_skipped'] += r['skipped']
        stats['total_errors'] += len(r['errors'])
        for e in r['errors']:
            stats['file_details'].append(f"  ERROR in {os.path.relpath(fp, repo)}: {e}")

    return stats


def do_verify(translations, repo):
    files = find_files(repo)
    stats = {
        'files_scanned': len(files),
        'cn_found': 0,
        'en_remaining': 0,
        'yaml_errors': 0,
        'failed_files': [],
        'details': [],
    }

    for fp in sorted(files):
        rel = os.path.relpath(fp, repo)

        valid, err = check_yaml_valid(fp)
        if not valid:
            stats['yaml_errors'] += 1
            stats['failed_files'].append(rel)
            stats['details'].append(f"YAML ERROR in {rel}: {err}")

        r = verify_file(fp, translations)
        stats['cn_found'] += r['cn_found']
        stats['en_remaining'] += r['en_remaining']
        stats['yaml_errors'] += r['yaml_errors']
        if r['en_remaining'] > 0 or r['yaml_errors'] > 0:
            stats['failed_files'].append(rel)
        for d in r['details']:
            stats['details'].append(f"{rel}: {d}")

    return stats


def do_idempotency(translations, repo, tmp_dir):
    import shutil
    assets_src = os.path.join(repo, 'Assets')
    tmp_assets = os.path.join(tmp_dir, 'Assets')
    if os.path.exists(tmp_assets):
        shutil.rmtree(tmp_assets)
    shutil.copytree(assets_src, tmp_assets, dirs_exist_ok=False)

    r1 = do_apply(translations, tmp_dir, dry_run=False)
    r2 = do_apply(translations, tmp_dir, dry_run=False)

    return {
        'first_run_replacements': r1['total_replacements'],
        'second_run_replacements': r2['total_replacements'],
        'idempotent': r2['total_replacements'] == 0,
    }


# --- CLI ---

def _write_report(path, mode, apply_stats, verify_stats):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"SPZ CN Localization Report - {mode}\n")
        f.write(f"{'='*60}\n\n")
        if apply_stats:
            f.write(f"Apply Results:\n")
            f.write(f"  Files scanned: {apply_stats['files_scanned']}\n")
            f.write(f"  Files modified: {apply_stats['files_modified']}\n")
            f.write(f"  Total replacements: {apply_stats['total_replacements']}\n")
            f.write(f"  Total errors: {apply_stats['total_errors']}\n\n")
            f.write("Details:\n")
            for d in apply_stats['file_details']:
                f.write(f"  {d}\n")
        if verify_stats:
            f.write(f"\nVerify Results:\n")
            f.write(f"  CN found: {verify_stats['cn_found']}\n")
            f.write(f"  EN remaining: {verify_stats['en_remaining']}\n")
            f.write(f"  YAML errors: {verify_stats['yaml_errors']}\n")
            if verify_stats['details']:
                f.write("Details:\n")
                for d in verify_stats['details']:
                    f.write(f"  {d}\n")


def main():
    ap = argparse.ArgumentParser(description='SPZ CN localization - apply, verify, idempotency check')
    ap.add_argument('--translations', required=True, help='Path to translations.json')
    ap.add_argument('--repo', required=True, help='Path to SPZ repository root')
    ap.add_argument('--mode', choices=['apply', 'verify', 'idempotency'], default='apply',
                    help='apply: replace EN to CN; verify: check all translated; idempotency: run twice, second=0')
    ap.add_argument('--dry-run', action='store_true', help='Show what would change without writing')
    ap.add_argument('--report', default=None, help='Write detailed report to this file')
    a = ap.parse_args()

    trans = load_translations(a.translations)
    print(f"=== CN Localization: {a.mode.upper()} ===")
    print(f"Loaded {len(trans)} translation pairs")

    if a.mode == 'apply':
        stats = do_apply(trans, a.repo, a.dry_run)
        print(f"Files scanned: {stats['files_scanned']}")
        print(f"Files modified: {stats['files_modified']}")
        print(f"Total replacements: {stats['total_replacements']}")
        print(f"Total skipped (parse errors): {stats['total_skipped']}")
        print(f"Total errors: {stats['total_errors']}")
        for d in stats['file_details']:
            print(d)
        if stats['total_errors'] > 0:
            print("\nWARNING: Errors occurred during apply!")
            sys.exit(1)
        print("\n=== Auto-verify after apply ===")
        vstats = do_verify(trans, a.repo)
        print(f"CN found: {vstats['cn_found']}")
        print(f"EN remaining: {vstats['en_remaining']}")
        print(f"YAML errors: {vstats['yaml_errors']}")
        if vstats['en_remaining'] > 0 or vstats['yaml_errors'] > 0:
            print("\nFAILED: Translation incomplete or YAML broken!")
            for d in vstats['details'][:20]:
                print(d)
            if a.report:
                with open(a.report, 'w', encoding='utf-8') as f:
                    f.write("VERIFY FAILURE REPORT\n\n")
                    for d in vstats['details']:
                        f.write(d + '\n')
            sys.exit(1)
        print("Apply + verify OK.")
        if a.report:
            _write_report(a.report, 'apply+verify', stats, vstats)
        sys.exit(0)

    elif a.mode == 'verify':
        stats = do_verify(trans, a.repo)
        print(f"Files scanned: {stats['files_scanned']}")
        print(f"CN translations found: {stats['cn_found']}")
        print(f"English remaining (untranslated): {stats['en_remaining']}")
        print(f"YAML errors: {stats['yaml_errors']}")
        if stats['en_remaining'] > 0:
            print(f"\nFAILED: {stats['en_remaining']} untranslated text fields found!")
        if stats['yaml_errors'] > 0:
            print(f"\nFAILED: {stats['yaml_errors']} YAML parse errors!")
        if stats['en_remaining'] > 0 or stats['yaml_errors'] > 0:
            for d in stats['details'][:30]:
                print(d)
            if a.report:
                with open(a.report, 'w', encoding='utf-8') as f:
                    f.write("VERIFY REPORT\n\n")
                    for d in stats['details']:
                        f.write(d + '\n')
            sys.exit(1)
        print("All verified OK.")
        if a.report:
            _write_report(a.report, 'verify', None, stats)
        sys.exit(0)

    elif a.mode == 'idempotency':
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            stats = do_idempotency(trans, a.repo, tmp)
            print(f"First run replacements: {stats['first_run_replacements']}")
            print(f"Second run replacements: {stats['second_run_replacements']}")
            if stats['idempotent']:
                print("Idempotency: PASS (second run produced 0 replacements)")
                sys.exit(0)
            else:
                print("Idempotency: FAIL (second run produced replacements!)")
                sys.exit(1)


if __name__ == '__main__':
    main()
