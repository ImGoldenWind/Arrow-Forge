"""USM media metadata and conversion plans; no Qt or invented game parameters.

Sofdec owns the container/codec. FFmpeg owns explicit pixel/time/audio edits.
The H.264 wrapper is deliberately unused: it drops AVI audio and formats FPS
with the Windows decimal separator. The standard encoder can mux Annex B ES.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import os
import shutil
import tempfile


@dataclass(frozen=True)
class MediaInfo:
    path: str = ''
    duration: float = 0.
    video_codec: str = ''
    width: int = 0
    height: int = 0
    fps_text: str = ''
    fps: float = 0.
    audio_codec: str = ''
    audio_channels: int = 0
    audio_layout: str = ''
    audio_rate: int = 0
    video_streams: int = 0
    audio_streams: int = 0
    other_streams: int = 0
    format_name: str = ''
    sample_aspect: str = '1:1'


def positive(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else 0.
    except (ValueError, TypeError):
        return 0.


def parse_rate(value):
    try:
        rate = Fraction(str(value))
        if rate > 0:
            return str(rate), float(rate)
    except (ValueError, ZeroDivisionError, TypeError):
        pass
    return '', 0.


def parse_media(data, path=''):
    streams = data.get('streams') or []
    videos = [s for s in streams if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')]
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    if not videos:
        raise ValueError('usm_error_no_video')
    video, audio = videos[0], audios[0] if audios else {}
    rate, fps = parse_rate(video.get('avg_frame_rate'))
    if not fps:
        rate, fps = parse_rate(video.get('r_frame_rate'))
    duration = positive(video.get('duration'))
    if not duration and fps:
        duration = positive(video.get('nb_frames')) / fps
    duration = duration or positive((data.get('format') or {}).get('duration'))
    info = MediaInfo(
        path=path, duration=duration, video_codec=video.get('codec_name', ''),
        width=int(video.get('width') or 0), height=int(video.get('height') or 0),
        fps_text=rate, fps=fps, audio_codec=audio.get('codec_name', ''),
        audio_channels=int(audio.get('channels') or 0), audio_layout=audio.get('channel_layout', ''),
        audio_rate=int(audio.get('sample_rate') or 0), video_streams=len(videos),
        audio_streams=len(audios), format_name=(data.get('format') or {}).get('format_name', ''),
        other_streams=len(streams) - len(videos) - len(audios),
        sample_aspect=video.get('sample_aspect_ratio') or '1:1',
    )
    if info.width <= 0 or info.height <= 0:
        raise ValueError('usm_error_no_video')
    return info


def check_usm(path):
    with open(path, 'rb') as handle:
        if handle.read(4) != b'CRID':
            raise ValueError('usm_error_container')


@dataclass(frozen=True)
class VideoEdits:
    start: float
    end: float
    fit: str = 'fit'
    audio: str = 'import'

    @property
    def duration(self):
        return self.end - self.start

    def validate(self, original, imported):
        if (not math.isfinite(self.start) or not math.isfinite(self.end)
                or self.start < 0 or self.duration <= 0
                or self.end > imported.duration + .001):
            raise ValueError('usm_error_trim')
        if original.video_streams != 1 or original.audio_streams > 1 or original.other_streams:
            raise ValueError('usm_error_tracks')
        if original.video_codec not in ('mpeg1video', 'h264'):
            raise ValueError('usm_error_codec')
        if original.audio_codec not in ('', 'adpcm_adx', 'hca'):
            raise ValueError('usm_error_codec')
        if not original.fps or not original.duration or not imported.duration:
            raise ValueError('usm_error_timing')
        if self.fit not in ('fit', 'crop', 'stretch') or self.audio not in ('import', 'original', 'silent'):
            raise ValueError('usm_error_options')
        if ((self.audio == 'import' and not imported.audio_codec)
                or (self.audio == 'original' and not original.audio_codec)):
            raise ValueError('usm_error_audio_source')
        # Keep the container's sample aspect, rather than silently stretching it.
        if original.sample_aspect not in ('1:1', '0:1', 'N/A'):
            raise ValueError('usm_error_aspect')


def fit_filter(width, height, mode='fit'):
    if mode == 'stretch':
        return f'scale={width}:{height},setsar=1'
    if mode == 'crop':
        return (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                f'crop={width}:{height},setsar=1')
    if mode != 'fit':
        raise ValueError('usm_error_options')
    return (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')


def audio_source(original, imported, edits):
    if edits.audio == 'silent':
        return None
    info = original if edits.audio == 'original' else imported
    return info if info.audio_codec else None


def prepare_args(original, imported, edits, video_path, audio_path):
    """Return one FFmpeg invocation. Video length never depends on audio length.

    Original audio starts at movie time zero; imported audio follows the trim.
    Audio is padded with silence and limited to the selected video interval.
    """
    edits.validate(original, imported)
    args = ['-hide_banner', '-nostdin', '-y', '-ss', f'{edits.start:.6f}', '-i', imported.path]
    sound = audio_source(original, imported, edits)
    if sound is original:
        args += ['-i', original.path]
    source_timing, _ = video_timing_args(imported)
    filters = ((source_timing + ',' if source_timing else '')
               + fit_filter(original.width, original.height, edits.fit) + f',fps={original.fps_text}')
    args += ['-map', '0:v:0', '-vf', filters, '-t', f'{edits.duration:.6f}']
    h264 = original.video_codec == 'h264'
    if h264:
        args += ['-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18',
                 '-x264-params', f'bframes=0:aud=1:keyint={max(1, round(original.fps))}', '-f', 'h264', video_path]
        if sound:
            index = 1 if sound is original else 0
            args += ['-map', f'{index}:a:0', '-vn', '-af', 'apad', '-t', f'{edits.duration:.6f}', '-c:a', 'pcm_s16le']
            args += _audio_format(original, sound) + [audio_path]
    else:
        args += ['-c:v', 'rawvideo', '-pix_fmt', 'bgr24']
        if sound:
            index = 1 if sound is original else 0
            args += ['-map', f'{index}:a:0', '-af', 'apad', '-c:a', 'pcm_s16le'] + _audio_format(original, sound)
        else:
            args += ['-an']
        args += [video_path]
    return args


def _audio_format(original, sound):
    return ['-ac', str(original.audio_channels or sound.audio_channels),
            '-ar', str(original.audio_rate or sound.audio_rate)]


def encoder_args(original, imported, edits, video_path, audio_path, output_path):
    norm = os.path.normpath
    if original.video_codec == 'h264':
        args = [f'-video00={norm(video_path)}']
        if audio_source(original, imported, edits):
            args += [f'-audio00={norm(audio_path)}']
    else:
        args = [f'-in={norm(video_path)}']
    args += [f'-out={norm(output_path)}']
    if original.audio_codec == 'hca' and audio_source(original, imported, edits):
        args += ['-hca=ON', '-hca_quality=4']
    return args


def validate_output(info, original, imported, edits):
    if info.format_name != 'usm' or info.video_streams != 1:
        raise ValueError('usm_error_container')
    # Sofdec Prime is reported as MPEG-1 by FFprobe; preserve that family.
    if info.video_codec != original.video_codec:
        raise ValueError('usm_error_output_profile')
    if (info.width, info.height) != (original.width, original.height):
        raise ValueError('usm_error_output_profile')
    if abs(info.fps - original.fps) > .01 or abs(info.duration - edits.duration) > 2 / original.fps + .01:
        raise ValueError('usm_error_output_profile')
    sound = audio_source(original, imported, edits)
    if info.audio_streams != int(sound is not None):
        raise ValueError('usm_error_output_audio')
    if sound:
        codec = original.audio_codec or 'adpcm_adx'
        if (info.audio_codec != codec or info.audio_channels != (original.audio_channels or sound.audio_channels)
                or info.audio_rate != (original.audio_rate or sound.audio_rate)):
            raise ValueError('usm_error_output_audio')


def video_timing_args(info):
    # The USM demuxer timestamps coded packets; MPEG B-frame reordering makes
    # those unsuitable as presentation timestamps. USM VIDEO_HDRINFO provides
    # the constant presentation rate. Rebuild it from decoded frame order.
    if info and info.format_name == 'usm' and info.fps:
        return f'setpts=N/({info.fps_text}*TB)', ['-r', info.fps_text, '-fps_mode', 'cfr']
    return '', []


def preview_args(path, output, info=None):
    timing, options = video_timing_args(info)
    filters = (timing + ',' if timing else '') + 'scale=min(1280\\,iw):-2'
    return ['-hide_banner', '-nostdin', '-y', '-i', path, '-map', '0:v:0', '-map', '0:a:0?',
            '-vf', filters, *options, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', output]


def intermediate_bytes(original, edits):
    """Conservative raw AVI estimate; H.264 uses compressed intermediate ES."""
    if original.video_codec == 'h264':
        return 0
    return math.ceil(edits.duration * original.fps) * original.width * original.height * 3


def atomic_copy_usm(source, target):
    """Only validated container bytes may enter a user's destination."""
    check_usm(source)
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        return
    directory = os.path.dirname(os.path.abspath(target))
    fd, temporary = tempfile.mkstemp(prefix='.arrowforge-usm-', suffix='.tmp', dir=directory)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        with open(temporary, 'r+b') as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
