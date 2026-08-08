#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from asn1crypto import cms
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

CAPSULE_GUID = uuid.UUID("4a3ca68b-7723-48fb-803d-578cc1fec44d").bytes_le
SIGNED = 0x200


class Error(RuntimeError):
    pass


@dataclass
class Capsule:
    offset: int
    header_size: int
    image_size: int
    rom_image_offset: int
    table_start: int
    table_end: int
    areas: list[tuple[int, int, int, int, int]]
    cert: bytes
    signature_offset: int
    signature: bytes
    span: int
    base: int | None = None


def offsets(data: bytes | bytearray, needle: bytes) -> list[int]:
    found, pos = [], 0
    while (pos := data.find(needle, pos)) >= 0:
        found.append(pos)
        pos += 1
    return found


def der_size(data: bytes, off: int) -> int:
    if off + 2 > len(data) or data[off] != 0x30:
        raise Error("not DER")
    first = data[off + 1]
    if first < 0x80:
        return first + 2
    n = first & 0x7F
    if not 0 < n <= 4 or off + 2 + n > len(data):
        raise Error("unsupported DER length")
    return 2 + n + int.from_bytes(data[off + 2 : off + 2 + n], "big")


def rom_areas(data: bytes, cap: int, layout: int, header: int):
    start = cap + layout
    if not cap <= start < cap + header:
        raise Error("ROM_AREA table outside capsule header")

    areas, pos = [], start
    for _ in range(512):
        if pos + 24 > len(data):
            raise Error("truncated ROM_AREA table")
        entry = struct.unpack_from("<QIIII", data, pos)
        pos += 24
        if entry == (0, 0, 0, 0, 0):
            if not areas:
                raise Error("empty ROM_AREA table")
            return start, pos, areas
        if entry[2] == 0:
            raise Error("zero-sized ROM_AREA")
        areas.append(entry)
    raise Error("unterminated ROM_AREA table")


def cms_at(data: bytes, off: int, limit: int):
    try:
        size = der_size(data, off)
        if size < 256 or off + size > limit:
            return None
        blob = data[off : off + size]
        signed = cms.SignedData.load(blob, strict=True)
        if len(signed["certificates"]) != 1 or len(signed["signer_infos"]) != 1:
            return None
        if "sha256" not in [a["algorithm"].native for a in signed["digest_algorithms"]]:
            return None
        signer = signed["signer_infos"][0]
        if signer["signature_algorithm"]["algorithm"].native != "rsassa_pkcs1v15":
            return None

        cert = signed["certificates"][0].chosen.dump()
        sig = signer["signature"].native
        public = x509.load_der_x509_certificate(cert).public_key()
        if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 2048:
            return None
        if len(sig) != 256:
            return None

        cert_rel, sig_rel = blob.find(cert), blob.find(sig)
        if cert_rel < 0 or sig_rel < 0:
            return None
        return cert, off + sig_rel, sig
    except Exception:
        return None


def find_cms(data: bytes, cap: int, header: int):
    end = min(len(data), cap + header)
    found = [
        parsed
        for off in range(cap + 0x20, end)
        if data[off] == 0x30 and (parsed := cms_at(data, off, end)) is not None
    ]
    if len(found) != 1:
        raise Error(f"capsule {cap:#x}: expected one RSA/SHA256 SignedData, found {len(found)}")
    return found[0]


def capsules(data: bytes) -> list[Capsule]:
    result = []
    for cap in offsets(data, CAPSULE_GUID):
        try:
            if cap + 32 > len(data):
                continue
            header, _, image_size = struct.unpack_from("<III", data, cap + 16)
            rom_image, layout = struct.unpack_from("<HH", data, cap + 28)
            if not (0x40 <= header <= 0x10000 and cap + header <= len(data)):
                continue
            if not (header < image_size and 0 < rom_image < image_size and 0 < layout < header):
                continue

            table_start, table_end, areas = rom_areas(data, cap, layout, header)
            cert, sig_off, sig = find_cms(data, cap, header)
            span = image_size - rom_image
            if max(off + size for _, off, size, _, _ in areas) > span:
                continue

            result.append(
                Capsule(cap, header, image_size, rom_image, table_start, table_end,
                        areas, cert, sig_off, sig, span)
            )
        except Error:
            continue
    return sorted(result, key=lambda c: c.offset)


