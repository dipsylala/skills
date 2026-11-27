"""PDF handling: text layers, scanned pages as images."""

import os
import re
import struct
import zlib
from . import common


# ----------------------------------------------------------- page images -----
# Scanned accounts are PDFs of CCITT Group 4 fax images (or JPEGs). Decoding the fax
# images to PNG here lets an agent read them without pdftoppm, Pillow or OCR tools.

# T.4 run-length codes in run order: terminating codes for runs 0-63, then make-up codes for 64, 128, ... 2560.
_WHITE_TERM = """00110101 000111 0111 1000 1011 1100 1110 1111 10011 10100 00111 01000 001000 000011 110100 110101
    101010 101011 0100111 0001100 0001000 0010111 0000011 0000100 0101000 0101011 0010011 0100100 0011000 00000010
    00000011 00011010 00011011 00010010 00010011 00010100 00010101 00010110 00010111 00101000 00101001 00101010
    00101011 00101100 00101101 00000100 00000101 00001010 00001011 01010010 01010011 01010100 01010101 00100100
    00100101 01011000 01011001 01011010 01011011 01001010 01001011 00110010 00110011 00110100"""
_WHITE_MAKEUP = """11011 10010 010111 0110111 00110110 00110111 01100100 01100101 01101000 01100111 011001100 011001101
    011010010 011010011 011010100 011010101 011010110 011010111 011011000 011011001 011011010 011011011 010011000
    010011001 010011010 011000 010011011"""
_BLACK_TERM = """0000110111 010 11 10 011 0011 0010 00011 000101 000100 0000100 0000101 0000111 00000100 00000111
    000011000 0000010111 0000011000 0000001000 00001100111 00001101000 00001101100 00000110111 00000101000
    00000010111 00000011000 000011001010 000011001011 000011001100 000011001101 000001101000 000001101001
    000001101010 000001101011 000011010010 000011010011 000011010100 000011010101 000011010110 000011010111
    000001101100 000001101101 000011011010 000011011011 000001010100 000001010101 000001010110 000001010111
    000001100100 000001100101 000001010010 000001010011 000000100100 000000110111 000000111000 000000100111
    000000101000 000001011000 000001011001 000000101011 000000101100 000001011010 000001100110 000001100111"""
_BLACK_MAKEUP = """0000001111 000011001000 000011001001 000001011011 000000110011 000000110100 000000110101
    0000001101100 0000001101101 0000001001010 0000001001011 0000001001100 0000001001101 0000001110010
    0000001110011 0000001110100 0000001110101 0000001110110 0000001110111 0000001010010 0000001010011
    0000001010100 0000001010101 0000001011010 0000001011011 0000001100100 0000001100101"""
_SHARED_MAKEUP = """00000001000 00000001100 00000001101 000000010010 000000010011 000000010100 000000010101
    000000010110 000000010111 000000011100 000000011101 000000011110 000000011111"""


def _run_codes(term, makeup):
    codes = {c: run for run, c in enumerate(term.split())}
    codes.update({c: 64 * (i + 1) for i, c in enumerate((makeup + " " + _SHARED_MAKEUP).split())})
    return codes


_RUNS = (_run_codes(_WHITE_TERM, _WHITE_MAKEUP), _run_codes(_BLACK_TERM, _BLACK_MAKEUP))  # indexed by colour
# T.6 2D modes: a vertical offset (a1 = b1 + offset), "pass", "horizontal" or "end" (EOFB).
_MODES = {"1": 0, "011": 1, "010": -1, "000011": 2, "000010": -2, "0000011": 3, "0000010": -3,
          "0001": "pass", "001": "horizontal", "000000000001": "end"}


def _read_code(bits, p, table, longest):
    for n in range(1, longest + 1):
        value = table.get(bits[p:p + n])
        if value is not None:
            return value, p + n
    raise ValueError(f"bad CCITT code at bit {p}")


def _read_run(bits, p, colour):
    total = 0
    while True:
        run, p = _read_code(bits, p, _RUNS[colour], 13)
        total += run
        if run < 64:
            return total, p


