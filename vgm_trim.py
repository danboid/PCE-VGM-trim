# PC Engine (HuC6280) VGM File Inspector & Trimmer
# Written to trim .vgm files to make them playable using UzeC6280
# on Uzeboxes with only 128 Kb of SPI RAM
# by Dan MacDonald

import argparse
import gzip
import os
import struct
import sys


def read_vgm(file_path):
    """Reads raw bytes and decompresses in-memory if Gzip compressed."""
    with open(file_path, "rb") as f:
        raw_data = f.read()

    if raw_data.startswith(b"\x1f\x8b"):
        return bytearray(gzip.decompress(raw_data))

    return bytearray(raw_data)


def parse_vgm_header(data):
    """Parses VGM header fields across v1.00 - v1.71 specs."""
    if len(data) < 0x40 or data[:4] not in (b"VGM ", b"Vgm "):
        raise ValueError(
            f"File header does not start with valid magic bytes (Found: {data[:4]!r})"
        )

    vgm_version = struct.unpack_from("<I", data, 0x08)[0]
    data_offset_raw = struct.unpack_from("<I", data, 0x34)[0]

    if vgm_version >= 0x150 and data_offset_raw != 0:
        header_end = 0x34 + data_offset_raw
    else:
        header_end = 0x40

    if header_end >= len(data):
        raise ValueError(
            f"Header end offset (0x{header_end:X}) exceeds file size."
        )

    total_samples = struct.unpack_from("<I", data, 0x18)[0]
    loop_offset_raw = struct.unpack_from("<I", data, 0x1C)[0]
    loop_samples = struct.unpack_from("<I", data, 0x20)[0]

    loop_point = (0x1C + loop_offset_raw) if loop_offset_raw != 0 else None

    return header_end, total_samples, loop_samples, loop_point


def extract_gd3(data):
    """Extracts the complete GD3 tag block using offset pointer at 0x14."""
    gd3_offset_raw = struct.unpack_from("<I", data, 0x14)[0]
    if gd3_offset_raw != 0:
        gd3_abs_pos = 0x14 + gd3_offset_raw
        if gd3_abs_pos < len(data) and data[gd3_abs_pos : gd3_abs_pos + 4] == b"Gd3 ":
            if gd3_abs_pos + 12 <= len(data):
                tag_length = struct.unpack_from("<I", data, gd3_abs_pos + 8)[0]
                total_gd3_size = 12 + tag_length
                if gd3_abs_pos + total_gd3_size <= len(data):
                    return data[gd3_abs_pos : gd3_abs_pos + total_gd3_size]
                else:
                    return data[gd3_abs_pos:]
    return None


