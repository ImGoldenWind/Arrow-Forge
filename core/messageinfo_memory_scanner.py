import ctypes
import os
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass


_ASCII_RE = re.compile(rb"[A-Za-z0-9_./:-]{4,96}")
_TEXT_RE = re.compile(r"[A-Za-z0-9_./:-]{4,96}")
_TOKEN_RE = re.compile(
    r"("
    r"_btlst_|_win_|c_name_|modeselect_|artv_|"
    r"tutorial|term_|guide|result|gallery|soundtest|"
    r"^[0-9][a-z]{3}[0-9]{2}_[A-Za-z0-9_:-]+$"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    path: str = ""

    @property
    def label(self) -> str:
        base = f"{self.name} ({self.pid})"
        return f"{base} - {self.path}" if self.path else base


@dataclass(frozen=True)
class MemoryScanResult:
    strings: set[str]
    regions: int = 0
    bytes_read: int = 0


class MemoryScanError(RuntimeError):
    pass


if sys.platform.startswith("win"):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010

    MEM_COMMIT = 0x1000
    PAGE_NOACCESS = 0x01
    PAGE_GUARD = 0x100
    PAGE_READABLE_MASK = 0xEE

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("PartitionId", wintypes.WORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def list_processes() -> list[ProcessInfo]:
    if not sys.platform.startswith("win"):
        return []

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        result: list[ProcessInfo] = []
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            name = entry.szExeFile
            result.append(ProcessInfo(pid=pid, name=name, path=_process_path(pid)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        result.sort(key=lambda p: (0 if p.name.lower() == "asbr.exe" else 1, p.name.lower(), p.pid))
        return result
    finally:
        kernel32.CloseHandle(snapshot)


def scan_process_strings(pid: int, *, max_region_bytes: int = 32 * 1024 * 1024) -> MemoryScanResult:
    if not sys.platform.startswith("win"):
        raise MemoryScanError("Live memory capture is only available on Windows.")

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
    if not handle:
        err = ctypes.get_last_error()
        raise MemoryScanError(
            f"Could not read the selected process (WinError {err}). "
            "If the game is protected by EAC, launch ASBR.exe directly or use an imported map."
        )

    try:
        strings: set[str] = set()
        regions = 0
        bytes_read = 0
        address = 0
        mbi = MEMORY_BASIC_INFORMATION()
        mbi_size = ctypes.sizeof(mbi)

        while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), mbi_size):
            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize or 0)
            if _is_readable_region(mbi) and 0 < size <= max_region_bytes:
                regions += 1
                for chunk in _read_region_chunks(handle, base, size):
                    bytes_read += len(chunk)
                    strings.update(_extract_candidates(chunk))
            next_address = base + max(size, 0x1000)
            if next_address <= address:
                break
            address = next_address
    finally:
        kernel32.CloseHandle(handle)

    return MemoryScanResult(strings=strings, regions=regions, bytes_read=bytes_read)


def _process_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _is_readable_region(mbi) -> bool:
    if int(mbi.State) != MEM_COMMIT:
        return False
    protect = int(mbi.Protect)
    if protect & PAGE_GUARD or protect & PAGE_NOACCESS:
        return False
    return bool(protect & PAGE_READABLE_MASK)


def _read_region_chunks(handle, base: int, size: int, chunk_size: int = 1024 * 1024):
    offset = 0
    while offset < size:
        wanted = min(chunk_size, size - offset)
        buf = ctypes.create_string_buffer(wanted)
        read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(base + offset),
            buf,
            wanted,
            ctypes.byref(read),
        )
        if ok and read.value:
            yield buf.raw[: read.value]
        offset += wanted


def _extract_candidates(chunk: bytes) -> set[str]:
    result: set[str] = set()
    for match in _ASCII_RE.finditer(chunk):
        text = match.group(0).decode("ascii", errors="ignore")
        if is_message_id_candidate(text):
            result.add(text)

    try:
        decoded = chunk.decode("utf-16le", errors="ignore")
    except UnicodeError:
        decoded = ""
    if decoded:
        for match in _TEXT_RE.finditer(decoded):
            text = match.group(0)
            if is_message_id_candidate(text):
                result.add(text)
    return result


def is_message_id_candidate(text: str) -> bool:
    text = (text or "").strip().strip("\x00")
    if not 4 <= len(text) <= 96:
        return False
    if not _TEXT_RE.fullmatch(text):
        return False
    if "\\" in text or os.sep in text:
        return False
    return bool(_TOKEN_RE.search(text))