def g4_rows(data, width, height):
    """Decode CCITT Group 4 (T.6) data: for each row, the positions where the colour
    changes, starting white (so black runs are [c0, c1), [c2, c3), ...)."""
    bits = bin(int.from_bytes(b"\x01" + data, "big"))[3:]
    p, ref = 0, [width] * 3
    for _ in range(height):
        cur, a0, colour, k = [], -1, 0, 0
        while a0 < width:
            while k > 0 and ref[k - 1] > a0:
                k -= 1
            while ref[k] <= a0 or k % 2 != colour:  # b1: next change on the row above to the opposite colour
                k += 1
            b1, b2 = ref[k], ref[k + 1]
            mode, p = _read_code(bits, p, _MODES, 12)
            if mode == "end":
                raise ValueError("data ends before the last row")
            if mode == "pass":
                a0 = b2
            elif mode == "horizontal":
                a0 = max(a0, 0)
                r1, p = _read_run(bits, p, colour)
                r2, p = _read_run(bits, p, 1 - colour)
                a1 = min(a0 + r1, width)
                a0 = min(a1 + r2, width)
                cur += [a1, a0]
            else:
                a0 = b1 + mode
                if not 0 <= a0 <= width:
                    raise ValueError(f"vertical code points outside the row ({a0})")
                cur.append(a0)
                colour = 1 - colour
        yield cur
        ref = cur + [width] * 3


# Limits on a fetched PDF's images, whose sizes the PDF itself declares: a scanned A4 page
# at 300 dpi is about 2500 x 3500 pixels, a 1 MB bitmap, from a ~100 KB fax stream.
MAX_PAGE_SIDE = 20000  # pixels; A0 at 600 dpi
MAX_PAGE_BITMAP = 64 * 1024 * 1024  # bytes of decoded 1-bit bitmap per page
MAX_PAGE_STREAM = 16 * 1024 * 1024  # bytes of encoded image data per page
MAX_PAGES = 1000


def _shrink_row(black, bits, scale, out_bits):
    """A row bitmap (pixel 0 in the top bit of `bits`) shrunk `scale` times: an
    output pixel is black when any of the `scale` input pixels it covers is."""
    spread = black
    for i in range(1, scale):
        spread |= black << i
    spread &= (1 << bits) - 1
    kept = format(spread, f"0{bits}b")[::scale]
    return int(kept.ljust(out_bits, "0")[:out_bits], 2)


def png_1bit(changes_by_row, width, height, invert=False, scale=1):
    """A black-and-white PNG from g4_rows output, optionally `scale` times smaller."""
    nbytes = (width + 7) // 8

    def rows():
        for changes in changes_by_row:
            black = 0
            for i in range(0, len(changes), 2):
                start, end = changes[i], changes[i + 1] if i + 1 < len(changes) else width
                if end > start:
                    black |= ((1 << (end - start)) - 1) << (nbytes * 8 - end)
            yield black
    return png_black_rows(rows(), width, height, invert, scale)


def flate_1bit_rows(data, width, height, invert=False):
    """Black-pixel rows of an uncompressed 1-bit DeviceGray bitmap (a FlateDecode
    scan, as in Brønnøysund's accounts copies): 0 is black unless `invert`."""
    nbytes = (width + 7) // 8
    if len(data) < nbytes * height:
        raise ValueError(f"image data of {len(data)} bytes is shorter than {width} x {height} pixels")
    full = (1 << nbytes * 8) - 1
    for y in range(height):
        row = int.from_bytes(data[y * nbytes:(y + 1) * nbytes], "big")
        yield row if invert else full ^ row