def shape(cap: Capsule):
    return cap.header_size, cap.image_size, cap.rom_image_offset, cap.areas


def pair(reference: list[Capsule], modified: list[Capsule]):
    if len(reference) != len(modified) or not reference:
        raise Error(f"SecureFlash capsule count changed ({len(reference)} -> {len(modified)})")
    pairs = list(zip(reference, modified))
    for ref, mod in pairs:
        if shape(ref) != shape(mod):
            raise Error(f"SecureFlash capsule structure changed near {ref.offset:#x}")
    return pairs


def digest(data: bytes | bytearray, cap: Capsule, base: int) -> bytes:
    if base < 0 or base + cap.span > len(data):
        raise Error("virtual ROM mapping outside file")
    h = hashlib.sha256()
    for _, off, size, _, attrs in cap.areas:
        if attrs & SIGNED:
            start, end = base + off, base + off + size
            if start < base or end > base + cap.span:
                raise Error("signed ROM_AREA outside virtual ROM")
            h.update(data[start:end])
    h.update(data[cap.table_start : cap.table_end])
    return h.digest()


def signature_valid(data: bytes, cap: Capsule, base: int) -> bool:
    try:
        x509.load_der_x509_certificate(cap.cert).public_key().verify(
            cap.signature,
            digest(data, cap, base),
            padding.PKCS1v15(),
            utils.Prehashed(hashes.SHA256()),
        )
        return True
    except Exception:
        return False


def find_base(reference: bytes, cap: Capsule) -> int:
    matches = [
        base
        for base in range(0, len(reference) - cap.span + 1, cap.span)
        if signature_valid(reference, cap, base)
    ]
    if len(matches) != 1:
        raise Error(f"capsule {cap.offset:#x}: OEM signature maps to {len(matches)} ROM domains")
    return matches[0]


def load_key(path: Path) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
        raise Error("SecureFlash key is not RSA-2048")
    return key


def clone_cert(template: bytes, key: rsa.RSAPrivateKey) -> bytes:
    cert = x509.load_der_x509_certificate(template)
    public = cert.public_key()
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 2048:
        raise Error("SecureFlash certificate is not RSA-2048")
    if cert.signature_hash_algorithm.name.lower() != "sha256":
        raise Error("SecureFlash certificate is not SHA-256 signed")

    try:
        old_ski = cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest
    except x509.ExtensionNotFound as exc:
        raise Error("SecureFlash certificate has no SKI") from exc

    old_mod = public.public_numbers().n.to_bytes(256, "big")
    old_sig = cert.signature
    mod_at, ski_at, sig_at = offsets(template, old_mod), offsets(template, old_ski), offsets(template, old_sig)
    if len(mod_at) != 1 or len(ski_at) != 1 or len(sig_at) != 1 or len(old_ski) != 20 or len(old_sig) != 256:
        raise Error("cannot uniquely patch X.509 template")

    out = bytearray(template)
    out[mod_at[0] : mod_at[0] + 256] = key.public_key().public_numbers().n.to_bytes(256, "big")
    out[ski_at[0] : ski_at[0] + 20] = x509.SubjectKeyIdentifier.from_public_key(key.public_key()).digest

    mutated = x509.load_der_x509_certificate(bytes(out))
    out[sig_at[0] : sig_at[0] + 256] = key.sign(
        mutated.tbs_certificate_bytes, padding.PKCS1v15(), hashes.SHA256()
    )

    final = x509.load_der_x509_certificate(bytes(out))
    final.public_key().verify(
        final.signature, final.tbs_certificate_bytes,
        padding.PKCS1v15(), final.signature_hash_algorithm,
    )
    return bytes(out)


