import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_phone_number(value):
    """
    Validates phone number in international format.
    Accepts formats like: +41 79 123 4567, +1 555 123 4567, etc.
    """
    if not value:
        return  # Allow empty since field is optional
    
    # Remove all whitespace for validation
    cleaned = re.sub(r'\s+', '', value)
    
    # Check if starts with +
    if not cleaned.startswith('+'):
        raise ValidationError(
            _('Phone number must start with + followed by country code (e.g., +41 79 123 4567)'),
            code='invalid_phone_format'
        )
    
    # Remove + and check if remaining are all digits
    digits = cleaned[1:]
    if not digits.isdigit():
        raise ValidationError(
            _('Phone number can only contain digits, spaces, and + sign (e.g., +41 79 123 4567)'),
            code='invalid_phone_characters'
        )
    
    # Check maximum length (E.164 standard: max 15 digits)
    if len(digits) > 15:
        raise ValidationError(
            _('Phone number is too long. Maximum 15 digits allowed (E.164 standard).'),
            code='phone_too_long'
        )
    
    # Validate country code and minimum length
    # Common country codes: 1 (US/CA), 41 (Switzerland), 44 (UK), etc.
    country_code_length = 1
    min_total_digits = 10  # Minimum total digits (country code + number)
    
    if len(digits) >= 1 and digits[0] == '1':
        # US/Canada: country code 1, requires 10 digits total (1 + 10 = 11)
        country_code_length = 1
        min_total_digits = 11
    elif len(digits) >= 2:
        # Two-digit country codes (most common)
        two_digit_codes = ['20', '27', '30', '31', '32', '33', '34', '36', '39', '40', '41', '43', '44', '45', '46', '47', '48', '49', '51', '52', '53', '54', '55', '56', '57', '58', '60', '61', '62', '63', '64', '65', '66', '81', '82', '84', '86', '90', '91', '92', '93', '94', '95', '98']
        if digits[:2] in two_digit_codes:
            country_code_length = 2
            min_total_digits = 10  # 2 digit code + 8 digits minimum
        elif len(digits) >= 3:
            # Three-digit country codes (some countries)
            three_digit_codes = ['212', '213', '216', '218', '220', '221', '222', '223', '224', '225', '226', '227', '228', '229', '230', '231', '232', '233', '234', '235', '236', '237', '238', '239', '240', '241', '242', '243', '244', '245', '246', '247', '248', '249', '250', '251', '252', '253', '254', '255', '256', '257', '258', '260', '261', '262', '263', '264', '265', '266', '267', '268', '269', '290', '291', '297', '298', '299', '350', '351', '352', '353', '354', '355', '356', '357', '358', '359', '370', '371', '372', '373', '374', '375', '376', '377', '378', '380', '381', '382', '383', '385', '386', '387', '389', '420', '421', '423', '500', '501', '502', '503', '504', '505', '506', '507', '508', '509', '590', '591', '592', '593', '594', '595', '596', '597', '598', '599', '670', '672', '673', '674', '675', '676', '677', '678', '679', '680', '681', '682', '683', '684', '685', '686', '687', '688', '689', '690', '691', '692', '850', '852', '853', '855', '856', '880', '886', '960', '961', '962', '963', '964', '965', '966', '967', '968', '970', '971', '972', '973', '974', '975', '976', '977', '992', '993', '994', '995', '996', '998']
            if digits[:3] in three_digit_codes:
                country_code_length = 3
                min_total_digits = 10  # 3 digit code + 7 digits minimum
            else:
                # Single digit country code (2-9)
                country_code_length = 1
                min_total_digits = 10  # 1 digit code + 9 digits minimum
        else:
            # Single digit country code
            country_code_length = 1
            min_total_digits = 10
    
    # Check minimum total length
    if len(digits) < min_total_digits:
        raise ValidationError(
            _('Phone number is too short. Minimum {min} digits required (including country code).').format(min=min_total_digits),
            code='phone_too_short'
        )
    
    # Ensure we have enough digits after country code (at least 7 for most countries)
    remaining_digits = len(digits) - country_code_length
    min_remaining = 7 if country_code_length > 1 else 9  # US/Canada needs 10, others need 7-8
    if remaining_digits < min_remaining:
        raise ValidationError(
            _('Phone number must have at least {min} digits after the country code.').format(min=min_remaining),
            code='insufficient_digits'
        )


def validate_disposable_email(value):
    """
    Validates that the email address does not use a disposable domain.
    """
    disposable_domains = [
        'example.com',
        'mailinator.com',
        'guerrillamail.com',
        'yopmail.com',
        'trashmail.com',
        'temp-mail.org',
        'fake-mail.com',
        '10minutemail.com',
        'throwawaymail.com',
        'getairmail.com',
        'sharklasers.com',
        'dispostable.com',
        'mailautotrash.com',
        'tempmailo.com',
        'tempr.email',
        'tempmailcheck.com',
        'mohmal.com',
        'crazymailing.com',
        'dropmail.me',
        'emlhub.com',
        'maildrop.cc',
        'mintemail.com',
        'mytrashmail.com',
        'tempmail.net',
        'tmpmail.net',
        'spamgourmet.com',
        'spam4.me',
        'spamherelots.com',
        'spamthis.co.uk',
        'spamthis.com',
        'today.com.au',
    ]
    
    if not value or '@' not in value:
        return
        
    domain = value.split('@')[-1].lower()
    if domain in disposable_domains:
        raise ValidationError(
            _('Disposable email addresses are not allowed. Please use a valid email address.'),
            code='disposable_email'
        )


class PhoneNumberValidator:
    """
    Django validator class for phone numbers.
    Can be used in model fields and form fields.
    """
    def __call__(self, value):
        validate_phone_number(value)
    
    def __eq__(self, other):
        return isinstance(other, PhoneNumberValidator)
