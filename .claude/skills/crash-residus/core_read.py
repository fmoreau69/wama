"""Lecteur minimal de core ELF x86-64 : signal, rip, cmdline, thread fautif, pile symbolisée (approx.)."""
import mmap
import struct
import sys

path = sys.argv[1]
f = open(path, 'rb')
m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

e_phoff, = struct.unpack_from('<Q', m, 0x20)
e_phentsize, e_phnum = struct.unpack_from('<HH', m, 0x36)
loads, notes = [], []
for i in range(e_phnum):
    p_type, p_flags, p_offset, p_vaddr, _, p_filesz, p_memsz, _ = struct.unpack_from('<IIQQQQQQ', m, e_phoff + i * e_phentsize)
    if p_type == 1:
        loads.append((p_vaddr, p_memsz, p_offset, p_filesz))
    elif p_type == 4:
        notes.append((p_offset, p_filesz))


def read(addr, n):
    for va, msz, off, fsz in loads:
        if va <= addr < va + fsz:
            return m[off + addr - va: off + min(addr - va + n, fsz)]
    return b''


REG = ['r15', 'r14', 'r13', 'r12', 'rbp', 'rbx', 'r11', 'r10', 'r9', 'r8', 'rax', 'rcx', 'rdx', 'rsi', 'rdi',
       'orig_rax', 'rip', 'cs', 'eflags', 'rsp', 'ss']
threads, files, psargs = [], [], ''
for off, sz in notes:
    pos = off
    while pos < off + sz:
        namesz, descsz, ntype = struct.unpack_from('<III', m, pos)
        pos += 12
        name = m[pos:pos + namesz].rstrip(b'\0')
        pos += (namesz + 3) & ~3
        desc = m[pos:pos + descsz]
        pos += (descsz + 3) & ~3
        if ntype == 1:  # PRSTATUS
            sig, = struct.unpack_from('<h', desc, 12)
            pid, = struct.unpack_from('<I', desc, 32)
            regs = dict(zip(REG, struct.unpack_from('<21Q', desc, 112)))
            threads.append((pid, sig, regs))
        elif ntype == 3:  # PSINFO
            psargs = desc[56:136].split(b'\0')[0].decode(errors='replace')
        elif ntype == 0x46494c45:  # NT_FILE
            count, pagesz = struct.unpack_from('<QQ', desc, 0)
            ents = [struct.unpack_from('<QQQ', desc, 16 + 24 * k) for k in range(count)]
            names = desc[16 + 24 * count:].split(b'\0')
            files = [(s, e, o * pagesz, names[k].decode(errors='replace')) for k, (s, e, o) in enumerate(ents)]


def where(addr):
    for s, e, o, n in files:
        if s <= addr < e:
            return f'{n.rsplit("/", 1)[-1]}+{hex(addr - s + o)}'
    return None


print('psargs :', psargs)
print('threads:', len(threads))
cur = threads[0]
print('thread fautif pid', cur[0], 'signal', cur[1], 'rip', hex(cur[2]['rip']), '->', where(cur[2]['rip']))
print('\n-- rip de chaque thread (regroupés) --')
from collections import Counter
print(Counter((where(t[2]['rip']) or '?').split('+')[0] for t in threads).most_common())
print('\n-- pile du thread fautif (adresses de retour plausibles) --')
rsp = cur[2]['rsp']
stack = read(rsp, 64 * 1024)
seen = 0
for k in range(0, len(stack) - 8, 8):
    v, = struct.unpack_from('<Q', stack, k)
    w = where(v)
    if w and ('.so' in w or 'python' in w):
        print(f'  [rsp+{hex(k)}] {w}')
        seen += 1
        if seen >= 60:
            break