def trim_vgm(data, header_end, target_seconds, output_path, loop_samples, loop_point):
    """Trims sound commands up to target duration and appends original GD3 tags."""
    target_samples = int(target_seconds * 44100)
    current_samples = 0
    pos = header_end

    # Extract original GD3 tag block BEFORE we process or truncate payload
    gd3_payload = extract_gd3(data)

    # Copy header verbatim up to sound data payload start
    out_data = bytearray(data[:header_end])

    while pos < len(data):
        if current_samples >= target_samples:
            break

        cmd = data[pos]

        # End of Sound Data (0x66) - handle looping if enabled
        if cmd == 0x66:
            if loop_point and loop_samples > 0 and current_samples < target_samples:
                pos = loop_point
                continue
            else:
                break

        # Wait n samples (0x61 nn nn)
        elif cmd == 0x61:
            samples = struct.unpack_from("<H", data, pos + 1)[0]
            if current_samples + samples > target_samples:
                remaining_samples = target_samples - current_samples
                out_data.append(0x61)
                out_data.extend(struct.pack("<H", remaining_samples))
                current_samples = target_samples
                break
            else:
                out_data.extend(data[pos : pos + 3])
                current_samples += samples
                pos += 3

        # Wait 735 samples / 60th sec (0x62)
        elif cmd == 0x62:
            if current_samples + 735 > target_samples:
                remaining_samples = target_samples - current_samples
                out_data.append(0x61)
                out_data.extend(struct.pack("<H", remaining_samples))
                current_samples = target_samples
                break
            else:
                out_data.append(0x62)
                current_samples += 735
                pos += 1

        # Wait 882 samples / 50th sec (0x63)
        elif cmd == 0x63:
            if current_samples + 882 > target_samples:
                remaining_samples = target_samples - current_samples
                out_data.append(0x61)
                out_data.extend(struct.pack("<H", remaining_samples))
                current_samples = target_samples
                break
            else:
                out_data.append(0x63)
                current_samples += 882
                pos += 1

        # Short waits (0x70 - 0x7F: 1 to 16 samples)
        elif 0x70 <= cmd <= 0x7F:
            samples = (cmd & 0x0F) + 1
            if current_samples + samples > target_samples:
                remaining_samples = target_samples - current_samples
                if remaining_samples > 0:
                    out_data.append(0x70 + (remaining_samples - 1))
                current_samples = target_samples
                break
            else:
                out_data.append(cmd)
                current_samples += samples
                pos += 1

        # HuC6280 register write (0xB9 aa dd)
        elif cmd == 0xB9:
            out_data.extend(data[pos : pos + 3])
            pos += 3

        # Data block / PCM streaming payload (0x67)
        elif cmd == 0x67:
            block_len = struct.unpack_from("<I", data, pos + 3)[0]
            cmd_len = 7 + block_len
            out_data.extend(data[pos : pos + cmd_len])
            pos += cmd_len

        # Various command byte lengths
        elif 0x30 <= cmd <= 0x4F or cmd == 0x50:
            out_data.extend(data[pos : pos + 2])
            pos += 2
        elif 0x51 <= cmd <= 0x5F or 0xA0 <= cmd <= 0xBF:
            out_data.extend(data[pos : pos + 3])
            pos += 3
        elif 0xC0 <= cmd <= 0xDF:
            out_data.extend(data[pos : pos + 4])
            pos += 4
        elif 0xE0 <= cmd <= 0xFF:
            out_data.extend(data[pos : pos + 5])
            pos += 5
        else:
            out_data.append(cmd)
            pos += 1

    # End payload cleanly with 0x66 EOF marker
    if len(out_data) == 0 or out_data[-1] != 0x66:
        out_data.append(0x66)

    # Re-attach GD3 payload and write correct relative offset pointer to header 0x14
    if gd3_payload:
        relative_gd3_offset = len(out_data) - 0x14
        struct.pack_into("<I", out_data, 0x14, relative_gd3_offset)
        out_data.extend(gd3_payload)
    else:
        struct.pack_into("<I", out_data, 0x14, 0)

    # Maintain original 4-byte signature prefix
    out_data[:4] = data[:4]

    # Update header size and sample metadata fields
    final_file_size = len(out_data) - 4
    struct.pack_into("<I", out_data, 0x04, final_file_size)  # File size minus 4
    struct.pack_into("<I", out_data, 0x18, current_samples)  # Total sample count
    struct.pack_into("<I", out_data, 0x1C, 0)                # Clear loop offset
    struct.pack_into("<I", out_data, 0x20, 0)                # Clear loop sample count

    with open(output_path, "wb") as f:
        f.write(out_data)

    print(f"Trimmed file written to: {output_path}")
    print(f"New Duration: {current_samples / 44100.0:.2f} seconds")


def main():
    parser = argparse.ArgumentParser(
        description="PC Engine (HuC6280) VGM File Inspector & Trimmer",
        epilog="Examples:\n"
        "  python3 vgm_trim.py Dungeon.vgm\n"
        "  python3 vgm_trim.py Dungeon.vgm -t 77\n"
        "  python3 vgm_trim.py -t 77 Dungeon.vgm\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("file", nargs="?", help="Path to .vgm / .vgz file")
    parser.add_argument(
        "-t",
        "--trim",
        type=int,
        metavar="SECONDS",
        help="Trim duration in seconds",
    )
    parser.add_argument(
        "-l",
        "--loops",
        type=int,
        default=2,
        help="Number of loops to calculate total player duration (default: 2)",
    )
    parser.add_argument(
        "-f",
        "--fade",
        type=int,
        default=10,
        help="Fade-out time in seconds to add to total player duration (default: 10)",
    )

    args = parser.parse_args()

    if not args.file:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)

    try:
        data = read_vgm(args.file)
        header_end, total_samples, loop_samples, loop_point = parse_vgm_header(data)

        intro_samples = total_samples - loop_samples
        single_loop_sec = total_samples / 44100.0

        if loop_samples > 0:
            playback_samples = intro_samples + (loop_samples * args.loops) + (args.fade * 44100)
            player_sec = playback_samples / 44100.0
        else:
            player_sec = single_loop_sec

        if args.trim is not None:
            if args.trim <= 0:
                print("Error: Trim value must be a positive integer.")
                sys.exit(1)

            base, ext = os.path.splitext(args.file)
            out_path = f"{base}_trimmed{ext}"
            trim_vgm(data, header_end, args.trim, out_path, loop_samples, loop_point)
        else:
            print(f"File: {args.file}")
            print(f"Single Loop Duration: {single_loop_sec:.2f} seconds ({total_samples} samples)")
            if loop_samples > 0:
                print(f"Player Duration ({args.loops}x loop + {args.fade}s fade): {player_sec:.2f} seconds")

    except Exception as e:
        print(f"Error processing VGM file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
