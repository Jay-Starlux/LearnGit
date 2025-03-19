# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import re

AMEX_CC_RE = re.compile(r"^3[47][0-9]{13}$")
VISA_CC_RE = re.compile(r"^4[0-9]{12}(?:[0-9]{3})?$")
MASTERCARD_CC_RE = re.compile(r"^5[1-5][0-9]{14}$")
DISCOVER_CC_RE = re.compile(r"^6(?:011|5[0-9]{2})[0-9]{12}$")
DINERS_CLUB_CC_RE = re.compile(r"^3(?:0[0-5]|[68][0-9])[0-9]{11}$")
JCB_CC_RE = re.compile(r"^(?:2131|1800|3[0-9]\d{3})\d{11}$")

CC_MAP = {"americanexpress": AMEX_CC_RE, "visa": VISA_CC_RE,
          "mastercard": MASTERCARD_CC_RE, "discover": DISCOVER_CC_RE,
          "dinersclub": DINERS_CLUB_CC_RE, "jcb": JCB_CC_RE}


def cc_type(cc_number):
    for type, regexp in CC_MAP.items():
        if regexp.match(str(cc_number)):
            return type
    return None


def masknumber(number):
    number = number.replace(' ','')
    if len(number) <= 7:
        s = ''
        s = s.zfill(len(number)).replace('0', 'X')
        return s
    else:
        return 'XXXXXXXXXXXX' + number[len(number)-4:len(number)]

def mask_account_number(number):
    number = number.replace(' ','')
    if len(number) <= 4:
        return 'X'*len(number)
    else:
        return 'XXXXX' + number[len(number)-4:len(number)]
