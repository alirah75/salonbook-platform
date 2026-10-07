"""Canonical Iranian mobile identifiers; formatting validation is not ownership proof."""

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_mobile(value: str) -> str:
    candidate = value.translate(DIGITS).strip()
    if len(candidate) > 32 or not re.fullmatch(r"[+0-9 ()-]+", candidate):
        raise ValueError("Enter a valid Iranian mobile number.")
    try:
        parsed = phonenumbers.parse(candidate, "IR")
    except NumberParseException:
        raise ValueError("Enter a valid Iranian mobile number.") from None
    if (
        parsed.country_code != 98
        or not phonenumbers.is_valid_number(parsed)
        or phonenumbers.number_type(parsed) != PhoneNumberType.MOBILE
    ):
        raise ValueError("Enter a valid Iranian mobile number.")
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
