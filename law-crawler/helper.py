import re


def convert_roman_to_num(roman_num):
    roman_num = str(roman_num).upper()
    roman_to_num = {"I": 10, "V": 50, "X": 100, "L": 500, "C": 1000, "D": 5000, "M": 10000}
    alphabet = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
    num = 0

    for i, roman_char in enumerate(roman_num):
        if roman_char not in roman_to_num:
            num += alphabet.index(roman_char) + 1 if roman_char in alphabet else 0
            continue

        previous = roman_to_num.get(roman_num[i - 1], 0) if i > 0 else 0
        current = roman_to_num[roman_char]
        num += current - 2 * previous if i > 0 and current > previous else current

    return num


def extract_input(input_string):
    match = re.search(r"\((.*?)\)", input_string or "")
    return match.group(1) if match else None
