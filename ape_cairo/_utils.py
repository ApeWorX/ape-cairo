from enum import Enum


class Extension(Enum):
    CAIRO = ".cairo"


def convert_bytecode_to_bytes(bytecode_list):
    def pad_hex(hex_str):
        # Remove '0x' prefix and pad to even length
        hex_str = hex_str[2:] if hex_str.startswith("0x") else hex_str
        return hex_str.zfill(len(hex_str) + len(hex_str) % 2)

    return b"".join(bytes.fromhex(pad_hex(hex_str)) for hex_str in bytecode_list)
