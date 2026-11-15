"""ACF 1.12 findings from the installed ASBR CRI readers/consumers.

RVA evidence and the remaining limits are in docs/acf-research.md.
No executable code or game data is embedded here.
"""
import math
from dataclasses import dataclass

from parsers.acf_dsp import DspField, FX_NAMES
from parsers.asb_acf_parser import AcfBlob


@dataclass(frozen=True)
class CommandField(DspField):
    blob_name: str = 'Command'


def command_fields(data):
    """Decode only complete, known cue-limit packets; leave other streams raw.

    A83900 reads a BE u16 opcode, u8 payload length, then BE operands.
    0049: limit/work index. 004F adds the selection-policy byte.
    """
    fields = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 3:
            return ()
        opcode = int.from_bytes(data[offset:offset + 2], 'big')
        size = data[offset + 2]
        end = offset + 3 + size
        if end > len(data) or (opcode, size) not in ((0x49, 4), (0x4f, 5)):
            return ()
        fields.extend((CommandField('cue_limit', offset + 3, 'H'),
                       CommandField('cue_work_index', offset + 5, 'H')))
        if opcode == 0x4f:
            fields.append(CommandField('cue_policy', offset + 7, 'B'))
        offset = end
    return tuple(fields)


def normalized_frequency(value):
    """Native A6F820, including its endpoint thresholds and float constants."""
    if not math.isfinite(value):
        return None
    if value <= 1 / 65536:
        return 24.0
    if value >= 1 - 1 / 65536:
        return 24000.0
    return min(24000.0, max(24.0, 2 ** ((value * 2.1735804080963135 + 1) * 4.584962368011475)))


def table_by_name(tables, name):
    return next((table for table in tables if table.name == name), None)


def category_name(tables, index):
    table = table_by_name(tables, 'CategoryName')
    return ' / '.join(str(row.get('Name', '')) for row in table.rows if row.get('Index') == index) if table else ''


def bus_name(tables, index):
    table = table_by_name(tables, 'BusName')
    if table and isinstance(index, int) and 0 <= index < len(table.rows):
        return str(table.rows[index].get('StringValue', index))
    return str(index)


def routing_rows(tables):
    """Source bus, ordered DSP chain, and direct sends (no signal simulation)."""
    buses = table_by_name(tables, 'Bus')
    effects = table_by_name(tables, 'DspFx')
    links = table_by_name(tables, 'BusLink')
    result = []
    for row in buses.rows if buses else []:
        fx_start, fx_count = row.get('StartFxIndex', 65535), row.get('NumFxs', 0)
        chain = []
        if effects and 0 <= fx_start < len(effects.rows):
            for effect in effects.rows[fx_start:fx_start + fx_count]:
                chain.append(FX_NAMES.get(effect.get('FxType'), str(effect.get('FxType'))))
        sends = []
        start, count = row.get('StartBusLinkIndex', 65535), row.get('NumBusLinks', 0)
        if links and 0 <= start < len(links.rows):
            for link in links.rows[start:start + count]:
                sends.append((bus_name(tables, link.get('BusNameIndex', link.get('SendBusNo'))),
                              link.get('SendBusNo'), link.get('SendLevel'), link.get('Type')))
        result.append((bus_name(tables, row.get('BusNameIndex', row.get('BusNo'))),
                       row.get('BusNo'), tuple(chain), tuple(sends)))
    return result


def reference_issues(tables):
    """Concrete dangling ranges and stock cue-pool dependencies, never guesses."""
    issues = []
    def check(table, row_index, row, field, target, count_field=None):
        if field not in row:
            return
        value = row.get(field, 65535)
        count = row.get(count_field, 0) if count_field else 1
        dest = table_by_name(tables, target)
        size = len(dest.rows) if dest else 0
        if count and (value == 65535 or value < 0 or value + count > size):
            issues.append(f'{table.name}[{row_index}].{field} → {target}: {value} + {count} / {size}')
    for table in tables:
        for i, row in enumerate(table.rows):
            if table.name == 'Bus':
                check(table, i, row, 'StartFxIndex', 'DspFx', 'NumFxs')
                check(table, i, row, 'StartBusLinkIndex', 'BusLink', 'NumBusLinks')
            elif table.name == 'DspSetting':
                check(table, i, row, 'StartIndex', 'Bus', 'NumBuses')
            elif table.name == 'Category' and row.get('CommandIndex', 65535) != 65535:
                check(table, i, row, 'CommandIndex', 'Command')
            elif table.name == 'React':
                check(table, i, row, 'Src', 'Category')
                check(table, i, row, 'Dest', 'Category')
            if table.name in ('CategoryName', 'GameVariableName'):
                check(table, i, row, 'Index', 'Category' if table.name == 'CategoryName' else 'GameVariable')
            if table.name in ('Bus', 'BusLink'):
                check(table, i, row, 'BusNameIndex', 'BusName')
    header = table_by_name(tables, 'Header')
    commands = table_by_name(tables, 'Command')
    if header and header.rows and commands:
        h = header.rows[0]
        pool = {}
        categories = table_by_name(tables, 'Category')
        used = {row.get('CommandIndex') for row in categories.rows} if categories else set(range(len(commands.rows)))
        for i, row in enumerate(commands.rows):
            if i not in used:
                continue
            blob = row.get('Command')
            if not isinstance(blob, AcfBlob):
                continue
            fields = command_fields(blob.data)
            for pos, field in enumerate(fields):
                if field.name != 'cue_limit':
                    continue
                limit, index = field.read(blob.data), fields[pos + 1].read(blob.data)
                if not limit or index == 65535:
                    continue
                if index >= h.get('NumCueLimitListWorks', 0):
                    issues.append(f'Command[{i}]: work {index} / NumCueLimitListWorks {h.get("NumCueLimitListWorks", 0)}')
                if index in pool and pool[index] != limit:
                    issues.append(f'Command[{i}]: work {index}: {pool[index]} ≠ {limit}')
                pool[index] = limit
        nodes = h.get('NumCueLimitNodeWorks', 0)
        if sum(pool.values()) > nodes:
            issues.append(f'Command: Σ limits {sum(pool.values())} > NumCueLimitNodeWorks {nodes}')
        # A85E74 aligns the workspace to 8 bytes, then uses 48/list + 16/node.
        blob = h.get('CueLimitWorkTable')
        required = 48 * h.get('NumCueLimitListWorks', 0) + 16 * nodes
        if isinstance(blob, AcfBlob) and len(blob.data) < required:
            issues.append(f'CueLimitWorkTable: {len(blob.data)} bytes < {required}')
    return issues
