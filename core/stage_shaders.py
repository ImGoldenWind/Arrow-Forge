"""Read ASBR's NUP4 shader pairs and translate their SM4 arithmetic to GLSL.

No procedural replacement for the game's material shading is used here. The
translation retains register masks, bitwise predicates and literal float bits.
Unsupported instructions fail explicitly instead of disappearing from a shader.
"""
from dataclasses import dataclass
from functools import lru_cache
import ctypes
import re
import struct


def read_shader_package(data):
    if len(data) < 16 or data[:4] != b'NUP4':
        raise ValueError('Invalid NUP4 shader package')
    if struct.unpack_from('<I', data, 4)[0] != len(data):
        raise ValueError('Truncated NUP4 shader package')
    result, pos = {}, 16
    while pos < len(data):
        shader_id, = struct.unpack_from('<I', data, pos)
        pos += 4
        pair = []
        for _ in range(2):
            size, = struct.unpack_from('<I', data, pos)
            pos += 4
            code = data[pos:pos + size]
            if len(code) != size or code[:4] != b'DXBC':
                raise ValueError('Invalid NUP4 bytecode record')
            pair.append(code)
            pos += size
        if shader_id in result and result[shader_id] != tuple(pair):
            raise ValueError('Duplicate NUP4 shader identifier')
        result[shader_id] = tuple(pair)
    return result