def png_black_rows(black_rows, width, height, invert=False, scale=1):
    """A black-and-white PNG from rows of black-pixel bits (most significant bit
    first), optionally `scale` times smaller."""
    nbytes = (width + 7) // 8
    if not (0 < width <= MAX_PAGE_SIDE and 0 < height <= MAX_PAGE_SIDE) or (nbytes + 1) * height > MAX_PAGE_BITMAP:
        raise ValueError(f"image of {width} x {height} pixels is larger than a scanned page")
    out_w, out_h = -(-width // scale), -(-height // scale)
    out_bytes = (out_w + 7) // 8
    full = (1 << out_bytes * 8) - 1
    raw, block, rows_in_block = bytearray(), 0, 0

    def add(black):
        if scale > 1:
            black = _shrink_row(black, nbytes * 8, scale, out_bytes * 8)
        raw.extend(b"\x00" + (black if invert else full ^ black).to_bytes(out_bytes, "big"))  # PNG: 1 is white
    for black in black_rows:
        block, rows_in_block = block | black, rows_in_block + 1
        if rows_in_block == scale:
            add(block)
            block, rows_in_block = 0, 0
    if rows_in_block:
        add(block)
    width, height = out_w, out_h

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


_PDF_STREAM_RE = re.compile(rb"\d+\s+\d+\s+obj((?:(?!endobj).)*?)\bstream\r?\n", re.S)


def pdf_images(pdf):
    """(dictionary, data) for each image in a PDF, in file order, which in scanned
    filings is page order."""
    for m in _PDF_STREAM_RE.finditer(pdf):
        d = m.group(1)
        if not re.search(rb"/Subtype\s*/Image\b", d):
            continue
        length, size = re.search(rb"/Length\s+(\d+)(?:\s+(\d+)\s+R)?", d), None
        if length and length.group(2):  # an indirect length: "8 0 R" points at "8 0 obj 12345 endobj"
            target = re.search(rb"\b%s\s+%s\s+obj\s*(\d+)\s*endobj" % (length.group(1), length.group(2)), pdf)
            size = int(target.group(1)) if target else None
        elif length:
            size = int(length.group(1))
        start = m.end()
        yield d, pdf[start:start + size] if size else pdf[start:pdf.find(b"endstream", start)].rstrip(b"\r\n")


def parse_pages(spec):
    """'1-3,7' -> {1, 2, 3, 7}"""
    pages = set()
    for part in filter(None, (x.strip() for x in spec.split(","))):
        lo, _, hi = part.partition("-")
        pages.update(range(int(lo), int(hi or lo) + 1))
    return pages


def page_images(pdf, out_dir, pages=None, scale=1):
    """Write each page image in a scanned PDF to out_dir as PNG (fax images) or JPEG.
    `scale` shrinks fax images that many times (JPEGs are saved as filed)."""
    os.makedirs(out_dir, exist_ok=True)
    count = written = 0
    for d, data in pdf_images(pdf):
        count += 1
        if count > MAX_PAGES:
            yield {"type": "error", "error": f"more than {MAX_PAGES} images; the rest were not read"}
            count -= 1
            break
        if pages and count not in pages:
            continue
        filters = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", d)
        filters = [f.decode() for f in re.findall(rb"/(\w+)", filters.group(1))] if filters else []
        size = re.search(rb"/Width\s+(\d+)", d), re.search(rb"/Height\s+(\d+)", d)
        width, height = (int(m.group(1)) for m in size) if all(size) else (None, None)
        base = {"image": count, "width": width, "height": height}  # as filed
        try:
            if filters == ["DCTDecode"]:
                ext, body = "jpg", data
            elif filters == ["CCITTFaxDecode"] and width and height:
                if len(data) > MAX_PAGE_STREAM:
                    raise ValueError(f"image data of {len(data)} bytes is larger than a scanned page")
                k = re.search(rb"/K\s+(-?\d+)", d)
                if not k or int(k.group(1)) >= 0:
                    raise ValueError("CCITT Group 3 images are not supported, only Group 4 (/K -1)")
                invert = (re.search(rb"/BlackIs1\s+true", d) is not None) != \
                    (re.search(rb"/Decode\s*\[\s*1(?:\.0*)?\s+0(?:\.0*)?\s*\]", d) is not None)
                ext, body = "png", png_1bit(g4_rows(data, width, height), width, height, invert, scale)
                base.update(width=-(-width // scale), height=-(-height // scale))  # as saved
            elif (filters == ["FlateDecode"] and width and height and re.search(rb"/BitsPerComponent\s+1(?!\d)", d)
                  and not re.search(rb"/DecodeParms", d)):
                z = zlib.decompressobj()
                try:
                    raw = z.decompress(data, MAX_PAGE_BITMAP + 1)
                except zlib.error as e:
                    raise ValueError(f"image data does not decompress: {e}") from e
                if len(raw) > MAX_PAGE_BITMAP or z.unconsumed_tail:
                    raise ValueError("image data is larger than a scanned page")
                invert = re.search(rb"/Decode\s*\[\s*1(?:\.0*)?\s+0(?:\.0*)?\s*\]", d) is not None
                ext = "png"
                body = png_black_rows(flate_1bit_rows(raw, width, height, invert), width, height, False, scale)
                base.update(width=-(-width // scale), height=-(-height // scale))  # as saved
            else:
                yield {"type": "uk_accounts_page_unsupported", **base, "filters": filters}
                continue
        except ValueError as e:
            yield {"type": "error", **base, "error": f"image {count}: {e}"}
            continue
        path = os.path.join(out_dir, f"page-{count:03d}.{ext}")
        with open(path, "wb") as f:
            f.write(body)
        written += 1
        yield {"type": "uk_accounts_page", **base, "path": path}
    note = ("image n is page n of the PDF, which is often not the page number printed on it (a cover page shifts "
            "them); cite both, as \"image 12 (printed p.10)\". Open the pages you need with your file reader")
    try:
        has_text = not written and bool(pdf_text(pdf))
    except ValueError:
        has_text = False
    if has_text:
        note = "no page images to save: this PDF was made by software and has a text layer; read it with mr.py pdf-text"
    yield {"type": "uk_accounts_pages", "images": count, "written": written, "out_dir": out_dir, "note": note}


# a PDF number; its parts cannot repartition, so a long digit run cannot make the matcher backtrack
_PDF_NUM = rb"-?(?:\d{1,32}(?:\.\d{0,32})?|\.\d{1,32})"
_PDF_TEXT_TOKEN_RE = re.compile(
    rb"\((?:\\.|[^\\)])*\)"            # literal string
    rb"|<[0-9A-Fa-f\s]*>"              # hex string
    rb"|\[|\]"
    rb"|/([^\s/\[\]()<>]+)\s+" + _PDF_NUM + rb"\s+Tf\b"   # font selection
    rb"|(" + _PDF_NUM + rb")\s+(" + _PDF_NUM + rb")\s+T[dD]\b"
    rb"|" + _PDF_NUM +
    rb"|T\*|Tj|TJ|'|\"|ET\b|BT\b", re.S)
_PDF_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                b"(": b"(", b")": b")", b"\\": b"\\"}
_PDF_OBJ_RE = re.compile(rb"(?<!\d)(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj\b", re.S)


def _pdf_literal(raw):
    out, i = bytearray(), 1
    while i < len(raw) - 1:
        c = raw[i:i + 1]
        if c == b"\\":
            nxt = raw[i + 1:i + 2]
            octal = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                i += 1 + len(octal.group(0))
                continue
            out += _PDF_ESCAPES.get(nxt, b"")
            i += 2
            continue
        out += c
        i += 1
    return bytes(out)


def _pdf_hex(raw):
    return bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", raw[1:-1]).decode().ljust(2, "0"))


MAX_PDF_OBJECTS = 200000
MAX_PDF_DECODED = common.MAX_BODY  # decompressed bytes across all of a PDF's streams


def _pdf_objects(pdf):
    """Object number -> (dictionary bytes, decoded stream bytes or None). Raises
    ValueError when the PDF holds too many objects or its streams decompress to
    more than MAX_PDF_DECODED bytes in all, so a fetched PDF cannot exhaust memory."""
    objects, decoded = {}, 0
    for m in _PDF_OBJ_RE.finditer(pdf):
        if len(objects) >= MAX_PDF_OBJECTS:
            raise ValueError(f"more than {MAX_PDF_OBJECTS} objects in the PDF")
        body = m.group(3)
        split = re.search(rb"\bstream\r?\n", body)
        if not split:
            objects[int(m.group(1))] = (body, None)
            continue
        d, data = body[:split.start()], body[split.end():]
        data = data[:data.rfind(b"endstream")].rstrip(b"\r\n")
        if re.search(rb"/Filter\s*/FlateDecode\b", d):
            z = zlib.decompressobj()
            try:
                data = z.decompress(data, min(MAX_PAGE_BITMAP, MAX_PDF_DECODED - decoded + 1))
            except zlib.error:
                data = None
            if z.unconsumed_tail:
                raise ValueError("a stream decompresses to more than a page's worth of data")
        elif re.search(rb"/Filter", d):
            data = None
        if data:
            decoded += len(data)
            if decoded > MAX_PDF_DECODED:
                raise ValueError(f"the PDF's streams decompress to more than {MAX_PDF_DECODED} bytes")
        objects[int(m.group(1))] = (d, data)
    return objects


def _pdf_resolve(objects, value):
    """An inline dictionary, or the one an `n 0 R` reference points at."""
    ref = re.fullmatch(rb"\s*(\d+)\s+\d+\s+R\s*", value or b"")
    return objects.get(int(ref.group(1)), (b"", None))[0] if ref else (value or b"")


def _pdf_dict_entry(d, key):
    """The value of /key in a dictionary: a reference, or a nested << >> dictionary."""
    m = re.search(rb"/" + key + rb"\s*(\d+\s+\d+\s+R|<<)", d)
    if not m:
        return None
    if m.group(1) != b"<<":
        return m.group(1)
    depth, i = 0, m.start(1)
    while i < len(d):
        if d.startswith(b"<<", i):
            depth, i = depth + 1, i + 2
        elif d.startswith(b">>", i):
            depth, i = depth - 1, i + 2
            if not depth:
                return d[m.start(1):i]
        else:
            i += 1
    return None


def _pdf_cmap(data):
    """A ToUnicode CMap as (code width in bytes, {code: text})."""
    out, width = {}, 1
    space = re.search(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>", data)
    if space:
        width = max(1, len(space.group(1)) // 2)

    def text(hexstr):
        return bytes.fromhex(hexstr.decode()).decode("utf-16-be", errors="replace")
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            out[int(src, 16)] = text(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block):
            lo, hi = int(lo, 16), int(hi, 16)
            if hi - lo > 65535:
                continue
            if dst.startswith(b"["):
                for i, item in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", dst)):
                    out[lo + i] = text(item)
            else:
                start = bytes.fromhex(dst[1:-1].decode())
                for i in range(hi - lo + 1):
                    last = int.from_bytes(start[-2:], "big") + i
                    out[lo + i] = (start[:-2] + last.to_bytes(2, "big")).decode("utf-16-be", errors="replace")
    return width, out


def _pdf_page_fonts(objects, page_dict, cache):
    """Font resource name -> (code width, ToUnicode map or None) for one page."""
    resources = _pdf_resolve(objects, _pdf_dict_entry(page_dict, b"Resources"))
    fonts = _pdf_resolve(objects, _pdf_dict_entry(resources, b"Font"))
    out = {}
    for name, num in re.findall(rb"/([^\s/\[\]()<>]+)\s*(\d+)\s+\d+\s+R", fonts):
        num = int(num)
        if num not in cache:
            font = objects.get(num, (b"", None))[0]
            tu = re.search(rb"/ToUnicode\s*(\d+)\s+\d+\s+R", font)
            data = objects.get(int(tu.group(1)), (b"", None))[1] if tu else None
            two_byte = re.search(rb"/Subtype\s*/Type0\b", font) is not None
            cache[num] = _pdf_cmap(data) if data else (2 if two_byte else 1, None)
        out[name] = cache[num]
    return out


def _pdf_decode(raw, font):
    width, cmap = font or (1, None)
    if cmap is None:
        return raw.decode("latin-1") if width == 1 else raw[1::2].decode("latin-1")
    codes = [int.from_bytes(raw[i:i + width], "big") for i in range(0, len(raw), width)]
    return "".join(cmap.get(c, "") for c in codes)


def pdf_content_text(content, fonts=None):
    """Text shown by a page content stream: strings drawn with Tj, TJ, ' and ",
    decoded through each font's ToUnicode map, with line breaks where the text moves down."""
    fonts, out, in_array, font = fonts or {}, [], False, None
    for m in _PDF_TEXT_TOKEN_RE.finditer(content):
        tok = m.group(0)
        if m.group(1) is not None:  # Tf
            font = fonts.get(m.group(1))
        elif m.group(2) is not None:  # Td / TD
            if float(m.group(3)) != 0:  # a move along the line only places the next glyph; spaces are glyphs
                out.append("\n")
        elif tok.startswith(b"("):
            out.append(_pdf_decode(_pdf_literal(tok), font))
        elif tok.startswith(b"<"):
            out.append(_pdf_decode(_pdf_hex(tok), font))
        elif tok == b"[":
            in_array = True
        elif tok == b"]":
            in_array = False
        elif in_array and re.fullmatch(_PDF_NUM, tok) and float(tok) < -200:
            out.append(" ")  # a wide kerning gap inside TJ is a space
        elif tok in (b"T*", b"'", b'"', b"ET"):
            out.append("\n")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", "".join(out))).strip()


def pdf_text(pdf):
    """The text layer of a PDF made by software (not a scan), one block per page,
    in file order."""
    objects, cache, blocks = _pdf_objects(pdf), {}, []
    for d, _ in list(objects.values()):
        if not re.search(rb"/Type\s*/Page\b(?!s)", d):
            continue
        fonts = _pdf_page_fonts(objects, d, cache)
        contents = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", d)
        refs = re.findall(rb"(\d+)\s+\d+\s+R", contents.group(1)) if contents else []
        content = b"\n".join(objects.get(int(r), (b"", None))[1] or b"" for r in refs)
        text = pdf_content_text(content, fonts)
        if text:
            blocks.append(text)
    return blocks


def pdf_text_records(pdf, source):
    blocks = pdf_text(pdf)
    if blocks:
        yield {"type": "pdf_text", "source": source, "blocks": len(blocks), "text": "\n\n".join(blocks)}
    else:
        yield {"type": "pdf_no_text", "source": source,
               "note": "no text layer (a scan); save its pages as images with mr.py uk-pages and read those"}
