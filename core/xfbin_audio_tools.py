"""Embedded audio IO. Siren is decoded by vgmstream; PCM is never labelled IS14."""
import os
import struct
import subprocess
import tempfile

from core.external_tools import find_ffmpeg, find_vgmstream_cli, tool_command
from parsers.nus3bank_parser import parse_audio_meta


def run_tool(command, output):
    result = subprocess.run(command, capture_output=True, timeout=180,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not os.path.isfile(output) or not os.path.getsize(output):
        details = (result.stderr or result.stdout).decode(errors='replace').strip()
        raise RuntimeError(details or f'Audio converter exited with {result.returncode}')
    with open(output, 'rb') as stream:
        return stream.read()


def decode_audio(blob, cli=None, extension='.bnsf'):
    info = parse_audio_meta(blob)
    if info and info['codec'] == 'PCM16':
        return blob
    cli = cli or find_vgmstream_cli()
    if not cli:
        raise RuntimeError('vgmstream-cli is required for Siren14/22 decoding. Configure it in Settings.')
    with tempfile.TemporaryDirectory() as folder:
        source, output = os.path.join(folder, 'source' + extension), os.path.join(folder, 'tone.wav')
        with open(source, 'wb') as stream:
            stream.write(blob)
        return run_tool([*tool_command(cli), '-i', '-o', output, source], output)


def import_audio(blob, source_path=''):
    """Accept validated Siren unchanged, or convert to native-supported PCM16 RIFF."""
    info = parse_audio_meta(blob)
    if info:
        return blob
    if blob[:4] == b'BNSF':
        raise ValueError('Malformed or unsupported BNSF header')
    extension = os.path.splitext(source_path)[1].lower()
    if extension in ('.hca', '.adx') or blob[:3] in (b'HCA', bytes((0xc8, 0xc3, 0xc1))) or blob[:2] == b'\x80\x00':
        if blob[:2] == b'\x80\x00':
            extension = '.adx'
        extension = '.hca' if blob[:3] in (b'HCA', bytes((0xc8, 0xc3, 0xc1))) else extension
        result = decode_audio(blob, extension=extension)
        if not parse_audio_meta(result):
            raise ValueError('Decoded audio is not supported mono/stereo PCM16')
        return result
    cli = find_ffmpeg()
    if not cli:
        raise RuntimeError('FFmpeg is required to convert this audio to PCM16 WAV. Configure it in Settings.')
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, 'source' + (os.path.splitext(source_path)[1] or '.bin'))
        output = os.path.join(folder, 'tone.wav')
        with open(source, 'wb') as stream:
            stream.write(blob)
        result = run_tool([*tool_command(cli), '-v', 'error', '-y', '-i', source,
                           '-map', '0:a:0', '-c:a', 'pcm_s16le', output], output)
        if not parse_audio_meta(result):
            raise ValueError('Import requires mono or stereo PCM16 audio')
        return result


def stream_loop(blob):
    info = parse_audio_meta(blob)
    if not info:
        return None
    if info['codec'] != 'PCM16':
        start, end = info['loop_start'], info['loop_end']
    else:
        start, end = None, None
        for tag, data in riff_chunks(blob):
            if tag == b'smpl' and len(data) >= 60 and struct.unpack_from('<I', data, 28)[0] == 1:
                start, last = struct.unpack_from('<II', data, 44)
                end = last + 1
                break
    if start is not None and 0 <= start and start + 2 <= end <= info['total_samples']:
        return start, end
    return None


def riff_chunks(blob):
    pos = 12
    while pos + 8 <= len(blob):
        tag, size = blob[pos:pos + 4], struct.unpack_from('<I', blob, pos + 4)[0]
        if pos + 8 + size > len(blob):
            raise ValueError('Truncated RIFF chunk')
        yield tag, memoryview(blob)[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)


def set_stream_loop(blob, enabled, start=0, end=0):
    info = parse_audio_meta(blob)
    if not info:
        raise ValueError('Unsupported embedded stream')
    if enabled and not (0 <= start and start + 2 <= end <= info['total_samples']):
        raise ValueError('Loop requires at least two samples, with 0 <= start < exclusive end <= stream length')
    if info['codec'] == 'PCM16':
        chunks = [(tag, data) for tag, data in riff_chunks(blob) if tag != b'smpl']
        if enabled:
            header = struct.pack('<9I', 0, 0, round(1e9 / info['sample_rate']), 60, 0, 0, 0, 1, 0)
            chunks.append((b'smpl', header + struct.pack('<6I', 0, 0, start, end - 1, 0, 0)))
        body = b'WAVE' + b''.join(tag + struct.pack('<I', len(data)) + bytes(data) + b'\0' * (len(data) & 1) for tag, data in chunks)
        return b'RIFF' + struct.pack('<I', len(body)) + body
    if info['flags']:
        raise ValueError('Loop authoring for keyed BNSF is unavailable')
    body = bytearray(blob[8:12])
    pos = 12
    aligned = start - start % info['block_samples'] if enabled else 0
    while pos + 8 <= len(blob):
        size = struct.unpack_from('>I', blob, pos + 4)[0]
        tag, data = blob[pos:pos + 4], bytearray(blob[pos + 8:pos + 8 + size])
        pos += 8 + size + (size & 1)
        if tag == b'loop':
            continue
        if tag == b'sfmt':
            struct.pack_into('>I', data, 12, start - aligned if enabled else 0)
        if tag == b'sdat' and enabled:
            body += b'loop' + struct.pack('>III', 8, aligned, end - 1)
        body += tag + struct.pack('>I', size) + data + b'\0' * (size & 1)
    size = len(body) + (8 if blob[8:12] == b'IS22' else 0)
    return b'BNSF' + struct.pack('>I', size) + body


def tone_state(tone):
    from parsers.nus3bank_parser import TONE_FIELDS
    return (tone.name, tone.flags, tone.type_id, bytes(tone._raw_params),
            tuple(getattr(tone, name) for name, _, _ in TONE_FIELDS if name not in ('pack_offset', 'pack_size')),
            tone._bnsf_blob)


def export_filename(index, name, extension):
    safe = ''.join('_' if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in name).strip(' .')[:120]
    return f'{index:05d}_{safe or "tone"}{extension}'