@lru_cache(maxsize=512)
def disassemble(code):
    # Windows supplies this library; it does not need the game installation.
    dll = ctypes.WinDLL('d3dcompiler_47.dll')
    fn = dll.D3DDisassemble
    fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint,
                   ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = ctypes.c_long
    blob = ctypes.c_void_p()
    # PRINT_HEX_LITERALS: decimal disassembly rounds constants to six places.
    hr = fn(code, len(code), 0x80, None, ctypes.byref(blob))
    if hr < 0:
        raise RuntimeError(f'D3DDisassemble failed: {hr:#x}')
    table = ctypes.cast(blob, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    pointer = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(table[3])
    size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(table[4])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
    try:
        return ctypes.string_at(pointer(blob), size(blob)).rstrip(b'\0').decode('ascii')
    finally:
        release(blob)


def _operands(text):
    return re.split(r',\s*(?![^()]*\))', text)


def _source(operand, prefix):
    operand = operand.strip()
    if operand.startswith('-'):
        return '-(' + _source(operand[1:], prefix) + ')'
    if operand.startswith('|') and operand.endswith('|'):
        return 'abs(' + _source(operand[1:-1], prefix) + ')'
    if operand.startswith('l('):
        values = _operands(operand[2:-1])
        bits = []
        for value in values:
            value = value.strip()
            bit = int(value, 16) if value.startswith('0x') else struct.unpack('<I', struct.pack('<f', float(value)))[0]
            bits.append(f'0x{bit:08x}u')
        return 'uintBitsToFloat(uvec4(' + ','.join(bits) + '))'
    operand = re.sub(r'cb(\d+)\[', prefix + r'cb\1[', operand, flags=re.I)
    operand = re.sub(r'icb\[([rv]\d+)\.([xyzw])\s*\+\s*(\d+)\]',
                     r'icb[floatBitsToInt(\1.\2)+\3]', operand)
    match = re.fullmatch(r'(.+)\.([xyzw]{1,4})', operand)
    if match:
        name, mask = match.groups()
        if len(mask) == 1:
            return f'vec4({name}.{mask})'
        return f'{name}.{(mask + mask[-1] * 4)[:4]}'
    if not re.fullmatch(r'[rvio]\d+|[vp]cb\d+\[\d+\]', operand):
        raise ValueError('Unsupported SM4 operand: ' + operand)
    return operand


@dataclass
class ShaderTranslation:
    source: str
    constants: dict
    inputs: dict
    textures: dict


def translate_shader(assembly, vertex, *, output_targets=1, native_framebuffer=False):
    prefix = 'v' if vertex else 'p'
    constants = {name: (int(offset), int(size)) for name, offset, size in re.findall(
        r'//\s+(?:row_major\s+)?\w+(?:\d+x\d+)?\s+(\w+);\s*// Offset:\s*(\d+) Size:\s*(\d+)', assembly)}
    signature = assembly.split('// Input signature:')[-1].split('// Output signature:')[0]
    inputs = {int(reg): (name, int(index)) for name, index, reg in re.findall(
        r'//\s+(\w+)\s+(\d+)\s+[xyzw]+\s+(\d+)\s+\w+\s+\w+', signature)}
    declarations, body, textures = [], [], {}
    immediate = re.search(r'dcl_immediateConstantBuffer\s*\{(?:[^{}]|\{[^{}]*\})*\}', assembly)
    immediate_values = []
    if immediate:
        immediate_values = [_source('l(' + row + ')', prefix)
                            for row in re.findall(r'\{([^{}]+)\}', immediate[0])]
        assembly = assembly[:immediate.start()] + assembly[immediate.end():]
    lines = [line.strip() for line in assembly.splitlines()
             if line.strip() and not line.startswith('//')]
    input_regs, output_regs = set(), set()
    cb_size = 0
    writes_depth = False
    for line in lines:
        if line.startswith('dcl_constantbuffer'):
            match = re.search(r'cb0\[(\d+)\]', line, re.I)
            if not match:
                raise ValueError('Only per-material cb0 is supported')
            cb_size = int(match[1])
        elif line.startswith('dcl_input'):
            input_regs.add(int(re.search(r'v(\d+)', line)[1]))
        elif line.startswith('dcl_output'):
            if 'oDepth' in line:
                writes_depth = True
            else:
                output_regs.add(int(re.search(r'o(\d+)', line)[1]))
        elif line.startswith('dcl_resource_texture'):
            unit = int(re.search(r't(\d+)', line)[1])
            if 'texture2d ' in line:
                textures[unit] = 'sampler2D'
            elif 'texturecube ' in line:
                textures[unit] = 'samplerCube'
            else:
                raise ValueError('Unsupported texture resource: ' + line)
        elif line.startswith('dcl_temps'):
            for i in range(int(line.split()[1])):
                declarations.append(f'vec4 r{i}=vec4(0);')
        elif line.startswith(('dcl_', 'vs_', 'ps_')):
            if line.startswith('dcl_immediate'):
                raise ValueError('Immediate constant tables are not supported')
        else:
            op, _, args = line.partition(' ')
            args = _operands(args)
            if op == 'ret':
                continue  # These material shaders have a single terminal return.
            if op in ('else', 'endif', 'endloop'):
                body.append('} else {' if op == 'else' else '}')
                continue
            if op == 'loop':
                body.append('while (true) {')
                continue
            if op in ('discard_nz', 'if_nz', 'breakc_nz'):
                condition = f'any(notEqual(floatBitsToUint({_source(args[0], prefix)}),uvec4(0)))'
                body.append(f'if ({condition}) ' + ('discard;' if op == 'discard_nz' else 'break;' if op == 'breakc_nz' else '{'))
                continue
            destination, *raw = args
            if op == 'sincos':
                cosine, value = raw
                for target, fn in ((destination, 'sin'), (cosine, 'cos')):
                    if target != 'null':
                        mask = target.partition('.')[2]
                        body.append(f'_value={fn}({_source(value, prefix)}); {target}=_value' + ('.' + mask if mask else '') + ';')
                continue
            src = [_source(a, prefix) for a in raw] if not op.startswith('sample') else []
            saturate = op.endswith('_sat')
            op = op.removesuffix('_sat')
            if op in ('add', 'mul', 'div'):
                expr = f'({src[0]} {dict(add="+", mul="*", div="/")[op]} {src[1]})'
            elif op == 'mad':
                expr = f'({src[0]} * {src[1]} + {src[2]})'
            elif op == 'mov':
                expr = src[0]
            elif op in ('dp2', 'dp3', 'dp4'):
                mask = 'xyzw'[:int(op[-1])]
                expr = f'vec4(dot(({src[0]}).{mask},({src[1]}).{mask}))'
            elif op in ('min', 'max'):
                expr = f'{op}({src[0]},{src[1]})'
            elif op in ('lt', 'ge', 'eq', 'ne', 'ige'):
                fn = dict(lt='lessThan', ge='greaterThanEqual', eq='equal', ne='notEqual', ige='greaterThanEqual')[op]
                a, b = src
                if op == 'ige':
                    a, b = f'floatBitsToInt({a})', f'floatBitsToInt({b})'
                expr = f'uintBitsToFloat(uvec4({fn}({a},{b}))*0xffffffffu)'
            elif op == 'movc':
                expr = f'mix({src[2]},{src[1]},notEqual(floatBitsToUint({src[0]}),uvec4(0)))'
            elif op in ('sqrt', 'rsq', 'exp', 'log', 'frc', 'round_z', 'round_ni'):
                fn = dict(sqrt='sqrt', rsq='inversesqrt', exp='exp2', log='log2', frc='fract', round_z='trunc', round_ni='floor')[op]
                expr = f'{fn}({src[0]})'
            elif op in ('and', 'or', 'ishl', 'ishr', 'iadd'):
                symbol = {'and':'&', 'or':'|', 'ishl':'<<', 'ishr':'>>', 'iadd':'+'}[op]
                conv = 'floatBitsToInt' if op in ('ishr', 'iadd') else 'floatBitsToUint'
                back = 'intBitsToFloat' if conv.endswith('Int') else 'uintBitsToFloat'
                operands = [f'{conv}({value})' for value in src]
                if op in ('iadd', 'ishr', 'ishl'):
                    # SM4 integer source negation is two's complement, not a
                    # float sign-bit change on a typeless register.
                    operands = ['-(' + conv + '(' + _source(raw_value[1:], prefix) + '))'
                                if raw_value.startswith('-') else converted
                                for raw_value, converted in zip(raw, operands)]
                expr = f'{back}({operands[0]} {symbol} {operands[1]})'
            elif op in ('itof', 'utof', 'ftoi'):
                expr = f'vec4(floatBitsToInt({src[0]}))' if op == 'itof' else f'vec4(floatBitsToUint({src[0]}))' if op == 'utof' else f'intBitsToFloat(ivec4({src[0]}))'
            elif op in ('sample', 'sample_c_lz', 'sample_d', 'sample_l'):
                coord, texture, sampler, *extra = raw
                unit = int(re.search(r't(\d+)', texture)[1])
                mask = 'xyz' if textures[unit] == 'samplerCube' else 'xy'
                uv = f'({_source(coord, prefix)}).{mask}'
                if op == 'sample_c_lz':
                    textures[unit] = 'sampler2DShadow'
                    expr = f'vec4(texture(tex{unit},vec3({uv},({_source(extra[0], prefix)}).x)))'
                elif op == 'sample_d':
                    expr = f'textureGrad(tex{unit},{uv},({_source(extra[0], prefix)}).xy,({_source(extra[1], prefix)}).xy)'
                elif op == 'sample_l':
                    expr = f'textureLod(tex{unit},{uv},({_source(extra[0], prefix)}).x)'
                else:
                    expr = f'texture(tex{unit},{uv})'
                swizzle = texture.partition('.')[2]
                if swizzle:
                    expr += '.' + swizzle
            else:
                raise ValueError('Unsupported SM4 instruction: ' + line)
            if saturate:
                expr = f'clamp({expr},0.0,1.0)'
            mask = destination.partition('.')[2]
            body.append(f'_value = {expr}; {destination} = _value' +
                        ('.x' if destination == 'oDepth' else '.' + mask if mask else '') + ';')
    header = ['#version 330 compatibility']
    if immediate_values:
        header.append(f'const vec4 icb[{len(immediate_values)}]=vec4[](' + ','.join(immediate_values) + ');')
    if cb_size:
        header.append(f'uniform vec4 {prefix}cb0[{cb_size}];')
    header.extend(f'uniform {kind} tex{unit};' for unit, kind in textures.items())
    if vertex:
        header.extend(f'attribute vec4 a{reg};' for reg in sorted(input_regs))
        header.extend(f'out vec4 io{reg};' for reg in sorted(output_regs) if reg != 0)
    else:
        header.extend(f'in vec4 io{reg};' for reg in sorted(input_regs) if reg != 0)
        header.append('layout(location=0) out vec4 fragColor;')
        header.extend(f'layout(location={reg}) out vec4 fragColor{reg};'
                      for reg in sorted(output_regs) if 0 < reg < output_targets)
    start = ['void main() {', 'vec4 _value;'] + declarations
    for reg in sorted(input_regs):
        expr = f'a{reg}' if vertex else 'gl_FragCoord' if reg == 0 else f'io{reg}'
        start.append(f'vec4 v{reg}={expr};')
    start.extend(f'vec4 o{reg}=vec4(0);' for reg in sorted(output_regs))
    if writes_depth:
        start.append('float oDepth=0.0;')
    end = ['gl_Position=o0; gl_Position.z=2.0*o0.z-o0.w;'] if vertex else ['fragColor=o0;']
    if vertex:
        if native_framebuffer:
            end.append('gl_Position.y=-gl_Position.y;')
        end.extend(f'io{reg}=o{reg};' for reg in sorted(output_regs) if reg != 0)
    else:
        end.extend(f'fragColor{reg}=o{reg};' for reg in sorted(output_regs) if 0 < reg < output_targets)
        if writes_depth:
            end.append('gl_FragDepth=oDepth;')
    return ShaderTranslation('\n'.join(header + start + body + end + ['}']), constants, inputs, textures)
