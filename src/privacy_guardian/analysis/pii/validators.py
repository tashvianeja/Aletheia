from __future__ import annotations

import re


def luhn(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value)
    if not digits.isascii() or not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number *= 2
            number = number - 9 if number > 9 else number
        total += number
    return total % 10 == 0


IBAN_LENGTHS = {
    "AL": 28,
    "AD": 24,
    "AT": 20,
    "AZ": 28,
    "BH": 22,
    "BE": 16,
    "BA": 20,
    "BR": 29,
    "BG": 22,
    "CR": 22,
    "HR": 21,
    "CY": 28,
    "CZ": 24,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "FO": 18,
    "FI": 18,
    "FR": 27,
    "GE": 22,
    "DE": 22,
    "GI": 23,
    "GR": 27,
    "GL": 18,
    "GT": 28,
    "HU": 28,
    "IS": 26,
    "IE": 22,
    "IL": 23,
    "IT": 27,
    "JO": 30,
    "KZ": 20,
    "XK": 20,
    "KW": 30,
    "LV": 21,
    "LB": 28,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "MT": 31,
    "MR": 27,
    "MU": 30,
    "MD": 24,
    "MC": 27,
    "ME": 22,
    "NL": 18,
    "MK": 19,
    "NO": 15,
    "PK": 24,
    "PS": 29,
    "PL": 28,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "SM": 27,
    "SA": 24,
    "RS": 22,
    "SK": 24,
    "SI": 19,
    "ES": 24,
    "SE": 24,
    "CH": 21,
    "TL": 23,
    "TN": 24,
    "TR": 26,
    "UA": 29,
    "AE": 23,
    "GB": 22,
    "VA": 22,
    "VG": 24,
}


def iban_mod97(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", compact):
        return False
    if IBAN_LENGTHS.get(compact[:2]) != len(compact):
        return False
    remainder = 0
    for char in compact[4:] + compact[:4]:
        for digit in str(ord(char) - 55) if char.isalpha() else char:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def aba_checksum(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{9}", digits) or digits == "0" * 9:
        return False
    prefix = int(digits[:2])
    if not (1 <= prefix <= 12 or 21 <= prefix <= 32 or 61 <= prefix <= 72 or prefix == 80):
        return False
    return sum(int(d) * (3, 7, 1)[i % 3] for i, d in enumerate(digits)) % 10 == 0


def nhs_mod11(value: str) -> bool:
    digits = re.sub(r"\s", "", value)
    if not re.fullmatch(r"\d{10}", digits) or len(set(digits)) == 1:
        return False
    check = 11 - sum(int(d) * (10 - i) for i, d in enumerate(digits[:9])) % 11
    return check != 10 and (0 if check == 11 else check) == int(digits[-1])


def ssn_structure(value: str) -> bool:
    compact = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{9}", compact):
        return False
    area, group, serial = int(compact[:3]), int(compact[3:5]), int(compact[5:])
    return 0 < area < 900 and area != 666 and group != 0 and serial != 0


def mrz_check_digit(value: str) -> str:
    total = 0
    for index, char in enumerate(value.upper()):
        if char == "<":
            number = 0
        elif "0" <= char <= "9":
            number = int(char)
        elif "A" <= char <= "Z":
            number = ord(char) - 55
        else:
            return "!"
        total += number * (7, 3, 1)[index % 3]
    return str(total % 10)


def passport_mrz(value: str) -> bool:
    lines = [line.strip().upper() for line in value.splitlines() if line.strip()]
    if len(lines) != 2 or any(len(line) != 44 for line in lines):
        return False
    first, second = lines
    if not first.startswith("P") or not re.fullmatch(r"[A-Z0-9<]{44}", second):
        return False
    checks = ((second[:9], second[9]), (second[13:19], second[19]), (second[21:27], second[27]))
    if not all(mrz_check_digit(text) == check for text, check in checks):
        return False
    if second[42] != "<" and mrz_check_digit(second[28:42]) != second[42]:
        return False
    return mrz_check_digit(second[:10] + second[13:20] + second[21:43]) == second[43]


validate_luhn = luhn
validate_iban = iban_mod97
validate_aba = aba_checksum
validate_nhs = nhs_mod11
validate_ssn = ssn_structure
validate_passport_mrz = passport_mrz