def resign(reference: bytes, modified: bytes, key: rsa.RSAPrivateKey) -> bytes:
    ref_caps = capsules(reference)
    mod_caps = capsules(modified)
    pairs = pair(ref_caps, mod_caps)

    for ref, _ in pairs:
        ref.base = find_base(reference, ref)
        print(
            f"[+] capsule {ref.offset:#x}: span={ref.span:#x}, "
            f"base={ref.base:#x}, ROM_AREA entries={len(ref.areas)}"
        )

    image = bytearray(modified)
    replacements: dict[bytes, tuple[bytes, int]] = {}
    for old_cert in dict.fromkeys(ref.cert for ref, _ in pairs):
        cap_count = sum(ref.cert == old_cert for ref, _ in pairs)
        occurrences = offsets(image, old_cert)
        minimum = cap_count * 2  # CMS signer + standalone trust copy per observed H11 domain.
        if len(occurrences) < minimum:
            raise Error(f"SecureFlash certificate occurs {len(occurrences)} times; need at least {minimum}")
        new_cert = clone_cert(old_cert, key)
        for off in occurrences:
            image[off : off + len(old_cert)] = new_cert
        replacements[old_cert] = new_cert, minimum
        print(f"[+] replaced {len(occurrences)} SecureFlash certificate copies")

    # Certificate replacement can change bytes covered by the firmware digest.
    patched = capsules(bytes(image))
    patched_pairs = pair(ref_caps, patched)
    reports = []
    for ref, cap in patched_pairs:
        assert ref.base is not None
        d = digest(image, cap, ref.base)
        sig = key.sign(d, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
        if len(sig) != len(cap.signature):
            raise Error("firmware signature slot size changed")
        image[cap.signature_offset : cap.signature_offset + len(sig)] = sig
        reports.append((cap.offset, ref.base, d.hex()))

    final = bytes(image)
    final_pairs = pair(ref_caps, capsules(final))
    expected = key.public_key().public_numbers()
    for ref, cap in final_pairs:
        assert ref.base is not None
        cert = x509.load_der_x509_certificate(cap.cert)
        public = cert.public_key()
        if not isinstance(public, rsa.RSAPublicKey) or public.public_numbers() != expected:
            raise Error("final CMS certificate has the wrong key")
        public.verify(
            cap.signature, digest(final, cap, ref.base),
            padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()),
        )
        public.verify(
            cert.signature, cert.tbs_certificate_bytes,
            padding.PKCS1v15(), cert.signature_hash_algorithm,
        )

    for old_cert, (new_cert, minimum) in replacements.items():
        if offsets(final, old_cert):
            raise Error("OEM certificate remains in output")
        if len(offsets(final, new_cert)) < minimum:
            raise Error("replacement trust certificate copies disappeared")

    for i, (cap, base, d) in enumerate(reports, 1):
        print(f"[+] domain {i}: capsule={cap:#x} base={base:#x} SHA256={d}")
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-sign AMI SecureFlash after a UEFI edit")
    parser.add_argument("modified", type=Path, help="modified BIOS to sign")
    parser.add_argument("-r", "--reference", required=True, type=Path, help="original OEM-signed BIOS")
    parser.add_argument("-o", "--output", required=True, type=Path, help="signed output BIOS")
    parser.add_argument("--key", required=True, type=Path, help="persistent RSA-2048 PEM private key (created if absent)")
    args = parser.parse_args()

    try:
        reference, modified = args.reference.read_bytes(), args.modified.read_bytes()
        if len(reference) != len(modified):
            raise Error(f"whole-image size changed ({len(reference)} -> {len(modified)})")
        output = resign(reference, modified, load_key(args.key))
        args.output.write_bytes(output)
        print(f"[+] SHA256: {hashlib.sha256(output).hexdigest()}")
        return 0
    except (Error, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
