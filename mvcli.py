#!/usr/bin/env python3
"""node_exporter textfile collector for Marvell RAID controllers via mvcli.

Written for the Dell BOSS-S1 (Marvell 88SE9230) carrying the OS mirror on
box-us17, where megacli segfaults. Status only -- alerting lives in
textfiles.rules.yml on mon6.

mvcli_up is printed even when everything else fails. The collector cron is
"./mvcli.py > x.prom.$$; mv x.prom.$$ x.prom" with no &&, so exiting non-zero
publishes an empty but freshly dated file that no staleness alert would catch.
"""

import argparse
import os.path
import re
import subprocess

MVCLI = '/usr/local/sbin/mvcli'
MOCK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mocks', 'mvcli')

SIZE_UNITS = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}
# BGA status when nothing is running. Firmware 2.5.13.1215 says "not running".
BGA_IDLE = ('not running', 'none', '')

DEBUG = False


def run(args, mock):
    """Return mvcli stdout, or None if the call failed.

    One missing section must not suppress the others, so callers treat None as
    "skip these metrics" rather than aborting.
    """
    if DEBUG:
        try:
            with open(os.path.join(MOCK_DIR, mock)) as handle:
                return handle.read()
        except OSError:
            return None
    try:
        res = subprocess.run([MVCLI] + args, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, check=True,
                             universal_newlines=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    return res.stdout


def blocks(text):
    """Split mvcli output into `key: value` dicts, one per blank-line-separated
    record. Keys are lower-cased because mvcli mixes `id:`, `PD ID:` and
    `RAID mode:` in the same output. Lines without a colon -- banners and the
    `-----` rules under them -- are dropped.
    """
    records = []
    current = {}
    for line in (text or '').splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, sep, value = line.partition(':')
        if sep:
            current[key.strip().lower()] = value.strip()
    if current:
        records.append(current)
    return records


def size_bytes(value):
    """`228872 M` / `234431064 K` -> bytes. mvcli counts in binary multiples."""
    match = re.match(r'([\d.]+)\s*([KMGT])\b', value.strip(), re.IGNORECASE)
    if not match:
        return None
    return int(float(match.group(1)) * SIZE_UNITS[match.group(2).upper()])


def total(text, key):
    """Read a `Total # of ...` trailer, which mvcli prints as its own record."""
    for record in blocks(text):
        if key in record:
            try:
                return int(record[key])
            except ValueError:
                return None
    return None


def smart_threshold_exceeded(pd_id):
    """1 if the drive reports a failing SMART status or holds an attribute at
    or below its threshold, 0 if clean, None if it could not be read.

    `info -o pd` carries no SMART verdict, so this comes from `mvcli smart`.
    Attributes with threshold 0 have no defined failure point and are skipped.
    """
    text = run(['smart', '-p', str(pd_id)], 'smart_%s.txt' % pd_id)
    if text is None:
        return None
    exceeded = 0
    parsed = False
    for line in text.splitlines():
        if line.startswith('SMART STATUS RETURN'):
            parsed = True
            if line.partition(':')[2].strip().rstrip('.').upper() != 'OK':
                exceeded = 1
            continue
        # ID, Attribute Name, Current, Worst, Threshhold [sic], RawValue
        fields = line.split('\t')
        if len(fields) < 6 or not re.fullmatch(r'[0-9A-Fa-f]{2}', fields[0].strip()):
            continue
        try:
            current, threshold = int(fields[2].strip()), int(fields[4].strip())
        except ValueError:
            continue
        parsed = True
        if threshold > 0 and current <= threshold:
            exceeded = 1
    return exceeded if parsed else None


class Metrics:
    """Collects samples and renders them in node_exporter's text format."""

    def __init__(self):
        self.families = []
        self.index = {}

    def add(self, name, help_text, labels, value, kind='gauge'):
        family = self.index.get(name)
        if family is None:
            family = (name, help_text, kind, [])
            self.index[name] = family
            self.families.append(family)
        family[3].append((labels, value))

    def render(self):
        lines = []
        for name, help_text, kind, samples in self.families:
            lines.append('# HELP %s %s' % (name, help_text))
            lines.append('# TYPE %s %s' % (name, kind))
            for labels, value in samples:
                lines.append('%s%s %s' % (name, format_labels(labels), value))
        return '\n'.join(lines)


def format_labels(labels):
    if not labels:
        return ''
    parts = []
    for key in sorted(labels):
        value = (str(labels[key]).replace('\\', '\\\\')
                 .replace('"', '\\"').replace('\n', '\\n'))
        parts.append('%s="%s"' % (key, value))
    return '{%s}' % ','.join(parts)


def collect(metrics):
    """Emit everything readable. Returns True if all three sections parsed."""
    hba_text = run(['info', '-o', 'hba'], 'hba.txt')
    vd_text = run(['info', '-o', 'vd'], 'vd.txt')
    pd_text = run(['info', '-o', 'pd'], 'pd.txt')

    hba = blocks(hba_text)
    vds = [b for b in blocks(vd_text) if 'id' in b]
    pds = [b for b in blocks(pd_text) if 'pd id' in b]

    # All three commands address the same controller, but only `info -o hba`
    # and the pd records name it.
    adapter = '0'
    if hba:
        adapter = hba[0].get('adapter id', adapter)
    elif pds:
        adapter = pds[0].get('adapter', adapter)

    if hba:
        metrics.add('mvcli_controller_info', 'Controller identity; always 1.', {
            'adapter': adapter,
            'product': hba[0].get('product', ''),
            'model': hba[0].get('model', ''),
            'firmware_version': hba[0].get('firmware version', ''),
        }, 1)

    for vd in vds:
        labels = {'adapter': adapter, 'vd': vd['id']}
        status = vd.get('status', '')
        metrics.add('mvcli_vd_status_ok', 'Virtual disk status is functional.',
                    dict(labels, name=vd.get('name', ''),
                         raid_mode=vd.get('raid mode', ''), status=status),
                    int(status.lower() == 'functional'))
        bga = vd.get('bga status', '')
        metrics.add('mvcli_vd_bga_active',
                    'Background activity (rebuild, consistency check) is running.',
                    dict(labels, bga_status=bga),
                    int(bga.lower() not in BGA_IDLE))
        size = size_bytes(vd.get('size', ''))
        if size is not None:
            metrics.add('mvcli_vd_size_bytes', 'Virtual disk size.', labels, size)

    for pd in pds:
        labels = {'adapter': pd.get('adapter', adapter), 'pd': pd['pd id']}
        metrics.add('mvcli_pd_info', 'Physical disk identity; always 1.',
                    dict(labels, model=pd.get('model', ''),
                         serial=pd.get('serial', '')), 1)
        # BOSS-S1 firmware 2.5.13.1215 reports no per-disk status. Emit the
        # metric only if a firmware that does report one turns up, rather than
        # inventing a healthy value; a member that drops out instead shows up
        # as mvcli_pd_count falling below the mirror width.
        if 'status' in pd:
            metrics.add('mvcli_pd_status_ok', 'Physical disk status is online.',
                        dict(labels, model=pd.get('model', ''),
                             serial=pd.get('serial', ''), status=pd['status']),
                        int(pd['status'].lower() == 'online'))
        size = size_bytes(pd.get('size', ''))
        if size is not None:
            metrics.add('mvcli_pd_size_bytes', 'Physical disk size.', labels, size)
        exceeded = smart_threshold_exceeded(pd['pd id'])
        if exceeded is not None:
            metrics.add('mvcli_pd_smart_threshold_exceeded',
                        'Drive reports a failing SMART status or an attribute '
                        'at or below its threshold.', labels, exceeded)

    # The trailer is authoritative, but fall back to what we enumerated so the
    # missing-member alert keeps working if mvcli stops printing it.
    vd_count = total(vd_text, 'total # of vd')
    if vd_count is None and vd_text is not None:
        vd_count = len(vds)
    if vd_count is not None:
        metrics.add('mvcli_vd_count', 'Virtual disks the controller enumerates.',
                    {'adapter': adapter}, vd_count)

    pd_count = total(pd_text, 'total # of pd')
    if pd_count is None and pd_text is not None:
        pd_count = len(pds)
    if pd_count is not None:
        metrics.add('mvcli_pd_count', 'Physical disks the controller enumerates.',
                    {'adapter': adapter}, pd_count)

    return bool(hba) and bool(vds) and bool(pds)


def main():
    global DEBUG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--debug', action='store_true',
                        help='parse mocks/mvcli/*.txt instead of running mvcli')
    DEBUG = parser.parse_args().debug

    metrics = Metrics()
    try:
        ok = collect(metrics)
    except Exception:  # a crash must still publish mvcli_up 0
        ok = False
    metrics.add('mvcli_up', 'Controller was read and all sections parsed.', {}, int(ok))
    print(metrics.render())


if __name__ == '__main__':
    main()
